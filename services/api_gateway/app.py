from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from core.process_launcher import get_npm_command, start_async_process, terminate_process_tree

load_dotenv()

app = FastAPI(title="api-gateway", version="0.1.0")

FRONTEND_HOST = (os.getenv("DASHBOARD_FRONTEND_HOST") or "127.0.0.1").strip() or "127.0.0.1"
FRONTEND_PORT = int((os.getenv("DASHBOARD_FRONTEND_PORT") or "3000").strip() or "3000")
FRONTEND_DEV = (os.getenv("DASHBOARD_FRONTEND_DEV") or "0").strip().lower() not in {"0", "false", "no", "off"}
BACKEND_BASE_URL = (os.getenv("DASHBOARD_BACKEND_URL") or "http://dashboard-backend-service:8788").strip().rstrip("/")

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
    _proxy_session = aiohttp.ClientSession(timeout=timeout, connector=connector, auto_decompress=False)
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
            if key.lower() not in _HOP_BY_HOP_HEADERS and key.lower() != "content-length"
        }
        return Response(content=content, status_code=upstream.status, headers=out_headers)


def _backend_ws_url(path: str) -> str:
    if BACKEND_BASE_URL.startswith("https://"):
        return "wss://" + BACKEND_BASE_URL[len("https://"):] + path
    if BACKEND_BASE_URL.startswith("http://"):
        return "ws://" + BACKEND_BASE_URL[len("http://"):] + path
    return BACKEND_BASE_URL + path


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


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.websocket("/ws/dashboard")
async def proxy_ws_dashboard(websocket: WebSocket) -> None:
    await _proxy_websocket(websocket, _backend_ws_url("/ws/dashboard"), include_auth_headers=True)


@app.websocket("/_next/webpack-hmr")
async def proxy_ws_frontend_hmr(websocket: WebSocket) -> None:
    # Next.js dev HMR channel.
    query = str(websocket.url.query or "")
    await _proxy_websocket(websocket, _frontend_ws_url("/_next/webpack-hmr", query), include_auth_headers=False)


@app.api_route("/api/{rest_of_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_api(rest_of_path: str, request: Request) -> Response:
    target_url = f"{BACKEND_BASE_URL}/api/{rest_of_path}"
    try:
        return await _proxy_request(request, target_url=target_url)
    except Exception as exc:
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
