from __future__ import annotations

import asyncio
import os
import json
import logging
from typing import Any, Optional
from pathlib import Path

import aiohttp
from fastapi import FastAPI, Query, HTTPException, Body, Request, WebSocket, WebSocketDisconnect, Header, Depends, status
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

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
    cors_origins = ["http://127.0.0.1:3000", "http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = DashboardService()
process_manager = ProcessManager(base_dir=".", logs_dir="logs")
logger = logging.getLogger("dashboard_api")

FRONTEND_HOST = os.getenv("DASHBOARD_FRONTEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
FRONTEND_PORT = int((os.getenv("DASHBOARD_FRONTEND_PORT") or "3000").strip() or "3000")
FRONTEND_DEV = (os.getenv("DASHBOARD_FRONTEND_DEV") or "0").strip().lower() not in {"0", "false", "no", "off"}

_frontend_process: asyncio.subprocess.Process | None = None
_proxy_session: aiohttp.ClientSession | None = None
_prev_loop_exception_handler = None


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
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            msg = line.decode("utf-8", errors="replace").rstrip()
            if msg:
                print(f"[frontend] {msg}")
    except Exception:
        return


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
    token = websocket.query_params.get("token")
    if token:
        return token
    auth_header = websocket.headers.get("authorization")
    header_token = _extract_bearer_from_authorization(auth_header)
    if header_token:
        return header_token
    cookie_token = websocket.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
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
    if not ENABLE_WS_REALTIME:
        await websocket.close(code=1008, reason="Realtime disabled")
        return

    token = _extract_token_from_websocket(websocket)
    if not token:
        await websocket.close(code=4401, reason="Missing auth token")
        return
    try:
        await _auth_introspect(token)
    except HTTPException:
        await websocket.close(code=4401, reason="Invalid auth token")
        return

    redis = get_redis_client()
    if not redis:
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

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
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

# ==========================================================================
# EXISTING ROUTES
# ==========================================================================

@app.get("/api/history/days")
async def api_history_days(
    source: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    _user: dict = Depends(require_user),
) -> dict:
    return service.list_history_days(source=source, page=page, page_size=page_size)


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
    # For now, return incidents from today as "pending" list
    result = service.list_history_incidents(day=None, page=page, page_size=page_size)
    items = list(result.get("items") or [])
    incident_ids = [f"{it.get('site_id')}:{it.get('resource_id')}" for it in items]
    locks = service.runtime_store.get_incident_locks(incident_ids=incident_ids)
    for item in items:
        incident_id = f"{item.get('site_id')}:{item.get('resource_id')}"
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
    _user: dict = Depends(require_user),
) -> dict:
    return service.list_history_successes(day=day, page=page, page_size=page_size)


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


@app.get("/api/queue/live-screenshot")
async def api_queue_live_screenshot(_user: dict = Depends(require_user)):
    """Devuelve el ultimo frame JPEG del screencast CDP del worker."""
    if not _LIVE_FRAME_PATH.exists():
        raise HTTPException(status_code=404, detail="No hay frame en vivo")
    try:
        content = _LIVE_FRAME_PATH.read_bytes()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No hay frame en vivo")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo frame en vivo: {exc}") from exc

    return Response(
        content=content,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
@app.get("/api/control/status")
async def api_control_status(_admin: dict = Depends(require_admin)) -> dict:
    return process_manager.get_all_status()


@app.post("/api/control/{process_name}/start")
async def api_control_start(process_name: str, _admin: dict = Depends(require_admin)) -> dict:
    try:
        return await process_manager.start_process(process_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/control/{process_name}/stop")
async def api_control_stop(process_name: str, _admin: dict = Depends(require_admin)) -> dict:
    try:
        return await process_manager.stop_process(process_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/control/{process_name}/restart")
async def api_control_restart(process_name: str, _admin: dict = Depends(require_admin)) -> dict:
    try:
        return await process_manager.restart_process(process_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/logs/{process_name}")
async def api_logs_process(
    process_name: str,
    lines: int = Query(100, ge=1, le=2000),
    _admin: dict = Depends(require_admin),
) -> dict:
    try:
        return process_manager.get_logs(process_name, lines=lines)
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
