from __future__ import annotations

import os
from typing import Any

import aiohttp
from fastapi import FastAPI, Query, HTTPException, Body
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from dashboard import DashboardService
from dashboard.dashboard_restarter import DashboardRestarter
from dashboard.process_manager import ProcessManager
from dashboard.update_manager import UpdateManager
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
update_manager = UpdateManager(base_dir=".", service=service, process_manager=process_manager)
dashboard_restarter = DashboardRestarter(base_dir=".")

# Ensure frontend directory exists to avoid crash on StaticFiles mount
frontend_out = os.path.join("dashboard-frontend", "out")
if not os.path.exists(frontend_out):
    os.makedirs(frontend_out, exist_ok=True)
    index_placeholder = os.path.join(frontend_out, "index.html")
    if not os.path.exists(index_placeholder):
        with open(index_placeholder, "w", encoding="utf-8") as f:
            f.write("<html><body><h1>Dashboard is building...</h1><p>Please wait a few minutes and refresh.</p></body></html>")


# Static assets mounts (defined BEFORE catch-all, but can be here or at bottom)
app.mount("/_next", StaticFiles(directory="dashboard-frontend/out/_next"), name="next")
assets_path = os.path.join("dashboard-frontend", "out", "assets")
if os.path.exists(assets_path):
    app.mount("/assets", StaticFiles(directory="dashboard-frontend/out/assets"), name="assets")

@app.get("/favicon.ico")
async def favicon():
    fpath = os.path.join("dashboard-frontend", "out", "favicon.ico")
    if os.path.exists(fpath):
        return FileResponse(fpath)
    return Response(status_code=404)


@app.on_event("startup")
async def app_startup() -> None:
    # No se inicia worker/brain automaticamente; control explicito desde frontend.
    return None


@app.on_event("shutdown")
async def app_shutdown() -> None:
    await process_manager.stop_all()


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


@app.get("/api/control/update/status")
async def api_control_update_status() -> dict:
    return update_manager.status()


@app.get("/api/control/restart/status")
async def api_control_restart_status() -> dict:
    return dashboard_restarter.status()


@app.get("/api/control/update/check")
async def api_control_update_check() -> dict:
    try:
        return await update_manager.check_for_updates()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error comprobando actualizaciones: {exc}") from exc


@app.post("/api/control/update/run")
async def api_control_update_run(
    wait_timeout_seconds: int = Query(1800, ge=1, le=7200),
    poll_seconds: float = Query(2.0, ge=0.2, le=10.0),
) -> dict:
    try:
        return await update_manager.run_update(
            wait_timeout_seconds=wait_timeout_seconds,
            poll_seconds=poll_seconds,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc)) from exc
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 409 if "en curso" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error ejecutando actualizacion: {exc}") from exc


@app.post("/api/control/restart-dashboard")
async def api_control_restart_dashboard(
    delay_seconds: float = Query(1.0, ge=0.2, le=10.0),
) -> dict:
    try:
        return await dashboard_restarter.schedule_restart(delay_seconds=delay_seconds)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error programando reinicio: {exc}") from exc


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


# ==========================================================================
# CATCH-ALL FOR NEXT.JS SPA ROUTING
# ==========================================================================

# This handles /, /admin, /history, /control, etc. and returns index.html
# MUST be defined last so it doesn't shadow /api routes
@app.get("/{rest_of_path:path}")
@app.head("/{rest_of_path:path}")
async def catch_all(rest_of_path: str):
    # Skip if it starts with api/ (should have been caught above)
    if rest_of_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    # 1. Try to serve the exact file from out/ (e.g. scripts, images, pre-rendered .txt)
    file_path = os.path.join("dashboard-frontend", "out", rest_of_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)

    # 1.b Next static export may request "__next.<route>.__PAGE__.txt"
    # while files are emitted as "__next.<route>/__PAGE__.txt".
    if rest_of_path.endswith(".__PAGE__.txt"):
        base_part = rest_of_path[: -len(".__PAGE__.txt")]
        page_variant = os.path.join("dashboard-frontend", "out", base_part, "__PAGE__.txt")
        if os.path.isfile(page_variant):
            return FileResponse(page_variant)
    
    # 2. Try to serve as a pre-rendered HTML page (e.g. /admin -> /admin.html)
    html_path = file_path.rstrip("/") + ".html"
    if os.path.isfile(html_path):
        return FileResponse(html_path)

    # 3. Fallback to index.html for SPA client-side routing
    # ONLY if it doesn't look like a file (no extension)
    if "." not in rest_of_path:
        index_path = os.path.join("dashboard-frontend", "out", "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    
    raise HTTPException(status_code=404, detail="Not Found")
