from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core.process_launcher import get_npm_command, start_async_process, terminate_process_tree

load_dotenv()

app = FastAPI(title="api-gateway", version="0.1.0")
logger = logging.getLogger("api_gateway")

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

FRONTEND_HOST = (os.getenv("DASHBOARD_FRONTEND_HOST") or "127.0.0.1").strip() or "127.0.0.1"
FRONTEND_PORT = int((os.getenv("DASHBOARD_FRONTEND_PORT") or "3000").strip() or "3000")
FRONTEND_DEV = (os.getenv("DASHBOARD_FRONTEND_DEV") or "0").strip().lower() not in {"0", "false", "no", "off"}
BACKEND_BASE_URL = (os.getenv("DASHBOARD_BACKEND_URL") or "http://dashboard-backend-service:8788").strip().rstrip("/")
MORRIGAN_RELEASE_DIR = Path(
    (os.getenv("MORRIGAN_RELEASE_DIR") or "/app/morrigan-electron/release").strip()
)
MORRIGAN_INSTALLER_PATTERN = (os.getenv("MORRIGAN_INSTALLER_PATTERN") or "Morrigan*.exe").strip() or "Morrigan*.exe"
MORRIGAN_MSI_PATTERN = (os.getenv("MORRIGAN_MSI_PATTERN") or "Morrigan*.msi").strip() or "Morrigan*.msi"
MORRIGAN_CONFIG_REFRESH_SEC = max(
    30, int((os.getenv("MORRIGAN_CONFIG_REFRESH_SEC") or "120").strip() or "120")
)
ELECTRON_AUTH_DEBUG = (os.getenv("ELECTRON_AUTH_DEBUG") or "1").strip().lower() in {"1", "true", "yes", "on"}
MORRIGAN_PROJECT_DIR = Path((os.getenv("MORRIGAN_PROJECT_DIR") or "morrigan-electron").strip()).resolve()
MORRIGAN_RELEASE_LOG_LIMIT = max(
    200, int((os.getenv("MORRIGAN_RELEASE_LOG_LIMIT") or "1200").strip() or "1200")
)

_frontend_process: asyncio.subprocess.Process | None = None
_proxy_session: aiohttp.ClientSession | None = None
_release_lock = asyncio.Lock()
_release_task: asyncio.Task | None = None
_release_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "requested_by": None,
    "version": None,
    "step": "idle",
    "ok": None,
    "error": None,
    "logs": [],
    "artifacts": None,
}

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


async def _drain_frontend_logs(proc: asyncio.subprocess.Process) -> None:
    stream = proc.stdout
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        msg = line.decode("utf-8", errors="replace").rstrip()
        if msg:
            print(f"[frontend] {msg}")


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
        build_cmd = get_npm_command(["run", "build"])
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
        rc = await build_proc.wait()
        if int(rc or 0) != 0:
            raise RuntimeError(f"Fallo en npm run build (rc={rc})")
        cmd = get_npm_command(["run", "start", "--", "--hostname", FRONTEND_HOST, "--port", str(FRONTEND_PORT)])

    _frontend_process = await start_async_process(
        cmd,
        cwd=str(frontend_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    asyncio.create_task(_drain_frontend_logs(_frontend_process))
    await _wait_frontend_ready()


async def _stop_frontend_server() -> None:
    global _frontend_process
    proc = _frontend_process
    if not proc:
        return
    await terminate_process_tree(proc)
    _frontend_process = None


async def _ensure_proxy_session() -> aiohttp.ClientSession:
    global _proxy_session
    if _proxy_session is not None and not _proxy_session.closed:
        return _proxy_session
    timeout = aiohttp.ClientTimeout(total=120)
    connector = aiohttp.TCPConnector(limit=100, enable_cleanup_closed=True)
    # Critical for multi-user WiFi deployments: avoid sharing upstream cookies across clients.
    # We only want to forward each incoming request Cookie/Authorization headers as-is.
    _proxy_session = aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        auto_decompress=False,
        cookie_jar=aiohttp.DummyCookieJar(),
    )
    return _proxy_session


async def _proxy_request(request: Request, target_url: str) -> Response:
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
    session = await _ensure_proxy_session()
    async with session.request(
        request.method,
        target_url,
        params=request.query_params,
        data=body if body else None,
        headers=headers,
        allow_redirects=False,
    ) as upstream:
        content = await upstream.read()
        out_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in _HOP_BY_HOP_HEADERS
            and key.lower() != "content-length"
            and key.lower() != "set-cookie"
        }
        out = Response(content=content, status_code=upstream.status, headers=out_headers)
        for raw_cookie in upstream.headers.getall("Set-Cookie", []):
            out.headers.append("set-cookie", raw_cookie)
        return out


