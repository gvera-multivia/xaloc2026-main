from __future__ import annotations

import asyncio
import os
import json
import logging
import sqlite3
import re
import zipfile
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any, Optional, Literal
from pathlib import Path
from datetime import datetime, timezone

import aiohttp
from PIL import Image
from fastapi import FastAPI, Query, HTTPException, Body, Request, WebSocket, WebSocketDisconnect, Header, Depends, status, UploadFile, File
from fastapi.responses import Response, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter

load_dotenv()

from dashboard.services import DashboardService, DashboardConflictError, DashboardNotFoundError
from dashboard.process_manager import ProcessManager
from core.xvia_auth import create_authenticated_session_in_place
from core.xvia_deselect import deselect_resource
from core.process_launcher import get_npm_command, start_async_process, terminate_process_tree
from core.redis_client import get_redis_client

app = FastAPI(title="Xaloc Realtime Dashboard", version="2.0.0")

AUTH_COOKIE_NAME = "dashboard_access_token"
AUTH_ROLE_COOKIE_NAME = "dashboard_role"
TOKEN_EXPIRE_MINUTES = max(5, int((os.getenv("DASHBOARD_TOKEN_EXPIRE_MINUTES") or "480").strip() or "480"))
AUTH_COOKIE_SECURE = (os.getenv("DASHBOARD_AUTH_COOKIE_SECURE") or "0").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_WS_REALTIME = (os.getenv("DASHBOARD_ENABLE_WS") or "0").strip().lower() in {"1", "true", "yes", "on"}
AUTH_RBAC_SERVICE_URL = (os.getenv("AUTH_RBAC_SERVICE_URL") or "http://auth-rbac-service:8101").strip().rstrip("/")

cors_origins_raw = (os.getenv("DASHBOARD_CORS_ORIGINS") or "").strip()
if cors_origins_raw:
    cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
