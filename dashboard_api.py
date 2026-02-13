from __future__ import annotations

import asyncio
import os
from typing import Any
from pathlib import Path

import aiohttp
from fastapi import FastAPI, Query, HTTPException, Body, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from dashboard import DashboardService
from dashboard.process_manager import ProcessManager
from core.xvia_auth import create_authenticated_session_in_place
from core.xvia_deselect import deselect_resource

app = FastAPI(title="Xaloc Realtime Dashboard", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = DashboardService()
process_manager = ProcessManager(base_dir=".", logs_dir="logs")

FRONTEND_HOST = os.getenv("DASHBOARD_FRONTEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
FRONTEND_PORT = int((os.getenv("DASHBOARD_FRONTEND_PORT") or "3000").strip() or "3000")
FRONTEND_DEV = (os.getenv("DASHBOARD_FRONTEND_DEV") or "1").strip().lower() not in {"0", "false", "no", "off"}

_frontend_process: asyncio.subprocess.Process | None = None
_proxy_session: aiohttp.ClientSession | None = None


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

    mode = "dev" if FRONTEND_DEV else "start"
    cmd = ["cmd", "/c", "npm", "run", mode, "--", "--hostname", FRONTEND_HOST, "--port", str(FRONTEND_PORT)]
    _frontend_process = await asyncio.create_subprocess_exec(
        *cmd,
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
    _proxy_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _proxy_session


async def _stop_frontend_server() -> None:
    global _frontend_process
    proc = _frontend_process
    if not proc:
        return
    if proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=8)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    _frontend_process = None


@app.on_event("startup")
async def app_startup() -> None:
    await _start_frontend_server()


@app.on_event("shutdown")
async def app_shutdown() -> None:
    global _proxy_session
    await process_manager.stop_all()
    if _proxy_session is not None and not _proxy_session.closed:
        await _proxy_session.close()
    _proxy_session = None
    await _stop_frontend_server()


@app.get("/api/history/days")
async def api_history_days(
    source: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> dict:
    return service.list_history_days(source=source, page=page, page_size=page_size)


@app.get("/api/history/incidents")
async def api_history_incidents(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return service.list_history_incidents(day=day, page=page, page_size=page_size)


@app.get("/api/history/successes")
async def api_history_successes(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return service.list_history_successes(day=day, page=page, page_size=page_size)


@app.get("/api/queue/days")
async def api_queue_days(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> dict:
    return service.list_queue_days(page=page, page_size=page_size)


@app.get("/api/queue/current")
async def api_queue_current(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
) -> dict:
    return service.list_queue_current(day=day, page=page, page_size=page_size)


@app.get("/api/queue/live")
async def api_queue_live(
    day: str | None = Query(None),
) -> dict:
    item = service.get_queue_live(day=day)
    if not item:
        raise HTTPException(status_code=404, detail="No active tramite")
    return item


@app.get("/api/queue/completion-marker")
async def api_queue_completion_marker(
    day: str | None = Query(None),
) -> dict:
    return service.get_queue_completion_marker(day=day)


from pathlib import Path as _Path

_LIVE_FRAME_PATH = _Path(__file__).parent.absolute() / "screenshots" / "live_frame.jpg"


@app.get("/api/queue/live-screenshot")
async def api_queue_live_screenshot():
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
async def api_control_status() -> dict:
    return process_manager.get_all_status()


@app.post("/api/control/{process_name}/start")
async def api_control_start(process_name: str) -> dict:
    try:
        return await process_manager.start_process(process_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/control/{process_name}/stop")
async def api_control_stop(process_name: str) -> dict:
    try:
        return await process_manager.stop_process(process_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/control/{process_name}/restart")
async def api_control_restart(process_name: str) -> dict:
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
) -> dict:
    try:
        return process_manager.get_logs(process_name, lines=lines)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/queue/pauses")
async def api_queue_pauses(
    active_only: bool = Query(True),
) -> dict:
    items = service.list_processing_pauses(active_only=active_only)
    return {"items": items, "total": len(items)}


@app.post("/api/queue/pauses/{site_id}")
async def api_pause_site_processing(
    site_id: str,
    minutes: int | None = Query(None, ge=1),
    reason: str | None = Query(None),
) -> dict:
    try:
        return service.pause_site_processing(site_id=site_id, reason=reason, minutes=minutes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/queue/pauses/{site_id}")
async def api_unpause_site_processing(site_id: str) -> dict:
    try:
        return service.unpause_site_processing(site_id=site_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/queue/item-pauses")
async def api_queue_item_pauses(
    active_only: bool = Query(True),
) -> dict:
    items = service.list_item_processing_pauses(active_only=active_only)
    return {"items": items, "total": len(items)}


@app.post("/api/queue/items/{site_id}/{resource_id}/pause")
async def api_pause_queue_item(
    site_id: str,
    resource_id: int,
    minutes: int | None = Query(None, ge=1),
    reason: str | None = Query(None),
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
async def api_unpause_queue_item(site_id: str, resource_id: int) -> dict:
    try:
        return service.unpause_queue_item_processing(site_id=site_id, resource_id=resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/queue/items/{site_id}/{resource_id}")
async def api_delete_queue_item(site_id: str, resource_id: int) -> dict:
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
async def api_blacklist(site_id: str | None = Query(None)) -> dict:
    items = service.list_blacklist(site_id=site_id)
    return {"items": items, "total": len(items)}


@app.post("/api/blacklist")
async def api_blacklist_block(payload: dict[str, Any] = Body(...)) -> dict:
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
async def api_blacklist_unblock(site_id: str, resource_id: int) -> dict:
    try:
        return service.unblock_blacklist(site_id=site_id, resource_id=resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/config")
async def api_config_list() -> dict:
    items = service.list_organismo_configs()
    return {"items": items, "total": len(items)}


@app.put("/api/config/{site_id}")
async def api_config_update(site_id: str, payload: dict[str, Any] = Body(...)) -> dict:
    try:
        updates = dict(payload or {})
        return service.update_organismo_config(site_id=site_id, updates=updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ==========================================================================
# PENDING AUTHORIZATION QUEUE
# ==========================================================================


@app.get("/api/pending-auth")
async def api_pending_auth_list(
    authorization_type: str | None = Query(None),
) -> dict:
    return service.list_pending_authorizations(authorization_type=authorization_type)


@app.post("/api/pending-auth/{pending_id}/approve")
async def api_pending_auth_approve(pending_id: int) -> dict:
    try:
        return service.approve_pending_authorization(pending_id=pending_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/pending-auth/{pending_id}/reject")
async def api_pending_auth_reject(
    pending_id: int,
    payload: dict[str, Any] = Body(...),
) -> dict:
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Se requiere un motivo de rechazo.")
    try:
        return service.reject_pending_authorization(
            pending_id=pending_id,
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ==========================================================================
# CLIENT FOLDER (open in Explorer)
# ==========================================================================


@app.post("/api/client-folder")
async def api_client_folder(payload: dict[str, Any] = Body(...)) -> dict:
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

    if not _frontend_process or _frontend_process.returncode is not None:
        await _start_frontend_server()

    target_url = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/{rest_of_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS and key.lower() != "host"
    }

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
