from __future__ import annotations

import os

import aiohttp
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from dashboard import DashboardService
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
async def history():
    return FileResponse("dashboard-frontend/index.html")


@app.get("/styles.css")
async def styles():
    return FileResponse("dashboard-frontend/styles.css")


# Mount the frontend directory for any other assets
app.mount("/dashboard", StaticFiles(directory="dashboard-frontend"), name="dashboard")


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
    }