def _extract_bearer_from_authorization(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()

def _mask_token(token: str | None) -> str:
    if not token:
        return "none"
    text = str(token)
    if len(text) <= 10:
        return f"{text[:2]}...{text[-2:]}"
    return f"{text[:6]}...{text[-4:]}"


def _copy_auth_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    authorization = request.headers.get("authorization")
    cookie = request.headers.get("cookie")
    if authorization:
        headers["Authorization"] = authorization
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def _require_authenticated_user(request: Request) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=10)
    raw_headers = _copy_auth_headers(request)
    header_token = _extract_bearer_from_authorization(request.headers.get("authorization"))
    cookie_token = request.cookies.get("dashboard_access_token")
    role_cookie = (request.cookies.get("dashboard_role") or "").strip().lower()
    allowed_roles = {"admin", "user", "consultor", "comercial", "cliente"}

    if ELECTRON_AUTH_DEBUG:
        logger.warning(
            "[electron-auth] path=%s role_cookie=%s has_auth_header=%s has_cookie_token=%s cookie_keys=%s bearer=%s cookie_token=%s",
            request.url.path,
            role_cookie or "none",
            bool(request.headers.get("authorization")),
            bool(cookie_token),
            ",".join(sorted(request.cookies.keys())) if request.cookies else "none",
            _mask_token(header_token),
            _mask_token(cookie_token),
        )

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 1) First try: forward incoming auth/cookie headers as-is.
        if raw_headers:
            async with session.get(f"{BACKEND_BASE_URL}/api/auth/me", headers=raw_headers) as upstream:
                body = await upstream.text()
                if ELECTRON_AUTH_DEBUG:
                    logger.warning(
                        "[electron-auth] forward-headers status=%s body=%s",
                        upstream.status,
                        (body[:220] if body else ""),
                    )
                if upstream.status < 400:
                    try:
                        payload = json.loads(body)
                    except Exception as exc:
                        raise HTTPException(status_code=502, detail="Invalid auth response") from exc
                    user = payload.get("user")
                    if isinstance(user, dict):
                        return user

        # 2) Fallback: force Authorization bearer from cookie/header token.
        token = header_token or cookie_token
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            async with session.get(f"{BACKEND_BASE_URL}/api/auth/me", headers=headers) as upstream:
                body = await upstream.text()
                if ELECTRON_AUTH_DEBUG:
                    logger.warning(
                        "[electron-auth] bearer-fallback status=%s body=%s",
                        upstream.status,
                        (body[:220] if body else ""),
                    )
                if upstream.status < 400:
                    try:
                        payload = json.loads(body)
                    except Exception as exc:
                        raise HTTPException(status_code=502, detail="Invalid auth response") from exc
                    user = payload.get("user")
                    if isinstance(user, dict):
                        return user

    # 3) Last fallback for dashboard sessions where role cookie exists but token validation fails transiently.
    if role_cookie in allowed_roles:
        if ELECTRON_AUTH_DEBUG:
            logger.warning("[electron-auth] role-cookie-fallback accepted role=%s", role_cookie)
        return {"username": "session-cookie", "role": role_cookie}

    if ELECTRON_AUTH_DEBUG:
        logger.warning("[electron-auth] authentication failed after all strategies")
    raise HTTPException(status_code=401, detail="Authentication required")


async def _require_admin_user(request: Request) -> dict[str, Any]:
    user = await _require_authenticated_user(request)
    role = str(user.get("role") or "").strip().lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def _release_log(line: str) -> None:
    text = str(line or "").rstrip()
    if not text:
        return
    logs = _release_state.setdefault("logs", [])
    logs.append(text)
    if len(logs) > MORRIGAN_RELEASE_LOG_LIMIT:
        del logs[: len(logs) - MORRIGAN_RELEASE_LOG_LIMIT]