else:
    cors_origins = [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

# Electron production (file://) sends Origin: null. Without this, Axios reports
# generic "Network Error" because CORS blocks credentialed requests.
if "null" not in cors_origins:
    cors_origins.append("null")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

process_manager = ProcessManager(base_dir=".", logs_dir="logs")
logger = logging.getLogger("dashboard_api")
CONTROL_PROCESS_NAMES = {"worker", "brain"}
_service_instance: DashboardService | None = None


class _LazyDashboardService:
    def _get(self) -> DashboardService:
        global _service_instance
        if _service_instance is None:
            _service_instance = DashboardService()
        return _service_instance

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


service = _LazyDashboardService()

FRONTEND_HOST = os.getenv("DASHBOARD_FRONTEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
FRONTEND_PORT = int((os.getenv("DASHBOARD_FRONTEND_PORT") or "3000").strip() or "3000")
FRONTEND_DEV = (os.getenv("DASHBOARD_FRONTEND_DEV") or "0").strip().lower() not in {"0", "false", "no", "off"}

_frontend_process: asyncio.subprocess.Process | None = None
_proxy_session: aiohttp.ClientSession | None = None
_prev_loop_exception_handler = None
_FRONTEND_LOG_PATH = Path("logs") / "frontend_out.log"
_RUNNER_LOG_PATH = Path("logs") / "playwright_runner_out.log"
_ISO_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)")
_WS_ACTIVE_CONNECTIONS = 0
_WS_DEBUG_STATS: dict[str, int] = {
    "accepted": 0,
    "rejected_missing_token": 0,
    "rejected_invalid_token": 0,
    "rejected_redis_unavailable": 0,
}


def _to_rgb_for_jpeg(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", image.size, (255, 255, 255))
        alpha = image.split()[-1]
        background.paste(image.convert("RGB"), mask=alpha)
        return background
    if image.mode == "P":
        if "transparency" in image.info:
            return _to_rgb_for_jpeg(image.convert("RGBA"))
        return image.convert("RGB")
    return image.convert("RGB")


def _encode_image_candidate(
    image: Image.Image,
    *,
    fmt: str,
    jpeg_quality: int,
    png_compress_level: int,
) -> tuple[bytes, dict[str, Any]]:
    tmp = BytesIO()
    if fmt == "JPEG":
        image.save(
            tmp,
            format="JPEG",
            quality=jpeg_quality,
            optimize=True,
            progressive=True,
        )
        return tmp.getvalue(), {
            "format": "JPEG",
            "quality": jpeg_quality,
            "optimize": True,
            "progressive": True,
        }
    image.save(
        tmp,
        format="PNG",
        optimize=True,
        compress_level=png_compress_level,
    )
    return tmp.getvalue(), {
        "format": "PNG",
        "optimize": True,
        "compress_level": png_compress_level,
    }


def _compress_pdf_images_in_writer(
    writer: PdfWriter,
    *,
    jpeg_quality: int,
    max_image_dim: int,
    min_gain_ratio: float,
    png_compress_level: int,
) -> tuple[int, int, int]:
    total_images = 0
    replaced_images = 0
    skipped_images = 0

    for page in writer.pages:
        for image_file in page.images:
            total_images += 1
            try:
                original_bytes = image_file.data or b""
                original_size = len(original_bytes)
                source = image_file.image

                if max_image_dim > 0:
                    width, height = source.size
                    biggest_side = max(width, height)
                    if biggest_side > max_image_dim:
                        ratio = max_image_dim / float(biggest_side)
                        new_size = (
                            max(1, int(width * ratio)),
                            max(1, int(height * ratio)),
                        )
                        source = source.resize(new_size, Image.Resampling.LANCZOS)

                jpeg_source = _to_rgb_for_jpeg(source)
                jpeg_bytes, jpeg_kwargs = _encode_image_candidate(
                    jpeg_source,
                    fmt="JPEG",
                    jpeg_quality=jpeg_quality,
                    png_compress_level=png_compress_level,
                )

                candidates: list[tuple[bytes, dict[str, Any], Image.Image]] = [
                    (jpeg_bytes, jpeg_kwargs, jpeg_source)
                ]
                if source.mode in {"1", "L", "P", "LA", "RGBA"}:
                    png_bytes, png_kwargs = _encode_image_candidate(
                        source,
                        fmt="PNG",
                        jpeg_quality=jpeg_quality,
                        png_compress_level=png_compress_level,
                    )
                    candidates.append((png_bytes, png_kwargs, source))

                best_data, best_kwargs, best_image = min(candidates, key=lambda x: len(x[0]))
                best_size = len(best_data)

                if original_size > 0:
                    target_size = int(original_size * (1.0 - min_gain_ratio))
                    if best_size >= target_size:
                        skipped_images += 1
                        continue

                image_file.replace(best_image, **best_kwargs)
                replaced_images += 1
            except Exception:
                skipped_images += 1

    return total_images, replaced_images, skipped_images


def _is_windows_connection_reset(context: dict[str, Any]) -> bool:
    exc = context.get("exception")
    if not isinstance(exc, ConnectionResetError):
        return False
    msg = str(exc)
    if "10054" in msg:
        return True
    handle = context.get("handle")
    handle_text = str(handle or "")
    return "_ProactorBasePipeTransport._call_connection_lost" in handle_text


def _loop_exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    if _is_windows_connection_reset(context):
        return
    if _prev_loop_exception_handler:
        _prev_loop_exception_handler(loop, context)
    else:
        loop.default_exception_handler(context)


async def _drain_frontend_logs(proc: asyncio.subprocess.Process) -> None:
    stream = proc.stdout
    if stream is None:
        return
    _FRONTEND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            msg = line.decode("utf-8", errors="replace").rstrip()
            if msg:
                ts = datetime.now(timezone.utc).isoformat()
                line_out = f"{ts} [frontend] {msg}"
                print(line_out)
                try:
                    with _FRONTEND_LOG_PATH.open("a", encoding="utf-8") as fh:
                        fh.write(f"{line_out}\n")
                except Exception:
                    pass
    except Exception:
        return


def _tail_text_file(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    safe_lines = min(max(int(lines), 1), 2000)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
        return [ln.rstrip("\n") for ln in all_lines[-safe_lines:]]
    except Exception:
        return []


def _line_sort_key(line: str, fallback_idx: int) -> tuple[str, int]:
    match = _ISO_TS_RE.match(line.strip())
    if not match:
        return ("", fallback_idx)
    return (match.group(1).replace(",", "."), fallback_idx)


def _merge_tail_text_files(paths: list[Path], lines: int) -> list[str]:
    safe_lines = min(max(int(lines), 1), 2000)
    combined: list[tuple[int, str]] = []
    idx = 0
    for path in paths:
        tail = _tail_text_file(path, safe_lines)
        for ln in tail:
            combined.append((idx, ln))
            idx += 1
    if not combined:
        return []
    combined.sort(key=lambda item: _line_sort_key(item[1], item[0]))
    return [ln for _, ln in combined[-safe_lines:]]


async def _wait_frontend_ready(timeout_seconds: float = 45.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    target = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/"
    timeout = aiohttp.ClientTimeout(total=2.5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while asyncio.get_running_loop().time() < deadline:
            try:
                async with session.get(target) as res:
                    if int(res.status) < 500:
                        return
            except Exception:
                pass
            await asyncio.sleep(0.4)
    raise RuntimeError(f"No se pudo arrancar frontend Next en {target} dentro de {timeout_seconds}s")


async def _start_frontend_server() -> None:
    global _frontend_process
    if _frontend_process and _frontend_process.returncode is None:
        return

    frontend_dir = Path("dashboard-frontend").resolve()
    if not frontend_dir.exists():
        raise RuntimeError(f"No existe el directorio frontend: {frontend_dir}")

    if FRONTEND_DEV:
        args = ["run", "dev", "--", "--hostname", FRONTEND_HOST, "--port", str(FRONTEND_PORT)]
        cmd = get_npm_command(args)
    else:
        # Build step
        build_args = ["run", "build"]
        build_cmd = get_npm_command(build_args)

        build_proc = await start_async_process(
            build_cmd,
            cwd=str(frontend_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert build_proc.stdout is not None
        while True:
            line = await build_proc.stdout.readline()
            if not line:
                break
            msg = line.decode("utf-8", errors="replace").rstrip()
            if msg:
                print(f"[frontend-build] {msg}")
        build_rc = await build_proc.wait()
        if int(build_rc or 0) != 0:
            raise RuntimeError(f"Fallo en npm run build (rc={build_rc})")

        # Start step
        args = ["run", "start", "--", "--hostname", FRONTEND_HOST, "--port", str(FRONTEND_PORT)]
        cmd = get_npm_command(args)

    _frontend_process = await start_async_process(
        cmd,
        cwd=str(frontend_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    asyncio.create_task(_drain_frontend_logs(_frontend_process))
    await _wait_frontend_ready()


async def _ensure_proxy_session() -> aiohttp.ClientSession:
    global _proxy_session
    if _proxy_session is not None and not _proxy_session.closed:
        return _proxy_session
    timeout = aiohttp.ClientTimeout(total=120)
    connector = aiohttp.TCPConnector(limit=100, enable_cleanup_closed=True)
    # Preserve upstream encoding as-is; otherwise browser can fail decoding.
    _proxy_session = aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        auto_decompress=False,
    )
    return _proxy_session


async def _stop_frontend_server() -> None:
    global _frontend_process
    proc = _frontend_process
    if not proc:
        return
    await terminate_process_tree(proc)
    _frontend_process = None


@app.on_event("startup")
async def app_startup() -> None:
    global _prev_loop_exception_handler
    loop = asyncio.get_running_loop()
    _prev_loop_exception_handler = loop.get_exception_handler()
    loop.set_exception_handler(_loop_exception_handler)
    if (os.getenv("DASHBOARD_ENABLE_FRONTEND_PROXY") or "1").strip().lower() in {"1", "true", "yes", "on"}:
        await _start_frontend_server()


@app.on_event("shutdown")
async def app_shutdown() -> None:
    global _proxy_session, _prev_loop_exception_handler
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_prev_loop_exception_handler)
    _prev_loop_exception_handler = None
    await process_manager.stop_all()
    if _proxy_session is not None and not _proxy_session.closed:
        await _proxy_session.close()
    _proxy_session = None
    if (os.getenv("DASHBOARD_ENABLE_FRONTEND_PROXY") or "1").strip().lower() in {"1", "true", "yes", "on"}:
        await _stop_frontend_server()

# ==========================================================================
# AUTH & REDIS
# ==========================================================================

def _extract_bearer_from_authorization(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _extract_token_from_websocket(websocket: WebSocket) -> Optional[str]:
    candidates = _extract_tokens_from_websocket(websocket)
    return candidates[0] if candidates else None


def _extract_tokens_from_websocket(websocket: WebSocket) -> list[str]:
    candidates: list[str] = []
    query_token = websocket.query_params.get("token")
    auth_header = websocket.headers.get("authorization")
    header_token = _extract_bearer_from_authorization(auth_header)
    cookie_token = websocket.cookies.get(AUTH_COOKIE_NAME)
    for token in (query_token, header_token, cookie_token):
        value = (token or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _token_exp_unverified(token: str) -> Optional[int]:
    try:
        payload_part = token.split(".")[1]
        padding = "=" * (-len(payload_part) % 4)
        raw = base64.urlsafe_b64decode(payload_part + padding)
        payload = json.loads(raw.decode("utf-8"))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return int(exp)
        return None
    except Exception:
        return None


def _extract_token_from_request(request: Request, authorization: Optional[str]) -> Optional[str]:
    header_token = _extract_bearer_from_authorization(authorization)
    if header_token:
        return header_token
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


async def _auth_introspect(token: str) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{AUTH_RBAC_SERVICE_URL}/auth/introspect",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth token")
            try:
                data = json.loads(body)
            except Exception as exc:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth service response invalid") from exc
            user = data.get("user")
            if not isinstance(user, dict):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth service did not return user")
            return user


async def get_current_user(request: Request, authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    token = _extract_token_from_request(request, authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing auth token")
    return await _auth_introspect(token)


async def require_user(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if str(user.get("role") or "").strip().lower() not in {"admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


async def _proxy_auth_service(
    *,
    method: str,
    path: str,
    request: Request,
    payload: dict[str, Any] | None = None,
) -> Response:
    timeout = aiohttp.ClientTimeout(total=30)
    headers: dict[str, str] = {}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header
    token_cookie = request.cookies.get(AUTH_COOKIE_NAME)
    role_cookie = request.cookies.get(AUTH_ROLE_COOKIE_NAME)
    cookie_header_parts: list[str] = []
    if token_cookie:
        cookie_header_parts.append(f"{AUTH_COOKIE_NAME}={token_cookie}")
    if role_cookie:
        cookie_header_parts.append(f"{AUTH_ROLE_COOKIE_NAME}={role_cookie}")
    if cookie_header_parts:
        headers["Cookie"] = "; ".join(cookie_header_parts)
    if payload is not None:
        headers["Content-Type"] = "application/json"

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(
            method=method,
            url=f"{AUTH_RBAC_SERVICE_URL}{path}",
            headers=headers,
            data=(json.dumps(payload) if payload is not None else None),
            allow_redirects=False,
        ) as upstream:
            body = await upstream.read()
            out = Response(content=body, status_code=upstream.status, media_type=upstream.headers.get("content-type"))
            for raw_cookie in upstream.headers.getall("Set-Cookie", []):
                out.headers.append("set-cookie", raw_cookie)
            return out


@app.post("/api/auth/login")
async def api_auth_login(request: Request, payload: dict[str, Any] = Body(...)) -> Response:
    return await _proxy_auth_service(method="POST", path="/auth/login", request=request, payload=payload)


@app.post("/api/auth/register")
async def api_auth_register(request: Request, payload: dict[str, Any] = Body(...)) -> Response:
    return await _proxy_auth_service(method="POST", path="/auth/register", request=request, payload=payload)


@app.get("/api/auth/me")
async def api_auth_me(request: Request, _user: dict[str, Any] = Depends(require_user)) -> Response:
    return await _proxy_auth_service(method="GET", path="/auth/me", request=request)


@app.post("/api/auth/logout")
async def api_auth_logout(request: Request) -> Response:
    return await _proxy_auth_service(method="POST", path="/auth/logout", request=request)


@app.get("/api/auth/users")
async def api_auth_list_users(request: Request, _admin: dict[str, Any] = Depends(require_admin)) -> Response:
    return await _proxy_auth_service(method="GET", path="/auth/users", request=request)


@app.post("/api/auth/users")
async def api_auth_create_user(
    request: Request,
    payload: dict[str, Any] = Body(...),
    _admin: dict[str, Any] = Depends(require_admin),
) -> Response:
    return await _proxy_auth_service(method="POST", path="/auth/users", request=request, payload=payload)


@app.put("/api/auth/users/{user_id}")
async def api_auth_update_user(
    request: Request,
    user_id: int,
    payload: dict[str, Any] = Body(...),
    _admin: dict[str, Any] = Depends(require_admin),
) -> Response:
    return await _proxy_auth_service(method="PUT", path=f"/auth/users/{int(user_id)}", request=request, payload=payload)


@app.delete("/api/auth/users/{user_id}")
async def api_auth_delete_user(
    request: Request,
    user_id: int,
    _admin: dict[str, Any] = Depends(require_admin),
) -> Response:
    return await _proxy_auth_service(method="DELETE", path=f"/auth/users/{int(user_id)}", request=request)


@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    global _WS_ACTIVE_CONNECTIONS
    logger.error(">>> WEBSOCKET HANDSHAKE REACHED ROUTE")
    if not ENABLE_WS_REALTIME:
        await websocket.close(code=1008, reason="Realtime disabled")
        return

    candidate_tokens = _extract_tokens_from_websocket(websocket)
    query_token = (websocket.query_params.get("token") or "").strip()
    header_token = (_extract_bearer_from_authorization(websocket.headers.get("authorization")) or "").strip()
    cookie_token = (websocket.cookies.get(AUTH_COOKIE_NAME) or "").strip()
    logger.warning(
        "WS auth candidates query=%s header=%s cookie=%s query_exp=%s header_exp=%s cookie_exp=%s",
        bool(query_token),
        bool(header_token),
        bool(cookie_token),
        _token_exp_unverified(query_token) if query_token else None,
        _token_exp_unverified(header_token) if header_token else None,
        _token_exp_unverified(cookie_token) if cookie_token else None,
    )
    if not candidate_tokens:
        _WS_DEBUG_STATS["rejected_missing_token"] += 1
        await websocket.close(code=4401, reason="Missing auth token")
        return

    authenticated = False
    for token in candidate_tokens:
        try:
            await _auth_introspect(token)
            authenticated = True
            break
        except HTTPException:
            continue

    if not authenticated:
        _WS_DEBUG_STATS["rejected_invalid_token"] += 1
        await websocket.close(code=4401, reason="Invalid auth token")
        return

    redis = get_redis_client()
    if not redis:
        _WS_DEBUG_STATS["rejected_redis_unavailable"] += 1
        await websocket.close(code=1013, reason="Realtime backend unavailable")
        return

    pubsub = None
    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe("channel:ui_updates")
    except Exception as exc:
        logger.warning("WebSocket realtime disabled: Redis unavailable (%s)", exc)
        if pubsub is not None:
            try:
                await pubsub.close()
            except Exception:
                pass
        await websocket.close(code=1013, reason="Realtime backend unavailable")
        return

    await websocket.accept()
    _WS_ACTIVE_CONNECTIONS += 1
    _WS_DEBUG_STATS["accepted"] += 1

    async def _forward_pubsub_to_ws() -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            raw_data = message.get("data")
            if isinstance(raw_data, bytes):
                text_data = raw_data.decode("utf-8", errors="replace")
            elif isinstance(raw_data, str):
                text_data = raw_data
            else:
                text_data = json.dumps(raw_data, ensure_ascii=False)
            await websocket.send_text(text_data)

    async def _watch_client_disconnect() -> None:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break

    sender_task = asyncio.create_task(_forward_pubsub_to_ws())
    watcher_task = asyncio.create_task(_watch_client_disconnect())

    try:
        done, pending = await asyncio.wait(
            {sender_task, watcher_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                logger.error(f"WebSocket task error: {exc}")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        _WS_ACTIVE_CONNECTIONS = max(0, _WS_ACTIVE_CONNECTIONS - 1)
        if pubsub is not None:
            try:
                await pubsub.unsubscribe("channel:ui_updates")
            except Exception:
                pass
            try:
                await pubsub.close()
            except Exception:
                pass

@app.post("/api/incidents/{id}/claim")
async def api_claim_incident(id: str, user: dict = Depends(require_user)):
    user_id = str(user.get("sub", "unknown"))
    username = user.get("username", "Unknown")
    try:
        lock_result = service.runtime_store.acquire_incident_lock(
            incident_id=id,
            user_id=user_id,
            username=username,
            ttl_seconds=1800,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not bool(lock_result.get("acquired")):
        owner = lock_result.get("owner_username") or lock_result.get("owner_id") or "otro usuario"
        raise HTTPException(status_code=409, detail=f"Incident already locked by {owner}")

    return {
        "status": "locked",
        "incident_id": id,
        "user_id": user_id,
        "username": username,
        "expires_at": lock_result.get("expires_at"),
    }

@app.post("/api/incidents/{id}/release")
async def api_release_incident(id: str, user: dict = Depends(require_user)):
    user_id = str(user.get("sub", "unknown"))
    role = user.get("role", "user")
    release_result = service.runtime_store.release_incident_lock(
        incident_id=id,
        user_id=user_id,
        is_admin=(str(role).strip().lower() == "admin"),
    )
    reason = str(release_result.get("reason") or "")
    if reason == "not_owner":
        raise HTTPException(status_code=403, detail="You do not own this lock")
    if reason == "not_locked":
        return {"status": "unlocked", "message": "Was not locked"}
    return {"status": "unlocked", "incident_id": id}


@app.delete("/api/incidents/{site_id}/{resource_id}")
async def api_resolve_incident(
    site_id: str,
    resource_id: int,
    incident_type: str | None = Query(None),
    _user: dict = Depends(require_user),
) -> dict:
    deleted = service.runtime_store.clear_incident(
        site_id=site_id,
        resource_id=resource_id,
        incident_type=incident_type or None,
    )
    return {"status": "resolved", "site_id": site_id, "resource_id": resource_id, "deleted": deleted}


@app.delete("/api/incidents/bulk")
async def api_resolve_incidents_bulk(
    site_id: str = Query(...),
    incident_type: str = Query(...),
    _user: dict = Depends(require_user),
) -> dict:
    deleted = service.runtime_store.clear_incidents_bulk(
        site_id=site_id,
        incident_type=incident_type,
    )
    return {"status": "resolved", "site_id": site_id, "incident_type": incident_type, "deleted": deleted}


# ==========================================================================
# EXISTING ROUTES
# ==========================================================================

@app.get("/api/history/days")
async def api_history_days(
    source: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: dict = Depends(require_user),
) -> dict:
    return service.list_history_days(source=source, page=page, page_size=page_size, user=user)


@app.get("/api/history/incidents")
async def api_history_incidents(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_user),
) -> dict:
    return service.list_history_incidents(day=day, page=page, page_size=page_size)


@app.get("/api/incidents")
async def api_incidents_pending(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_user),
) -> dict:
    result = service.list_pending_incidents(page=page, page_size=page_size)
    items = list(result.get("items") or [])

    def _resolve_incident_resource(item: dict[str, Any]) -> Optional[int]:
        raw = item.get("resource_id")
        if raw is None:
            payload = item.get("payload") or {}
            if isinstance(payload, dict):
                raw = payload.get("idRecurso")
                if raw is None:
                    raw = payload.get("resource_id")
        try:
            return int(raw) if raw is not None else None
        except Exception:
            return None

    incident_ids = []
    for it in items:
        rid = _resolve_incident_resource(it)
        it["resource_id"] = rid
        incident_ids.append(f"{it.get('site_id')}:{rid if rid is not None else 'none'}")

    locks = service.runtime_store.get_incident_locks(incident_ids=incident_ids)
    for item in items:
        rid = item.get("resource_id")
        incident_id = f"{item.get('site_id')}:{rid if rid is not None else 'none'}"
        lock_info = locks.get(incident_id)
        if lock_info:
            item["locked"] = True
            item["lock_user_id"] = lock_info.get("user_id")
            item["lock_username"] = lock_info.get("username")
            item["lock_expires_at"] = lock_info.get("expires_at")
        else:
            item["locked"] = False
            item["lock_user_id"] = None
            item["lock_username"] = None
            item["lock_expires_at"] = None
    result["items"] = items
    return result


@app.get("/api/history/successes")
async def api_history_successes(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    user: dict = Depends(require_user),
) -> dict:
    return service.list_history_successes(day=day, page=page, page_size=page_size, user=user)


@app.get("/api/history/top-users")
async def api_history_top_users(
    limit: int = Query(500, ge=1, le=5000),
    day: str | None = Query(None),
    user: dict = Depends(require_user),
) -> dict:
    return service.list_history_top_users(limit=limit, day=day, user=user)


@app.get("/api/queue/days")
async def api_queue_days(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    _user: dict = Depends(require_user),
) -> dict:
    return service.list_queue_days(page=page, page_size=page_size)


@app.get("/api/queue/current")
async def api_queue_current(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_user),
) -> dict:
    return service.list_queue_current(day=day, page=page, page_size=page_size)


@app.get("/api/queue/live")
async def api_queue_live(
    day: str | None = Query(None),
    _user: dict = Depends(require_user),
) -> dict:
    item = service.get_queue_live(day=day)
    if not item:
        raise HTTPException(status_code=404, detail="No active tramite")
    return item


@app.get("/api/queue/completion-marker")
async def api_queue_completion_marker(
    day: str | None = Query(None),
    _user: dict = Depends(require_user),
) -> dict:
    return service.get_queue_completion_marker(day=day)


from pathlib import Path as _Path

_LIVE_FRAME_PATH = _Path(__file__).parent.absolute() / "screenshots" / "live_frame.jpg"


def _novnc_force_local_scale(url: str) -> str:
    """Force noVNC local scaling (resize=scale) as default behavior."""
    parts = urlsplit(url)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    filtered_pairs = [(k, v) for k, v in query_pairs if k.lower() != "resize"]
    filtered_pairs.append(("resize", "scale"))
    new_query = urlencode(filtered_pairs, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


@app.get("/api/queue/live-viewer")
async def api_queue_live_viewer(request: Request, _user: dict = Depends(require_user)) -> dict:
    visual_enabled = (os.getenv("XALOC_VISUAL_DEBUG") or "1").strip().lower() in {"1", "true", "yes", "on"}
    if not visual_enabled:
        return {"enabled": False, "novnc_url": None}

    explicit_url = (os.getenv("XALOC_NOVNC_PUBLIC_URL") or "").strip()
    if explicit_url:
        return {"enabled": True, "novnc_url": _novnc_force_local_scale(explicit_url)}

    scheme = request.url.scheme or "http"
    host = request.url.hostname or "localhost"
    port = int((os.getenv("XALOC_NOVNC_PUBLIC_PORT") or "6080").strip() or "6080")
    novnc_quality = (os.getenv("XALOC_NOVNC_QUALITY") or "9").strip() or "9"
    novnc_compression = (os.getenv("XALOC_NOVNC_COMPRESSION") or "0").strip() or "0"
    novnc_url = (
        f"{scheme}://{host}:{port}/vnc.html"
        f"?autoconnect=1&quality={novnc_quality}&compression={novnc_compression}&resize=scale"
    )
    return {"enabled": True, "novnc_url": novnc_url}


@app.get("/api/queue/live-screenshot")
async def api_queue_live_screenshot(request: Request, _user: dict = Depends(require_user)):
    """Devuelve el ultimo frame JPEG del screencast CDP del worker."""
    if not _LIVE_FRAME_PATH.exists():
        raise HTTPException(status_code=404, detail="No hay frame en vivo")
    try:
        stat = _LIVE_FRAME_PATH.stat()
        frame_tag = f'{stat.st_mtime_ns}-{stat.st_size}'
        if request.headers.get("if-none-match") == frame_tag:
            return Response(
                status_code=304,
                headers={
                    "ETag": frame_tag,
                    "X-Frame-Stamp": frame_tag,
                    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        content = _LIVE_FRAME_PATH.read_bytes()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No hay frame en vivo")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo frame en vivo: {exc}") from exc

    return Response(
        content=content,
        media_type="image/jpeg",
        headers={
            "ETag": frame_tag,
            "X-Frame-Stamp": frame_tag,
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
@app.get("/api/control/status")
async def api_control_status(_admin: dict = Depends(require_admin)) -> dict:
    states = service.runtime_store.list_process_desired_states()
    return {
        "worker": "running" if states.get("worker", {}).get("desired_state") != "stopped" else "stopped",
        "brain": "running" if states.get("brain", {}).get("desired_state") != "stopped" else "stopped",
    }


@app.post("/api/control/{process_name}/start")
async def api_control_start(process_name: str, _admin: dict = Depends(require_admin)) -> dict:
    pname = str(process_name or "").strip().lower()
    if pname not in CONTROL_PROCESS_NAMES:
        raise HTTPException(status_code=400, detail="process_name invalido. Usa 'worker' o 'brain'.")
    state = service.runtime_store.set_process_desired_state(
        process_name=pname,
        desired_state="running",
        reason="dashboard_control_start",
    )
    return {
        "name": pname,
        "status": "running",
        "started": True,
        "control": state,
    }


@app.post("/api/control/{process_name}/stop")
async def api_control_stop(process_name: str, _admin: dict = Depends(require_admin)) -> dict:
    pname = str(process_name or "").strip().lower()
    if pname not in CONTROL_PROCESS_NAMES:
        raise HTTPException(status_code=400, detail="process_name invalido. Usa 'worker' o 'brain'.")
    state = service.runtime_store.set_process_desired_state(
        process_name=pname,
        desired_state="stopped",
        reason="dashboard_control_stop",
    )
    return {
        "name": pname,
        "status": "stopped",
        "stopped": True,
        "control": state,
    }


@app.post("/api/control/{process_name}/restart")
async def api_control_restart(process_name: str, _admin: dict = Depends(require_admin)) -> dict:
    pname = str(process_name or "").strip().lower()
    if pname not in CONTROL_PROCESS_NAMES:
        raise HTTPException(status_code=400, detail="process_name invalido. Usa 'worker' o 'brain'.")
    state = service.runtime_store.set_process_desired_state(
        process_name=pname,
        desired_state="running",
        reason="dashboard_control_restart",
    )
    return {
        "name": pname,
        "status": "running",
        "restarted": True,
        "control": state,
    }


@app.get("/api/logs/{process_name}")
async def api_logs_process(
    process_name: str,
    lines: int = Query(100, ge=1, le=2000),
    _admin: dict = Depends(require_admin),
) -> dict:
    pname = str(process_name or "").strip().lower()
    safe_lines = min(max(int(lines), 1), 2000)
    if pname == "frontend":
        status = "stopped"
        if _frontend_process and _frontend_process.returncode is None:
            status = "running"
        elif _frontend_process and _frontend_process.returncode not in (0, None):
            status = "error"
        return {
            "name": "frontend",
            "status": status,
            "lines": safe_lines,
            "stdout": _tail_text_file(_FRONTEND_LOG_PATH, safe_lines),
            "stderr": [],
        }
    if pname == "worker":
        return {
            "name": "worker",
            "status": process_manager.get_status("worker"),
            "lines": safe_lines,
            "stdout": _merge_tail_text_files([Path("logs") / "worker_out.log", _RUNNER_LOG_PATH], safe_lines),
            "stderr": [],
        }
    try:
        return process_manager.get_logs(pname, lines=safe_lines)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/queue/pauses")
async def api_queue_pauses(
    active_only: bool = Query(True),
    _admin: dict = Depends(require_admin),
) -> dict:
    items = service.list_processing_pauses(active_only=active_only)
    return {"items": items, "total": len(items)}


@app.post("/api/queue/pauses/{site_id}")
async def api_pause_site_processing(
    site_id: str,
    minutes: int | None = Query(None, ge=1),
    reason: str | None = Query(None),
    _admin: dict = Depends(require_admin),
) -> dict:
    try:
        return service.pause_site_processing(site_id=site_id, reason=reason, minutes=minutes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/queue/pauses/{site_id}")
async def api_unpause_site_processing(site_id: str, _admin: dict = Depends(require_admin)) -> dict:
    try:
        return service.unpause_site_processing(site_id=site_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/queue/item-pauses")
async def api_queue_item_pauses(
    active_only: bool = Query(True),
    _admin: dict = Depends(require_admin),
) -> dict:
    items = service.list_item_processing_pauses(active_only=active_only)
    return {"items": items, "total": len(items)}


@app.post("/api/queue/items/{site_id}/{resource_id}/pause")
async def api_pause_queue_item(
    site_id: str,
    resource_id: int,
    minutes: int | None = Query(None, ge=1),
    reason: str | None = Query(None),
    _admin: dict = Depends(require_admin),
) -> dict:
    try:
        return service.pause_queue_item_processing(
            site_id=site_id,
            resource_id=resource_id,
            reason=reason,
            minutes=minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/queue/items/{site_id}/{resource_id}/pause")
async def api_unpause_queue_item(site_id: str, resource_id: int, _admin: dict = Depends(require_admin)) -> dict:
    try:
        return service.unpause_queue_item_processing(site_id=site_id, resource_id=resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/queue/items/{site_id}/{resource_id}")
async def api_delete_queue_item(site_id: str, resource_id: int, _admin: dict = Depends(require_admin)) -> dict:
    try:
        result = service.remove_queue_item(site_id=site_id, resource_id=resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.get("removed"):
        return {
            "removed": False,
            "site_id": site_id,
            "resource_id": int(resource_id),
            "reason": result.get("reason") or "unknown",
            "recovery_attempted": bool(result.get("recovery_attempted")),
            "recovery_reason": result.get("recovery_reason"),
            "recovery_heartbeat_timeout_seconds": result.get("recovery_heartbeat_timeout_seconds"),
            "xvia_deselected": False,
        }

    email = (os.getenv("XVIA_EMAIL") or "").strip()
    password = (os.getenv("XVIA_PASSWORD") or "").strip()
    if not email or not password:
        raise HTTPException(
            status_code=500,
            detail="Elemento eliminado de cola, pero faltan XVIA_EMAIL/XVIA_PASSWORD para deseleccionar en XVIA.",
        )

    cookie_jar = aiohttp.CookieJar(unsafe=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/login",
        "Origin": "http://www.xvia-grupoeuropa.net",
        "Connection": "keep-alive",
    }
    async with aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar) as session:
        await create_authenticated_session_in_place(session, email, password)
        deselected = await deselect_resource(session, int(resource_id))

    return {
        "removed": True,
        "site_id": site_id,
        "resource_id": int(resource_id),
        "xvia_deselected": bool(deselected),
        "recovered_processing": bool(result.get("recovered_processing")),
    }


@app.post("/api/queue/items/{site_id}/{resource_id}/recover")
async def api_recover_queue_item(
    site_id: str,
    resource_id: int,
    heartbeat_timeout_seconds: int | None = Query(None, ge=1),
    _user: dict = Depends(require_user),
) -> dict:
    try:
        return service.recover_queue_item_processing(
            site_id=site_id,
            resource_id=resource_id,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/queue/recover-stuck")
async def api_recover_stuck_queue_items(
    heartbeat_timeout_seconds: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=2000),
    site_id: str | None = Query(None),
    resource_id: int | None = Query(None),
    _admin: dict = Depends(require_admin),
) -> dict:
    try:
        return service.recover_stuck_queue_items(
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            limit=limit,
            site_id=site_id,
            resource_id=resource_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/blacklist")
async def api_blacklist(site_id: str | None = Query(None), _user: dict = Depends(require_user)) -> dict:
    items = service.list_blacklist(site_id=site_id)
    return {"items": items, "total": len(items)}


@app.post("/api/blacklist")
async def api_blacklist_block(payload: dict[str, Any] = Body(...), _user: dict = Depends(require_user)) -> dict:
    try:
        site_id = str(payload.get("site_id") or "").strip()
        resource_id = int(payload.get("resource_id"))
        reason = payload.get("reason")
        source = payload.get("source") or "manual"
        return service.block_blacklist(
            site_id=site_id,
            resource_id=resource_id,
            reason=reason,
            source=source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}") from exc


@app.delete("/api/blacklist/{site_id}/{resource_id}")
async def api_blacklist_unblock(site_id: str, resource_id: int, _user: dict = Depends(require_user)) -> dict:
    try:
        return service.unblock_blacklist(site_id=site_id, resource_id=resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/config")
async def api_config_list(_admin: dict = Depends(require_admin)) -> dict:
    items = service.list_organismo_configs()
    return {"items": items, "total": len(items)}


@app.put("/api/config/{site_id}")
async def api_config_update(
    site_id: str,
    payload: dict[str, Any] = Body(...),
    _admin: dict = Depends(require_admin),
) -> dict:
    try:
        updates = dict(payload or {})
        return service.update_organismo_config(site_id=site_id, updates=updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/config/{site_id}/active")
async def api_config_set_active(
    site_id: str,
    payload: dict[str, Any] = Body(...),
    _admin: dict = Depends(require_admin),
) -> dict:
    if "active" not in payload:
        raise HTTPException(status_code=400, detail="Campo 'active' obligatorio.")
    try:
        active = bool(payload.get("active"))
        return service.set_organismo_active(site_id=site_id, active=active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ==========================================================================
# PENDING AUTHORIZATION QUEUE
# ==========================================================================


@app.get("/api/pending-auth")
async def api_pending_auth_list(
    authorization_type: str | None = Query(None),
    _user: dict = Depends(require_user),
) -> dict:
    try:
        return service.list_pending_authorizations(authorization_type=authorization_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/pending-auth/{pending_id}/approve")
async def api_pending_auth_approve(
    pending_id: int,
    user: dict[str, Any] = Depends(require_user),
) -> dict:
    try:
        return service.approve_pending_authorization(
            pending_id=pending_id,
            authorized_by=str(user.get("username") or "admin"),
        )
    except DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DashboardConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/pending-auth/{pending_id}/reject")
async def api_pending_auth_reject(
    pending_id: int,
    payload: dict[str, Any] = Body(...),
    user: dict[str, Any] = Depends(require_user),
) -> dict:
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Se requiere un motivo de rechazo.")
    try:
        return service.reject_pending_authorization(
            pending_id=pending_id,
            reason=reason,
            rejected_by=str(user.get("username") or "admin"),
        )
    except DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DashboardConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ==========================================================================
# CLIENT FOLDER (open in Explorer)
# ==========================================================================


@app.post("/api/client-folder")
async def api_client_folder(payload: dict[str, Any] = Body(...), _user: dict = Depends(require_user)) -> dict:
    """Calcula la ruta de la carpeta del cliente.

    Por defecto devuelve la ruta para que el frontend intente abrirla en el cliente.
    Si `open_on_server=true`, tambien intenta abrirla en el servidor.
    """
    try:
        result = service.resolve_client_folder(payload=payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Error resolviendo carpeta: {exc}") from exc

    open_on_server = bool(payload.get("open_on_server", False))
    folder_path = result.get("path", "")
    if open_on_server and result.get("exists") and folder_path:
        try:
            os.startfile(folder_path)
            result["opened"] = True
        except Exception as exc:
            result["opened"] = False
            result["open_error"] = str(exc)
    else:
        result["opened"] = False

    return result


_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

_ALERT_TEMPLATE_LEVELS = {"info", "warning", "critical"}
_TEMPLATES_DB_PATH = Path(
    (os.getenv("DASHBOARD_TEMPLATES_DB") or "db/notification_templates.db").strip()
    or "db/notification_templates.db"
)
_DEFAULT_ALERT_TEMPLATES = [
    {
        "id": "maintenance",
        "label": "Mantenimiento programado",
        "level": "warning",
        "title": "Mantenimiento programado",
        "body": "Habra mantenimiento en breve. Guarda trabajo y valida estado de tramites.",
    },
    {
        "id": "incident",
        "label": "Incidencia operativa",
        "level": "critical",
        "title": "Incidencia operativa",
        "body": "Se ha detectado una incidencia. Sigue las instrucciones del equipo tecnico.",
    },
    {
        "id": "info",
        "label": "Comunicado interno",
        "level": "info",
        "title": "Comunicado interno",
        "body": "Nuevo aviso operativo para los equipos conectados.",
    },
]


def _ensure_alert_templates_table() -> None:
    _TEMPLATES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_TEMPLATES_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_templates (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                level TEXT NOT NULL CHECK(level IN ('info','warning','critical')),
                design_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notification_templates_level ON notification_templates(level)"
        )
        conn.commit()


def _seed_alert_templates_if_empty() -> None:
    _ensure_alert_templates_table()
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_TEMPLATES_DB_PATH) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM notification_templates")
        if int(cur.fetchone()[0] or 0) > 0:
            return
        for tpl in _DEFAULT_ALERT_TEMPLATES:
            conn.execute(
                """
                INSERT INTO notification_templates (id, label, title, body, level, design_code, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tpl["id"],
                    tpl["label"],
                    tpl["title"],
                    tpl["body"],
                    tpl["level"],
                    tpl.get("design_code"),
                    now_iso,
                    now_iso,
                ),
            )
        conn.commit()


def _validate_alert_template_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, str]:
    data: dict[str, Any] = {}
    required = ["label", "title", "body", "level"] if not partial else []
    for key in required:
        value = str(payload.get(key) or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail=f"Campo '{key}' obligatorio.")

    for key in ["label", "title", "body", "level", "design_code"]:
        value = payload.get(key)
        if value is not None:
             data[key] = str(value).strip() if isinstance(value, str) else value

    if "level" in data and data["level"] not in _ALERT_TEMPLATE_LEVELS:
        raise HTTPException(status_code=400, detail="Campo 'level' invalido (info|warning|critical).")

    return data


def _template_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "label": str(row["label"]),
        "title": str(row["title"]),
        "body": str(row["body"]),
        "level": str(row["level"]),
        "design_code": row["design_code"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


@app.on_event("startup")
async def _startup_alert_templates() -> None:
    _seed_alert_templates_if_empty()


@app.get("/api/admin/notifications/templates")
async def api_admin_list_notification_templates(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    _ensure_alert_templates_table()
    with sqlite3.connect(_TEMPLATES_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, label, title, body, level, design_code, created_at, updated_at
            FROM notification_templates
            ORDER BY label COLLATE NOCASE ASC, id ASC
            """
        ).fetchall()
    items = [_template_row_to_dict(row) for row in rows]
    return {"items": items, "total": len(items)}


@app.post("/api/admin/notifications/templates")
async def api_admin_create_notification_template(
    payload: dict[str, Any] = Body(...),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    template_id = str(payload.get("id") or "").strip()
    if not template_id:
        raise HTTPException(status_code=400, detail="Campo 'id' obligatorio.")
    data = _validate_alert_template_payload(payload, partial=False)
    now_iso = datetime.now(timezone.utc).isoformat()
    _ensure_alert_templates_table()
    try:
        with sqlite3.connect(_TEMPLATES_DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO notification_templates (id, label, title, body, level, design_code, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    data["label"],
                    data["title"],
                    data["body"],
                    data["level"],
                    data.get("design_code"),
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"La plantilla '{template_id}' ya existe.") from exc
    return {
        "ok": True,
        "item": {
            "id": template_id,
            **data,
            "created_at": now_iso,
            "updated_at": now_iso,
        },
    }


@app.put("/api/admin/notifications/templates/{template_id}")
async def api_admin_update_notification_template(
    template_id: str,
    payload: dict[str, Any] = Body(...),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    template_id = str(template_id or "").strip()
    if not template_id:
        raise HTTPException(status_code=400, detail="template_id invalido.")
    data = _validate_alert_template_payload(payload, partial=True)
    if not data:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar.")
    now_iso = datetime.now(timezone.utc).isoformat()
    set_fields = [f"{key} = ?" for key in data.keys()]
    set_fields.append("updated_at = ?")
    values = [*data.values(), now_iso, template_id]

    _ensure_alert_templates_table()
    with sqlite3.connect(_TEMPLATES_DB_PATH) as conn:
        cur = conn.execute(
            f"UPDATE notification_templates SET {', '.join(set_fields)} WHERE id = ?",
            values,
        )
        if int(cur.rowcount or 0) == 0:
            raise HTTPException(status_code=404, detail=f"Plantilla '{template_id}' no encontrada.")
        conn.commit()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, label, title, body, level, design_code, created_at, updated_at
            FROM notification_templates
            WHERE id = ?
            """,
            (template_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Plantilla '{template_id}' no encontrada.")
    return {"ok": True, "item": _template_row_to_dict(row)}


@app.delete("/api/admin/notifications/templates/{template_id}")
async def api_admin_delete_notification_template(
    template_id: str,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    template_id = str(template_id or "").strip()
    if not template_id:
        raise HTTPException(status_code=400, detail="template_id invalido.")
    _ensure_alert_templates_table()
    with sqlite3.connect(_TEMPLATES_DB_PATH) as conn:
        cur = conn.execute("DELETE FROM notification_templates WHERE id = ?", (template_id,))
        if int(cur.rowcount or 0) == 0:
            raise HTTPException(status_code=404, detail=f"Plantilla '{template_id}' no encontrada.")
        conn.commit()
    return {"ok": True, "deleted": True, "id": template_id}


@app.get("/api/admin/notifications/debug")
async def api_admin_notifications_debug(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    redis = get_redis_client()
    debug_info: dict[str, Any] = {
        "ws_realtime_enabled": bool(ENABLE_WS_REALTIME),
        "redis_enabled_env": (os.getenv("REDIS_ENABLED") or "0").strip(),
        "redis_url_configured": bool((os.getenv("REDIS_URL") or "").strip()),
        "channel": "channel:ui_updates",
        "ws_active_connections": _WS_ACTIVE_CONNECTIONS,
        "ws_debug_stats": dict(_WS_DEBUG_STATS),
    }
    if not redis:
        debug_info["redis_available"] = False
        return debug_info

    debug_info["redis_available"] = True
    try:
        debug_info["redis_ping"] = bool(await redis.ping())
    except Exception as exc:
        debug_info["redis_ping"] = False
        debug_info["redis_ping_error"] = str(exc)

    try:
        raw = await redis.execute_command("PUBSUB", "NUMSUB", "channel:ui_updates")
        # Redis devuelve [channel, count] para un único canal.
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            debug_info["numsub_raw"] = raw
            try:
                debug_info["numsub"] = int(raw[1])
            except Exception:
                debug_info["numsub"] = 0
        else:
            debug_info["numsub_raw"] = raw
            debug_info["numsub"] = 0
    except Exception as exc:
        debug_info["numsub_error"] = str(exc)
        debug_info["numsub"] = 0

    return debug_info


@app.post("/api/admin/notifications/debug/publish")
async def api_admin_notifications_debug_publish(
    payload: dict[str, Any] = Body(default={}),
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    redis = get_redis_client()
    if not redis:
        raise HTTPException(status_code=503, detail="Redis no disponible.")

    title = str(payload.get("title") or "DEBUG ALERT").strip()
    body_text = str(payload.get("body") or "Ping de diagnostico de notificaciones.").strip()
    level = str(payload.get("level") or "info").strip().lower()
    if level not in _ALERT_TEMPLATE_LEVELS:
        raise HTTPException(status_code=400, detail="Campo 'level' invalido (info|warning|critical).")

    event = {
        "type": "admin.alert",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "title": title,
            "body": body_text,
            "level": level,
            "template_id": None,
            "internal_note": "debug_publish_endpoint",
            "sent_by": str(admin.get("username") or admin.get("sub") or "admin"),
        },
    }
    subscribers = await redis.publish("channel:ui_updates", json.dumps(event, ensure_ascii=False))
    return {
        "ok": True,
        "published_to_subscribers": int(subscribers),
        "event": event,
    }


@app.post("/api/admin/notifications/broadcast")
async def api_admin_broadcast_notification(
    payload: dict = Body(...),
    admin: dict = Depends(require_admin),
) -> dict:
    """
    Broadcast admin notification to all WebSocket listeners (Electron included).
    Publishes an 'admin.alert' event to Redis channel:ui_updates.
    """
    import json as _json
    from datetime import datetime, timezone

    title = str(payload.get("title") or "").strip()
    body_text = str(payload.get("body") or "").strip()
    level = str(payload.get("level") or "info").strip().lower()
    template_id = str(payload.get("template_id") or "").strip()
    internal_note = str(payload.get("internal_note") or "").strip()
    design_code = payload.get("design_code")

    if not title:
        raise HTTPException(status_code=400, detail="Campo 'title' obligatorio.")
    if not body_text:
        raise HTTPException(status_code=400, detail="Campo 'body' obligatorio.")
    if level not in _ALERT_TEMPLATE_LEVELS:
        raise HTTPException(status_code=400, detail="Campo 'level' invalido (info|warning|critical).")

    redis = get_redis_client()
    if not redis:
        raise HTTPException(status_code=503, detail="Redis no disponible para broadcast.")

    event = {
        "type": "admin.alert",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "title": title,
            "body": body_text,
            "level": level,
            "template_id": template_id or None,
            "internal_note": internal_note or None,
            "design_code": design_code or None,
            "sent_by": str(admin.get("username") or admin.get("sub") or "admin"),
        },
    }

    try:
        subscribers = await redis.publish("channel:ui_updates", _json.dumps(event, ensure_ascii=False))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo publicar la notificacion: {exc}") from exc

    return {"ok": True, "published_to_subscribers": int(subscribers), "event": event}


@app.post("/api/documentos/convert")
async def api_documentos_convert(files: list[UploadFile] = File(...)) -> Response:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    converted_files: list[tuple[str, bytes]] = []
    for upload in files:
        contents = await upload.read()
        try:
            image = Image.open(BytesIO(contents))
            if image.mode in {"RGBA", "P"}:
                image = image.convert("RGB")

            pdf_bytes = BytesIO()
            image.save(pdf_bytes, format="PDF", resolution=100.0)
            pdf_bytes.seek(0)

            base_name = os.path.splitext(upload.filename or "image")[0]
            converted_files.append((f"{base_name}.pdf", pdf_bytes.read()))
        except Exception as exc:
            logger.error("Error converting %s: %s", upload.filename, exc)
            raise HTTPException(
                status_code=400,
                detail=f"No se pudo convertir el archivo {upload.filename}. Asegurate de que sea una imagen valida.",
            ) from exc

    if len(converted_files) == 1:
        pdf_name, pdf_data = converted_files[0]
        return Response(
            content=pdf_data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{pdf_name}"'},
        )

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for pdf_name, pdf_data in converted_files:
            archive.writestr(pdf_name, pdf_data)
    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.read(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="conversiones.zip"'},
    )


@app.post("/api/documentos/bundle")
async def api_documentos_bundle(files: list[UploadFile] = File(...)) -> Response:
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="Se requieren al menos 2 archivos para fusionar")

    writer = PdfWriter()
    try:
        for upload in files:
            contents = await upload.read()
            writer.append(BytesIO(contents))

        output_buffer = BytesIO()
        writer.write(output_buffer)
        output_buffer.seek(0)
        return Response(
            content=output_buffer.read(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="documentos_fusionados.pdf"'},
        )
    except Exception as exc:
        logger.error("Error merging PDFs: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Error al fusionar los archivos. Verifica que sean PDFs validos.",
        ) from exc


@app.post("/api/documentos/compress")
async def api_documentos_compress(
    files: list[UploadFile] = File(...),
    profile: Literal["conservador", "equilibrado", "agresivo"] = Query(
        default="equilibrado",
        description="Perfil de compresion predefinido",
    ),
    quality: int | None = Query(default=None, ge=20, le=95, description="Calidad JPEG para imagenes embebidas"),
    max_dim: int | None = Query(default=None, ge=0, le=6000, description="Tamano maximo (px) de lado largo; 0 desactiva downscale"),
    min_gain_percent: int | None = Query(default=None, ge=0, le=80, description="Ganancia minima para sustituir una imagen"),
    png_compress_level: int | None = Query(default=None, ge=0, le=9, description="Nivel de compresion PNG (0-9)"),
) -> Response:
    if not files:
        raise HTTPException(status_code=400, detail="No file provided")

    upload = files[0]
    try:
        presets: dict[str, dict[str, int]] = {
            "conservador": {"quality": 70, "max_dim": 2400, "min_gain_percent": 2, "png_compress_level": 9},
            "equilibrado": {"quality": 55, "max_dim": 1800, "min_gain_percent": 3, "png_compress_level": 9},
            "agresivo": {"quality": 40, "max_dim": 1400, "min_gain_percent": 1, "png_compress_level": 9},
        }
        preset = presets[profile]
        final_quality = int(quality if quality is not None else preset["quality"])
        final_max_dim = int(max_dim if max_dim is not None else preset["max_dim"])
        final_min_gain_percent = int(min_gain_percent if min_gain_percent is not None else preset["min_gain_percent"])
        final_png_compress_level = int(png_compress_level if png_compress_level is not None else preset["png_compress_level"])

        contents = await upload.read()
        reader = PdfReader(BytesIO(contents))
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        total_images, replaced_images, skipped_images = _compress_pdf_images_in_writer(
            writer,
            jpeg_quality=final_quality,
            max_image_dim=final_max_dim,
            min_gain_ratio=float(final_min_gain_percent) / 100.0,
            png_compress_level=final_png_compress_level,
        )

        for page in writer.pages:
            page.compress_content_streams()

        output_buffer = BytesIO()
        writer.write(output_buffer)
        output_buffer.seek(0)

        original_size = len(contents)
        compressed_size = len(output_buffer.getvalue())
        output_bytes = output_buffer.getvalue()
        returned_bytes = output_bytes if compressed_size < original_size else contents
        returned_size = len(returned_bytes)
        compression_applied = returned_bytes is output_bytes
        compression_message = (
            "Compresion aplicada correctamente."
            if compression_applied
            else "No se ha conseguido comprimir mas el PDF."
        )
        base_name = os.path.splitext(upload.filename or "document")[0]
        out_filename = (
            f"{base_name}_comprimido.pdf"
            if compression_applied
            else f"{base_name}_original.pdf"
        )

        return Response(
            content=returned_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{out_filename}"',
                "X-Original-Size": str(original_size),
                "X-Compressed-Size": str(compressed_size),
                "X-Returned-Size": str(returned_size),
                "X-Compression-Applied": "1" if compression_applied else "0",
                "X-Compression-Message": compression_message,
                "X-Compression-Profile": profile,
                "X-Compression-Quality": str(final_quality),
                "X-Compression-Max-Dim": str(final_max_dim),
                "X-Compression-Min-Gain-Percent": str(final_min_gain_percent),
                "X-Compression-Png-Level": str(final_png_compress_level),
                "X-Compressed-Images-Total": str(total_images),
                "X-Compressed-Images-Replaced": str(replaced_images),
                "X-Compressed-Images-Skipped": str(skipped_images),
            },
        )
    except Exception as exc:
        logger.error("Error compressing PDF: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Error al comprimir el archivo. Verifica que sea un PDF valido.",
        ) from exc


@app.get("/api/test")
async def test_access():
    # First check the mount root itself
    mount_root = "/mnt/dptos"
    target_path = "/mnt/dptos/4 DPTO -  JURIDICO/CARPETAS VIRTUALES/PARA REVISAR - - - DEV Y ORGANISMOS LLAMADOS/ANNA Descargas/Adria Descargas/revisar"
    try:
        mount_ok = os.path.exists(mount_root)
        mount_contents = os.listdir(mount_root) if mount_ok else []
        target_exists = os.path.exists(target_path)
        target_files = os.listdir(target_path) if target_exists else []
        return {
            "mount_root_exists": mount_ok,
            "mount_root_contents": mount_contents[:20],  # Limit to 20 entries
            "target_exists": target_exists,
            "target_files": target_files[:20],
            "error": None
        }
    except Exception as e:
        return {
            "mount_root_exists": os.path.exists(mount_root),
            "target_exists": False,
            "target_files": [],
            "error": str(e)
        }


@app.get("/api/count")
async def count_files_endpoint() -> dict:
    import smtplib
    from email.mime.text import MIMEText

    STATE_FILE = "folder_state.json"
    SMTP_HOST = "smtp.ionos.es"
    SMTP_PORT = 587
    SMTP_USER = "gvera@xvia-serviciosjuridicos.com"
    SMTP_PASS = "NetMulti01"
    EMAIL_TO = "jara@multivia.net"

    def _load_state():
        if not os.path.exists(STATE_FILE):
            return None
        with open(STATE_FILE, "r") as f:
            return json.load(f)

    def _save_state(state):
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)

    def _send_email(previous, current):
        from datetime import datetime, timezone
        body = f"""
No se detectan cambios en la carpeta.

Archivos anteriores: {previous}
Archivos actuales: {current}

Fecha: {datetime.now(timezone.utc).isoformat()}
"""
        msg = MIMEText(body)
        msg["Subject"] = "Alerta: sin cambios en carpeta"
        msg["From"] = SMTP_USER
        msg["To"] = EMAIL_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

    try:
        total = 0
        folder_path = "/mnt/dptos/4 DPTO -  JURIDICO/CARPETAS VIRTUALES/PARA REVISAR - - - DEV Y ORGANISMOS LLAMADOS/ANNA Descargas/Adria Descargas/revisar"
        most_recent_file = None
        most_recent_time = 0.0

        for root, dirs, files in os.walk(folder_path):
            total += len(files)
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    mtime = os.path.getmtime(file_path)
                    if mtime > most_recent_time:
                        most_recent_time = mtime
                        most_recent_file = file
                except OSError:
                    pass

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        state = _load_state()
        previous_count = None if state is None else state.get("count")

        # Alert if count is the same as previous (no change)
        alert = (previous_count is not None and total == previous_count)

        if alert:
            try:
                _send_email(previous_count, total)
            except Exception as email_err:
                logger.error(f"Fallo al enviar email alerta: {email_err}")

        _save_state({"count": total, "checkedAt": now.isoformat()})

        response = {
            "ok": True,
            "count": total,
            "previous": previous_count,
            "alert": alert,
            "checkedAt": now.isoformat()
        }

        if most_recent_file:
            response["lastFile"] = most_recent_file
            try:
                dt = datetime.fromtimestamp(most_recent_time, tz=timezone.utc)
                response["lastModified"] = dt.isoformat()
            except Exception:
                pass

        return response
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


@app.api_route(
    "/{rest_of_path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def catch_all(rest_of_path: str, request: Request):
    if rest_of_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    if (os.getenv("DASHBOARD_ENABLE_FRONTEND_PROXY") or "1").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="Frontend proxy disabled on this service")

    if not _frontend_process or _frontend_process.returncode is not None:
        await _start_frontend_server()

    target_url = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/{rest_of_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    incoming_host = request.headers.get("host", "").strip()
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme or "http")
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = (request.client.host if request.client else "") or ""
    if forwarded_for and client_ip:
        x_forwarded_for = f"{forwarded_for}, {client_ip}"
    else:
        x_forwarded_for = forwarded_for or client_ip

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
    }
    if incoming_host:
        headers["host"] = incoming_host
    headers["x-forwarded-host"] = incoming_host or f"{FRONTEND_HOST}:{FRONTEND_PORT}"
    headers["x-forwarded-proto"] = forwarded_proto
    if x_forwarded_for:
        headers["x-forwarded-for"] = x_forwarded_for

    try:
        session = await _ensure_proxy_session()
        async with session.request(
            request.method,
            target_url,
            data=body if body else None,
            headers=headers,
            allow_redirects=False,
        ) as upstream:
            content = await upstream.read()
            out_headers = {
                key: value
                for key, value in upstream.headers.items()
                if key.lower() not in _HOP_BY_HOP_HEADERS and key.lower() != "content-length"
            }
            return Response(content=content, status_code=upstream.status, headers=out_headers)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error conectando con frontend Next: {exc}") from exc
