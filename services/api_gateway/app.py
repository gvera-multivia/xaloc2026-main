from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
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
PLAYWRIGHT_NOVNC_BASE_URL = (
    os.getenv("PLAYWRIGHT_NOVNC_BASE_URL") or "http://playwright-runner-service:6080"
).strip().rstrip("/")
ELECTRON_AUTH_DEBUG = (os.getenv("ELECTRON_AUTH_DEBUG") or "1").strip().lower() in {"1", "true", "yes", "on"}
_frontend_process: asyncio.subprocess.Process | None = None
_proxy_session: aiohttp.ClientSession | None = None

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


def _jwt_exp_unverified(token: str | None) -> int | None:
    if not token:
        return None
    parts = str(token).split(".")
    if len(parts) < 2:
        return None
    payload_raw = parts[1]
    payload_raw += "=" * ((4 - len(payload_raw) % 4) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_raw.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    exp = payload.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def _choose_fresh_ws_token(*tokens: str | None) -> str | None:
    now = int(time.time())
    for token in tokens:
        if not token:
            continue
        exp = _jwt_exp_unverified(token)
        if exp is None or exp > now:
            return token
    return None


def _copy_auth_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    authorization = request.headers.get("authorization")
    cookie = request.headers.get("cookie")
    if authorization:
        headers["Authorization"] = authorization
    if cookie:
        headers["Cookie"] = cookie
    return headers


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


def _playwright_ws_url(path: str, query: str = "") -> str:
    if PLAYWRIGHT_NOVNC_BASE_URL.startswith("https://"):
        base = "wss://" + PLAYWRIGHT_NOVNC_BASE_URL[len("https://"):] + path
    elif PLAYWRIGHT_NOVNC_BASE_URL.startswith("http://"):
        base = "ws://" + PLAYWRIGHT_NOVNC_BASE_URL[len("http://"):] + path
    else:
        base = PLAYWRIGHT_NOVNC_BASE_URL + path
    return f"{base}?{query}" if query else base


def _build_dashboard_ws_upstream_url(websocket: WebSocket) -> str:
    raw_query = str(websocket.url.query or "")
    params = parse_qsl(raw_query, keep_blank_values=True)
    filtered: list[tuple[str, str]] = [(k, v) for (k, v) in params if k.lower() != "token"]
    query_token = next((v for (k, v) in params if k.lower() == "token" and (v or "").strip()), "")
    header_token = (_extract_bearer_from_authorization(websocket.headers.get("authorization")) or "").strip()
    cookie_token = (websocket.cookies.get("dashboard_access_token") or "").strip()
    # Prefer a non-expired token among header/query/cookie. This avoids WS 403 loops
    # when one source (often cookie/query) is stale while another source is fresh.
    chosen_token = _choose_fresh_ws_token(header_token, query_token, cookie_token)
    if chosen_token:
        filtered.append(("token", chosen_token))
    upstream_query = urlencode(filtered, doseq=True)
    return _backend_ws_url("/ws/dashboard", upstream_query)


async def _proxy_websocket(
    websocket: WebSocket,
    upstream_url: str,
    *,
    include_auth_headers: bool = False,
    include_cookies: bool = True,
) -> None:
    headers: dict[str, str] = {}
    if websocket.headers.get("origin"):
        headers["Origin"] = str(websocket.headers.get("origin"))
    if include_auth_headers and websocket.headers.get("authorization"):
        headers["Authorization"] = str(websocket.headers.get("authorization"))
    if include_cookies and websocket.headers.get("cookie"):
        headers["Cookie"] = str(websocket.headers.get("cookie"))
    subprotocols_header = str(websocket.headers.get("sec-websocket-protocol") or "").strip()
    requested_subprotocols = [p.strip() for p in subprotocols_header.split(",") if p.strip()]

    session = await _ensure_proxy_session()
    try:
        ws_connect_kwargs: dict[str, Any] = {"headers": headers}
        if requested_subprotocols:
            ws_connect_kwargs["protocols"] = requested_subprotocols
        async with session.ws_connect(upstream_url, **ws_connect_kwargs) as upstream_ws:
            selected_subprotocol = getattr(upstream_ws, "protocol", None)
            if not selected_subprotocol and requested_subprotocols:
                selected_subprotocol = requested_subprotocols[0]
            await websocket.accept(subprotocol=selected_subprotocol)

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
@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.websocket("/ws/dashboard")
async def proxy_ws_dashboard(websocket: WebSocket) -> None:
    await _proxy_websocket(
        websocket,
        _build_dashboard_ws_upstream_url(websocket),
        include_auth_headers=True,
    )


@app.websocket("/_next/webpack-hmr")
async def proxy_ws_frontend_hmr(websocket: WebSocket) -> None:
    # Next.js dev HMR channel.
    query = str(websocket.url.query or "")
    await _proxy_websocket(
        websocket,
        _frontend_ws_url("/_next/webpack-hmr", query),
        include_auth_headers=False,
        include_cookies=False,
    )


@app.websocket("/websockify")
async def proxy_ws_novnc_websockify(websocket: WebSocket) -> None:
    query = str(websocket.url.query or "")
    logger.warning(
        "[proxy-ws-novnc] sec-websocket-protocol=%s origin=%s",
        websocket.headers.get("sec-websocket-protocol"),
        websocket.headers.get("origin"),
    )
    await _proxy_websocket(
        websocket,
        _playwright_ws_url("/websockify", query),
        include_auth_headers=False,
        include_cookies=False,
    )


@app.websocket("/vnc/websockify")
async def proxy_ws_novnc_websockify_under_vnc(websocket: WebSocket) -> None:
    # noVNC served from /vnc/vnc.html resolves its websocket path relative to /vnc/.
    # Mirror the proxy here so the public asset path and WS path stay aligned.
    query = str(websocket.url.query or "")
    await _proxy_websocket(
        websocket,
        _playwright_ws_url("/websockify", query),
        include_auth_headers=False,
        include_cookies=False,
    )


@app.websocket("/websockify/{rest_of_path:path}")
async def proxy_ws_novnc_websockify_path(websocket: WebSocket, rest_of_path: str) -> None:
    query = str(websocket.url.query or "")
    await _proxy_websocket(
        websocket,
        _playwright_ws_url(f"/websockify/{rest_of_path}", query),
        include_auth_headers=False,
        include_cookies=False,
    )


@app.websocket("/vnc/websockify/{rest_of_path:path}")
async def proxy_ws_novnc_websockify_under_vnc_path(websocket: WebSocket, rest_of_path: str) -> None:
    query = str(websocket.url.query or "")
    await _proxy_websocket(
        websocket,
        _playwright_ws_url(f"/websockify/{rest_of_path}", query),
        include_auth_headers=False,
        include_cookies=False,
    )


@app.api_route("/vnc/{rest_of_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_novnc_assets(rest_of_path: str, request: Request) -> Response:
    # The public URL uses "/vnc/..." prefix, but upstream noVNC serves assets from "/".
    target_url = f"{PLAYWRIGHT_NOVNC_BASE_URL}/{rest_of_path}"
    try:
        return await _proxy_request(request, target_url=target_url)
    except Exception as exc:
        logger.error("[proxy-novnc-assets] error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error conectando noVNC interno: {exc}") from exc


@app.api_route("/websockify", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_novnc_websockify(request: Request) -> Response:
    target_url = f"{PLAYWRIGHT_NOVNC_BASE_URL}/websockify"
    try:
        return await _proxy_request(request, target_url=target_url)
    except Exception as exc:
        logger.error("[proxy-novnc-websockify] error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error conectando websockify interno: {exc}") from exc


@app.api_route("/websockify/{rest_of_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_novnc_websockify_path(rest_of_path: str, request: Request) -> Response:
    target_url = f"{PLAYWRIGHT_NOVNC_BASE_URL}/websockify/{rest_of_path}"
    try:
        return await _proxy_request(request, target_url=target_url)
    except Exception as exc:
        logger.error("[proxy-novnc-websockify-path] error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error conectando websockify interno: {exc}") from exc


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
    normalized_path = (rest_of_path or "").strip("/")
    query = str(request.url.query or "")
    if normalized_path == "history/top":
        target_url = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/history"
        target_url = f"{target_url}?view=top&{query}" if query else f"{target_url}?view=top"
    else:
        target_url = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/{rest_of_path}"
    try:
        return await _proxy_request(request, target_url=target_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error conectando frontend: {exc}") from exc