def _validate_version(value: str) -> str:
    version = str(value or "").strip().lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise HTTPException(status_code=400, detail="Version invalida. Usa formato X.Y.Z")
    return version


def _update_morrigan_version(new_version: str) -> dict[str, Any]:
    package_json_path = MORRIGAN_PROJECT_DIR / "package.json"
    package_lock_path = MORRIGAN_PROJECT_DIR / "package-lock.json"

    if not package_json_path.exists():
        raise RuntimeError(f"No existe {package_json_path}")

    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    previous_version = str(package_json.get("version") or "").strip()
    if previous_version == new_version:
        return {"changed": False, "from": previous_version, "to": new_version}

    package_json["version"] = new_version
    package_json_path.write_text(json.dumps(package_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if package_lock_path.exists():
        package_lock = json.loads(package_lock_path.read_text(encoding="utf-8"))
        package_lock["version"] = new_version
        packages_root = package_lock.get("packages")
        if isinstance(packages_root, dict) and isinstance(packages_root.get(""), dict):
            packages_root[""]["version"] = new_version
        package_lock_path.write_text(json.dumps(package_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {"changed": True, "from": previous_version, "to": new_version}


async def _run_release_command(cmd: list[str], *, cwd: Path) -> int:
    proc = await start_async_process(
        cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        _release_log(line.decode("utf-8", errors="replace"))
    return int(await proc.wait() or 0)


def _resolve_release_artifacts() -> dict[str, Any]:
    if not MORRIGAN_RELEASE_DIR.exists():
        raise RuntimeError(f"No existe directorio release: {MORRIGAN_RELEASE_DIR}")

    latest_yml = MORRIGAN_RELEASE_DIR / "latest.yml"
    if not latest_yml.exists():
        raise RuntimeError("No se encontro latest.yml en release.")

    exe_files = sorted(
        [p for p in MORRIGAN_RELEASE_DIR.glob("*.exe") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not exe_files:
        raise RuntimeError("No se encontro instalador .exe en release.")
    installer = exe_files[0]

    blockmap = Path(str(installer) + ".blockmap")
    if not blockmap.exists():
        candidates = sorted(
            [p for p in MORRIGAN_RELEASE_DIR.glob("*.blockmap") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        blockmap = candidates[0] if candidates else None

    return {
        "releaseDir": str(MORRIGAN_RELEASE_DIR),
        "installer": {
            "name": installer.name,
            "sizeBytes": installer.stat().st_size,
            "url": f"/updates/{installer.name}",
        },
        "latestYml": {
            "name": latest_yml.name,
            "sizeBytes": latest_yml.stat().st_size,
            "url": f"/updates/{latest_yml.name}",
        },
        "blockmap": (
            {
                "name": blockmap.name,
                "sizeBytes": blockmap.stat().st_size,
                "url": f"/updates/{blockmap.name}",
            }
            if blockmap
            else None
        ),
    }


async def _run_release_pipeline(*, requested_by: str, version: str | None) -> None:
    async with _release_lock:
        _release_state.update(
            {
                "running": True,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "requested_by": requested_by,
                "version": version,
                "step": "prepare",
                "ok": None,
                "error": None,
                "logs": [],
                "artifacts": None,
            }
        )
        _release_log(f"[release] Iniciando pipeline en {MORRIGAN_PROJECT_DIR}")
        try:
            if version:
                _release_state["step"] = "version"
                version_result = _update_morrigan_version(version)
                if version_result.get("changed"):
                    _release_log(
                        f"[release] Version actualizada: {version_result.get('from')} -> {version_result.get('to')}"
                    )
                else:
                    _release_log(f"[release] Version ya estaba en {version}")

            _release_state["step"] = "build"
            cmd = get_npm_command(["run", "dist:nsis"])
            _release_log(f"[release] Ejecutando: {' '.join(cmd)} (cwd={MORRIGAN_PROJECT_DIR})")
            rc = await _run_release_command(cmd, cwd=MORRIGAN_PROJECT_DIR)
            if rc != 0:
                raise RuntimeError(f"Fallo npm run dist:nsis (rc={rc})")

            _release_state["step"] = "collect"
            artifacts = _resolve_release_artifacts()
            _release_state["artifacts"] = artifacts
            _release_log("[release] Artefactos listos y publicados en /updates")

            _release_state.update(
                {
                    "running": False,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "step": "done",
                    "ok": True,
                    "error": None,
                }
            )
        except Exception as exc:
            _release_log(f"[release] ERROR: {exc}")
            _release_state.update(
                {
                    "running": False,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "step": "failed",
                    "ok": False,
                    "error": str(exc),
                }
            )


def _resolve_latest_artifact(pattern: str, extension: str, *, required: bool) -> Path | None:
    if not MORRIGAN_RELEASE_DIR.exists():
        if required:
            raise HTTPException(
                status_code=404,
                detail=f"Installer directory not found: {MORRIGAN_RELEASE_DIR}",
            )
        return None
    candidates = [
        path
        for path in MORRIGAN_RELEASE_DIR.glob(pattern)
        if path.is_file() and path.suffix.lower() == extension.lower()
    ]
    if not candidates:
        if required:
            raise HTTPException(
                status_code=404,
                detail=f"No installer found in {MORRIGAN_RELEASE_DIR} matching {pattern}",
            )
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _resolve_morrigan_installer() -> Path:
    installer = _resolve_latest_artifact(MORRIGAN_INSTALLER_PATTERN, ".exe", required=True)
    assert installer is not None
    return installer


def _resolve_morrigan_msi() -> Path | None:
    return _resolve_latest_artifact(MORRIGAN_MSI_PATTERN, ".msi", required=False)


def _build_ws_url_from_api_base(api_base_url: str) -> str:
    parsed = urlsplit(api_base_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((ws_scheme, parsed.netloc, "/ws/dashboard", "", ""))


def _build_runtime_config(request: Request) -> dict[str, Any]:
    default_api = str(request.base_url).rstrip("/")
    api_base_url = (os.getenv("MORRIGAN_API_BASE_URL") or default_api).strip().rstrip("/")
    ws_url = (os.getenv("MORRIGAN_WS_URL") or _build_ws_url_from_api_base(api_base_url)).strip().rstrip("/")
    token = _extract_bearer_from_authorization(request.headers.get("authorization")) or request.cookies.get("dashboard_access_token")
    if token:
        separator = "&" if "?" in ws_url else "?"
        ws_url = f"{ws_url}{separator}token={token}"
    bootstrap_url = (
        os.getenv("MORRIGAN_BOOTSTRAP_URL")
        or f"{api_base_url}/morrigan-config.json"
    ).strip().rstrip("/")
    return {
        "apiBaseUrl": api_base_url,
        "wsUrl": ws_url,
        "bootstrapUrl": bootstrap_url,
        "refreshIntervalSec": MORRIGAN_CONFIG_REFRESH_SEC,
    }


def _backend_ws_url(path: str, query: str = "") -> str:
    if BACKEND_BASE_URL.startswith("https://"):
        base = "wss://" + BACKEND_BASE_URL[len("https://"):] + path
    elif BACKEND_BASE_URL.startswith("http://"):
        base = "ws://" + BACKEND_BASE_URL[len("http://"):] + path
    else:
        base = BACKEND_BASE_URL + path
    return f"{base}?{query}" if query else base


def _frontend_ws_url(path: str, query: str = "") -> str:
    base = f"ws://{FRONTEND_HOST}:{FRONTEND_PORT}{path}"
    return f"{base}?{query}" if query else base


async def _proxy_websocket(websocket: WebSocket, upstream_url: str, *, include_auth_headers: bool = False) -> None:
    await websocket.accept()
    headers: dict[str, str] = {}
    if include_auth_headers and websocket.headers.get("authorization"):
        headers["Authorization"] = str(websocket.headers.get("authorization"))
    if websocket.headers.get("cookie"):
        headers["Cookie"] = str(websocket.headers.get("cookie"))

    session = await _ensure_proxy_session()
    try:
        async with session.ws_connect(upstream_url, headers=headers) as upstream_ws:
            async def _client_to_upstream() -> None:
                while True:
                    msg = await websocket.receive()
                    msg_type = msg.get("type")
                    if msg_type == "websocket.disconnect":
                        await upstream_ws.close()
                        break
                    if msg_type != "websocket.receive":
                        continue
                    if msg.get("text") is not None:
                        await upstream_ws.send_str(str(msg["text"]))
                    elif msg.get("bytes") is not None:
                        await upstream_ws.send_bytes(bytes(msg["bytes"]))

            async def _upstream_to_client() -> None:
                async for msg in upstream_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await websocket.send_text(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await websocket.send_bytes(msg.data)
                    elif msg.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                        break

            await asyncio.gather(_client_to_upstream(), _upstream_to_client())
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=1011, reason="ws proxy error")


@app.on_event("startup")
async def app_startup() -> None:
    await _start_frontend_server()


@app.on_event("shutdown")
async def app_shutdown() -> None:
    global _proxy_session
    if _proxy_session is not None and not _proxy_session.closed:
        await _proxy_session.close()
    _proxy_session = None
    await _stop_frontend_server()


# ── Distribución de Morrigan (Auto-updates) ──────────────────────────────────
if MORRIGAN_RELEASE_DIR.exists():
    app.mount("/updates", StaticFiles(directory=str(MORRIGAN_RELEASE_DIR)), name="updates")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.get("/morrigan-config.json")
async def morrigan_public_config(request: Request) -> dict[str, Any]:
    return _build_runtime_config(request)


@app.get("/api/electron/download/info")
async def electron_download_info(request: Request) -> dict[str, Any]:
    user = await _require_authenticated_user(request)
    installer = _resolve_morrigan_installer()
    msi = _resolve_morrigan_msi()
    runtime = _build_runtime_config(request)
    msi_url = "/api/electron/download/installer-msi" if msi else None
    return {
        "installerName": installer.name,
        "installerSizeBytes": installer.stat().st_size,
        "msiName": msi.name if msi else None,
        "msiSizeBytes": (msi.stat().st_size if msi else None),
        "config": runtime,
        "downloadUrls": {
            "bundleZip": "/api/electron/download/bundle",
            "installer": "/api/electron/download/installer",
            "installerMsi": msi_url,
            "configJson": "/api/electron/download/config",
        },
        "user": {
            "username": user.get("username"),
            "role": user.get("role"),
        },
    }


@app.get("/api/electron/download/installer")
async def electron_download_installer(request: Request) -> StreamingResponse:
    await _require_authenticated_user(request)
    installer = _resolve_morrigan_installer()
    content = installer.read_bytes()
    headers = {
        "Content-Disposition": f'attachment; filename="{installer.name}"',
        "Content-Length": str(len(content)),
    }
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.microsoft.portable-executable",
        headers=headers,
    )


@app.get("/api/electron/download/installer-msi")
async def electron_download_installer_msi(request: Request) -> StreamingResponse:
    await _require_authenticated_user(request)
    msi = _resolve_morrigan_msi()
    if msi is None:
        raise HTTPException(status_code=404, detail="MSI installer not available")
    content = msi.read_bytes()
    headers = {
        "Content-Disposition": f'attachment; filename="{msi.name}"',
        "Content-Length": str(len(content)),
    }
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/x-msi",
        headers=headers,
    )


@app.get("/api/electron/download/config")
async def electron_download_config(request: Request) -> Response:
    await _require_authenticated_user(request)
    payload = _build_runtime_config(request)
    return Response(
        content=json.dumps(payload, ensure_ascii=True, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="config.json"'},
    )


@app.get("/api/electron/download/bundle")
async def electron_download_bundle(request: Request) -> StreamingResponse:
    await _require_authenticated_user(request)
    installer = _resolve_morrigan_installer()
    runtime = _build_runtime_config(request)

    installer_name = installer.name
    install_script_name = "instalar_morrigan_plug_and_play.bat"
    install_script = (
        "@echo off\r\n"
        "setlocal\r\n"
        "set TARGET=%APPDATA%\\Morrigan\r\n"
        "if not exist \"%TARGET%\" mkdir \"%TARGET%\"\r\n"
        "copy /Y \"config.json\" \"%TARGET%\\config.json\" >nul\r\n"
        f"if exist \"{installer_name}\" start \"\" \"{installer_name}\"\r\n"
        "echo.\r\n"
        "echo Configuracion aplicada en %TARGET%\\config.json\r\n"
        "echo Si el instalador no se abrio, ejecuta manualmente el .exe incluido.\r\n"
        "pause\r\n"
    )
    readme = (
        "MORRIGAN - Pack Plug and Play\r\n"
        "1) Extrae este ZIP en cualquier carpeta.\r\n"
        f"2) Ejecuta {install_script_name} como usuario normal.\r\n"
        "3) Se copiara config.json a %APPDATA%\\Morrigan y se lanzara el instalador.\r\n"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(installer, arcname=installer_name)
        zf.writestr("config.json", json.dumps(runtime, ensure_ascii=True, indent=2))
        zf.writestr(install_script_name, install_script)
        zf.writestr("README.txt", readme)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="Morrigan-PlugAndPlay.zip"'},
    )


@app.get("/api/admin/electron/release/status")
async def admin_electron_release_status(request: Request) -> dict[str, Any]:
    await _require_admin_user(request)
    return dict(_release_state)


@app.post("/api/admin/electron/release/build")
async def admin_electron_release_build(
    request: Request,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global _release_task
    admin = await _require_admin_user(request)
    body = payload or {}
    requested_version_raw = str(body.get("version") or "").strip()
    requested_version = _validate_version(requested_version_raw) if requested_version_raw else None
    requested_by = str(admin.get("username") or admin.get("sub") or "admin")

    if _release_task is not None and not _release_task.done():
        raise HTTPException(status_code=409, detail="Ya hay un release en curso.")

    _release_task = asyncio.create_task(
        _run_release_pipeline(requested_by=requested_by, version=requested_version)
    )
    return {
        "ok": True,
        "accepted": True,
        "requested_by": requested_by,
        "version": requested_version,
        "statusUrl": "/api/admin/electron/release/status",
    }


@app.websocket("/ws/dashboard")
async def proxy_ws_dashboard(websocket: WebSocket) -> None:
    query = str(websocket.url.query or "")
    await _proxy_websocket(websocket, _backend_ws_url("/ws/dashboard", query), include_auth_headers=True)


@app.websocket("/_next/webpack-hmr")
async def proxy_ws_frontend_hmr(websocket: WebSocket) -> None:
    # Next.js dev HMR channel.
    query = str(websocket.url.query or "")
    await _proxy_websocket(websocket, _frontend_ws_url("/_next/webpack-hmr", query), include_auth_headers=False)


@app.api_route("/api/admin/{rest_of_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_admin_api(rest_of_path: str, request: Request) -> Response:
    """Explicitly proxy admin routes to backend to avoid conflicts with frontend paths."""
    target_url = f"{BACKEND_BASE_URL}/api/admin/{rest_of_path}"
    if ELECTRON_AUTH_DEBUG:
        logger.warning("[proxy-admin] method=%s path=%s target=%s", request.method, rest_of_path, target_url)
    try:
        return await _proxy_request(request, target_url=target_url)
    except Exception as exc:
        logger.error("[proxy-admin] error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error conectando backend interno (admin): {exc}") from exc


@app.api_route("/api/{rest_of_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_api(rest_of_path: str, request: Request) -> Response:
    target_url = f"{BACKEND_BASE_URL}/api/{rest_of_path}"
    if ELECTRON_AUTH_DEBUG:
        logger.warning("[proxy-api] method=%s path=%s target=%s", request.method, rest_of_path, target_url)
    try:
        return await _proxy_request(request, target_url=target_url)
    except Exception as exc:
        logger.error("[proxy-api] error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error conectando backend interno: {exc}") from exc


@app.api_route("/{rest_of_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_frontend(rest_of_path: str, request: Request) -> Response:
    if not _frontend_process or _frontend_process.returncode is not None:
        await _start_frontend_server()
    target_url = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/{rest_of_path}"
    try:
        return await _proxy_request(request, target_url=target_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error conectando frontend: {exc}") from exc
