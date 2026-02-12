from __future__ import annotations

import os
from typing import Any

import aiohttp
from fastapi import FastAPI, Query, HTTPException, Body
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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


@app.get("/")
async def home():
    return FileResponse("dashboard-frontend/index.html")

@app.get("/queues")
@app.get("/queues/")
@app.get("/admin")
@app.get("/admin/")
@app.get("/colas")
@app.get("/colas/")
async def queues():
    return FileResponse("dashboard-frontend/index.html")

@app.get("/history")
@app.get("/history/")
@app.get("/historico")
@app.get("/historico/")
@app.get("/control")
@app.get("/control/")
@app.get("/blacklist")
@app.get("/blacklist/")
async def history():
    return FileResponse("dashboard-frontend/index.html")


@app.get("/styles.css")
async def styles():
    return FileResponse("dashboard-frontend/styles.css")


# Mount the frontend directory for any other assets
app.mount("/dashboard", StaticFiles(directory="dashboard-frontend"), name="dashboard")


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

_LIVE_FRAME_PATH = _Path("screenshots/live_frame.jpg")


@app.get("/api/queue/live-screenshot")
async def api_queue_live_screenshot():
    """Devuelve el último frame JPEG del screencast CDP del worker."""
    if not _LIVE_FRAME_PATH.exists():
        raise HTTPException(status_code=404, detail="No hay frame en vivo")
    return FileResponse(
        _LIVE_FRAME_PATH,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
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
