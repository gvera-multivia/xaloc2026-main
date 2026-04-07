from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Optional

import aiohttp
from fastapi import APIRouter, Body, Depends, HTTPException, Header, Query, Response

import dashboard_api as api
from core.authorization_fetcher import find_authorization_in_tmp, move_authorization_to_destinations
from core.client_documentation import client_identity_from_db
from core.client_paths import get_ruta_cliente_documentacion, resolve_client_docs_base_path
from core.gesdoc_auth import close_gesdoc_session, create_gesdoc_session, execute_gesdoc_action, search_client_in_gesdoc
from core.sqlserver_utils import build_sqlserver_connection_string
from core.xvia_auth import create_authenticated_session_in_place
from core.xvia_deselect import deselect_resource
from dashboard.services import DashboardConflictError, DashboardNotFoundError

router = APIRouter()
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _build_novnc_proxy_url() -> str:
    quality = (os.getenv("XALOC_NOVNC_QUALITY") or "9").strip() or "9"
    compression = (os.getenv("XALOC_NOVNC_COMPRESSION") or "0").strip() or "0"
    return (
        "/vnc/vnc.html"
        f"?autoconnect=1&quality={quality}&compression={compression}&resize=scale&path=websockify"
    )


def _compact_text_snippet(html: str, *, max_len: int = 1200) -> str:
    text = _HTML_TAG_RE.sub(" ", html or "")
    text = " ".join(text.split()).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _resolve_gesdoc_credentials(
    gesdoc_user: str | None,
    gesdoc_password: str | None,
) -> tuple[str, str]:
    username = str(gesdoc_user or os.getenv("GESDOC_USER") or "").strip()
    password = str(gesdoc_password or os.getenv("GESDOC_PWD") or "").strip()
    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail="Credenciales GESDOC no disponibles. Usa cabeceras X-Gesdoc-User/X-Gesdoc-Password o variables GESDOC_USER/GESDOC_PWD.",
        )
    return username, password


async def _open_gesdoc_session_from_headers(
    gesdoc_user: str | None,
    gesdoc_password: str | None,
):
    username, password = _resolve_gesdoc_credentials(gesdoc_user, gesdoc_password)
    return await create_gesdoc_session(username, password)


def _build_proxy_response(action_result: dict[str, Any]) -> Response:
    headers: dict[str, str] = {"X-Gesdoc-Final-Url": str(action_result.get("final_url") or "")}
    content_disposition = str(action_result.get("content_disposition") or "").strip()
    if content_disposition:
        headers["Content-Disposition"] = content_disposition
    return Response(
        content=action_result.get("body") or b"",
        status_code=int(action_result.get("status_code") or 200),
        media_type=str(action_result.get("content_type") or "application/octet-stream"),
        headers=headers,
    )


def _normalize_int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except Exception:
        return None


def _cliente_tipo_label(cliente_tipo: Any) -> str:
    return "empresa" if _normalize_int(cliente_tipo) == 2 else "particular"


def _gesdoc_generate_action_key(cliente_tipo: Any) -> str:
    return "generate_company" if _normalize_int(cliente_tipo) == 2 else "generate_particular"


def _build_gesdoc_available_actions(search_result: dict[str, Any]) -> list[str]:
    if bool(search_result.get("has_sent_request")):
        return ["generate"]
    return ["generate", "send"]


def _resolve_gesdoc_destination_folders(
    *,
    numclient: int,
    conn_str: str,
    sujeto_recurso: str | None = None,
) -> tuple[Path, list[Path]]:
    client = client_identity_from_db(numclient, conn_str, sujeto_recurso=sujeto_recurso)
    client_root = get_ruta_cliente_documentacion(client, base_path=resolve_client_docs_base_path())
    dest_folders: list[Path] = []
    if client_root.exists():
        for sub in client_root.iterdir():
            if sub.is_dir() and "DOCUMENTA" in sub.name.upper():
                dest_folders.append(sub)
    if not dest_folders:
        dest_folders = [
            client_root / "DOCUMENTACION",
            client_root / "DOCUMENTACION RECURSOS",
        ]
    return client_root, dest_folders


async def _poll_and_store_gesdoc_authorization(
    *,
    numclient: int,
    cliente_tipo: Any,
    conn_str: str,
    sujeto_recurso: str | None = None,
    max_polling_retries: int = 5,
    polling_interval: float = 2.0,
) -> dict[str, Any]:
    client_type = _cliente_tipo_label(cliente_tipo)
    try:
        client_root, dest_folders = _resolve_gesdoc_destination_folders(
            numclient=numclient,
            conn_str=conn_str,
            sujeto_recurso=sujeto_recurso,
        )
    except Exception as exc:
        return {
            "ok": False,
            "authorization_found": False,
            "authorization_file": None,
            "destination_paths": [],
            "message": f"No se pudo resolver la carpeta de documentación del cliente: {exc}",
        }

    auth_file = find_authorization_in_tmp(numclient, client_type)
    if auth_file is None:
        for _ in range(max_polling_retries):
            await asyncio.sleep(polling_interval)
            auth_file = find_authorization_in_tmp(numclient, client_type)
            if auth_file is not None:
                break

    destination_paths = [str(path) for path in dest_folders]
    if auth_file is None:
        return {
            "ok": False,
            "authorization_found": False,
            "authorization_file": None,
            "destination_paths": destination_paths,
            "client_folder_path": str(client_root),
            "message": "GESDOC respondió, pero no apareció ningún PDF de autorización en la carpeta temporal.",
        }

    copied = move_authorization_to_destinations(auth_file, dest_folders)
    return {
        "ok": bool(copied),
        "authorization_found": True,
        "authorization_file": str(auth_file),
        "destination_paths": destination_paths,
        "client_folder_path": str(client_root),
        "message": (
            "Autorización copiada a la documentación del cliente."
            if copied
            else "Se encontró la autorización en GESDOC, pero no se pudo copiar al destino."
        ),
    }


async def _run_gesdoc_client_action(
    *,
    cliente: int,
    action_key: str,
    gesdoc_user: str | None,
    gesdoc_password: str | None,
) -> Response:
    session = await _open_gesdoc_session_from_headers(gesdoc_user, gesdoc_password)
    try:
        search_result = await search_client_in_gesdoc(session, cliente)
        action_links = dict(search_result.get("action_links") or {})
        action_url = str(action_links.get(action_key) or "").strip()
        if not action_url:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró el enlace GESDOC para la acción '{action_key}' del cliente {cliente}.",
            )
        action_result = await execute_gesdoc_action(session, action_url)
        return _build_proxy_response(action_result)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except aiohttp.ClientError as exc:
        raise HTTPException(status_code=502, detail=f"Error llamando a GESDOC: {exc}") from exc
    finally:
        await close_gesdoc_session(session)


@router.get("/api/gesdoc/client-search")
async def api_gesdoc_client_search(
    cliente: int = Query(..., ge=1),
    include_html: bool = Query(False),
    gesdoc_user: str | None = Header(default=None, alias="X-Gesdoc-User"),
    gesdoc_password: str | None = Header(default=None, alias="X-Gesdoc-Password"),
    _user: dict = Depends(api.require_user),
) -> dict[str, Any]:
    session = await _open_gesdoc_session_from_headers(gesdoc_user, gesdoc_password)
    try:
        result = await search_client_in_gesdoc(session, cliente)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except aiohttp.ClientError as exc:
        raise HTTPException(status_code=502, detail=f"Error llamando a GESDOC: {exc}") from exc
    finally:
        await close_gesdoc_session(session)

    html = str(result.get("html") or "")
    response_payload: dict[str, Any] = {
        "ok": True,
        "cliente": cliente,
        "status_code": int(result.get("status_code") or 0),
        "final_url": str(result.get("final_url") or ""),
        "logged_user": result.get("logged_user"),
        "has_client_number": bool(result.get("has_client_number")),
        "has_sent_request": bool(result.get("has_sent_request")),
        "sent_request_entries": list(result.get("sent_request_entries") or []),
        "html_snippet": _compact_text_snippet(html),
    }
    if include_html:
        response_payload["html"] = html
    return response_payload


@router.get("/api/gesdoc/client-send-authorization")
async def api_gesdoc_client_send_authorization(
    cliente: int = Query(..., ge=1),
    confirm: bool = Query(False),
    gesdoc_user: str | None = Header(default=None, alias="X-Gesdoc-User"),
    gesdoc_password: str | None = Header(default=None, alias="X-Gesdoc-Password"),
    _user: dict = Depends(api.require_user),
) -> Response:
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Esta acción puede enviar una solicitud real. Repite con confirm=true para ejecutarla.",
        )
    return await _run_gesdoc_client_action(
        cliente=cliente,
        action_key="send",
        gesdoc_user=gesdoc_user,
        gesdoc_password=gesdoc_password,
    )


@router.get("/api/gesdoc/client-generate-company-authorization")
async def api_gesdoc_client_generate_company_authorization(
    cliente: int = Query(..., ge=1),
    gesdoc_user: str | None = Header(default=None, alias="X-Gesdoc-User"),
    gesdoc_password: str | None = Header(default=None, alias="X-Gesdoc-Password"),
    _user: dict = Depends(api.require_user),
) -> Response:
    return await _run_gesdoc_client_action(
        cliente=cliente,
        action_key="generate_company",
        gesdoc_user=gesdoc_user,
        gesdoc_password=gesdoc_password,
    )


@router.get("/api/gesdoc/client-generate-particular-authorization")
async def api_gesdoc_client_generate_particular_authorization(
    cliente: int = Query(..., ge=1),
    gesdoc_user: str | None = Header(default=None, alias="X-Gesdoc-User"),
    gesdoc_password: str | None = Header(default=None, alias="X-Gesdoc-Password"),
    _user: dict = Depends(api.require_user),
) -> Response:
    return await _run_gesdoc_client_action(
        cliente=cliente,
        action_key="generate_particular",
        gesdoc_user=gesdoc_user,
        gesdoc_password=gesdoc_password,
    )


@router.get("/api/incidents/{site_id}/{resource_id}/gesdoc-status")
async def api_incident_gesdoc_status(
    site_id: str,
    resource_id: int,
    gesdoc_user: str | None = Header(default=None, alias="X-Gesdoc-User"),
    gesdoc_password: str | None = Header(default=None, alias="X-Gesdoc-Password"),
    user: dict = Depends(api.require_user),
) -> dict[str, Any]:
    try:
        incident = api.service.get_pending_gesdoc_incident(
            site_id=site_id,
            resource_id=resource_id,
            user=user,
            require_lock_owner=True,
        )
    except DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DashboardConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    numclient = _normalize_int(incident.get("numclient"))
    if numclient is None:
        raise HTTPException(status_code=400, detail="La incidencia no tiene numclient resoluble.")

    session = await _open_gesdoc_session_from_headers(gesdoc_user, gesdoc_password)
    try:
        search_result = await search_client_in_gesdoc(session, numclient)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except aiohttp.ClientError as exc:
        raise HTTPException(status_code=502, detail=f"Error llamando a GESDOC: {exc}") from exc
    finally:
        await close_gesdoc_session(session)

    return {
        "ok": True,
        "site_id": site_id,
        "resource_id": resource_id,
        "incident_id": incident.get("incident_id"),
        "numclient": numclient,
        "cliente_tipo": _normalize_int(incident.get("cliente_tipo")),
        "client_folder_exists": bool(incident.get("client_folder_exists")),
        "client_folder_path": incident.get("client_folder_path"),
        "has_sent_request": bool(search_result.get("has_sent_request")),
        "sent_request_entries": list(search_result.get("sent_request_entries") or []),
        "available_actions": _build_gesdoc_available_actions(search_result),
        "locked_required": True,
    }


@router.post("/api/incidents/{site_id}/{resource_id}/gesdoc-action")
async def api_incident_gesdoc_action(
    site_id: str,
    resource_id: int,
    body: dict[str, Any] = Body(...),
    gesdoc_user: str | None = Header(default=None, alias="X-Gesdoc-User"),
    gesdoc_password: str | None = Header(default=None, alias="X-Gesdoc-Password"),
    user: dict = Depends(api.require_user),
) -> dict[str, Any]:
    action = str((body or {}).get("action") or "").strip().lower()
    if action not in {"generate", "send"}:
        raise HTTPException(status_code=400, detail="action debe ser 'generate' o 'send'.")

    try:
        incident = api.service.get_pending_gesdoc_incident(
            site_id=site_id,
            resource_id=resource_id,
            user=user,
            require_lock_owner=True,
        )
    except DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DashboardConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    numclient = _normalize_int(incident.get("numclient"))
    if numclient is None:
        raise HTTPException(status_code=400, detail="La incidencia no tiene numclient resoluble.")
    cliente_tipo = _normalize_int(incident.get("cliente_tipo"))
    if not bool(incident.get("client_folder_exists")):
        raise HTTPException(status_code=409, detail="La carpeta de documentación del cliente no existe.")

    conn_str = getattr(api.service, "sqlserver_conn_str", "") or ""
    if not conn_str:
        try:
            conn_str = build_sqlserver_connection_string()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"No se pudo resolver SQL Server: {exc}") from exc

    session = await _open_gesdoc_session_from_headers(gesdoc_user, gesdoc_password)
    try:
        search_result = await search_client_in_gesdoc(session, numclient)
        action_links = dict(search_result.get("action_links") or {})
        action_key = "send" if action == "send" else _gesdoc_generate_action_key(cliente_tipo)
        action_url = str(action_links.get(action_key) or "").strip()
        if not action_url:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró el enlace GESDOC para la acción '{action}' del cliente {numclient}.",
            )
        await execute_gesdoc_action(session, action_url)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except aiohttp.ClientError as exc:
        raise HTTPException(status_code=502, detail=f"Error llamando a GESDOC: {exc}") from exc
    finally:
        await close_gesdoc_session(session)

    move_result = await _poll_and_store_gesdoc_authorization(
        numclient=numclient,
        cliente_tipo=cliente_tipo,
        conn_str=conn_str,
        sujeto_recurso=str((incident.get("payload") or {}).get("sujeto_recurso") or (incident.get("payload") or {}).get("SujetoRecurso") or "").strip() or None,
    )
    return {
        "ok": bool(move_result.get("ok")),
        "action": action,
        "cliente_tipo": cliente_tipo,
        "authorization_found": bool(move_result.get("authorization_found")),
        "authorization_file": move_result.get("authorization_file"),
        "destination_paths": list(move_result.get("destination_paths") or []),
        "message": str(move_result.get("message") or ""),
    }


@router.post("/api/incidents/{id:path}/claim")
async def api_claim_incident(id: str, user: dict = Depends(api.require_user)):
    user_id = str(user.get("sub", "unknown"))
    username = user.get("username", "Unknown")
    try:
        lock_result = api.service.runtime_store.acquire_incident_lock(
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


@router.post("/api/incidents/{id:path}/release")
async def api_release_incident(id: str, user: dict = Depends(api.require_user)):
    user_id = str(user.get("sub", "unknown"))
    role = user.get("role", "user")
    release_result = api.service.runtime_store.release_incident_lock(
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


@router.delete("/api/incidents/{site_id}/{resource_id}")
async def api_resolve_incident(
    site_id: str,
    resource_id: int,
    incident_type: str | None = Query(None),
    _user: dict = Depends(api.require_user),
) -> dict:
    deleted = api.service.runtime_store.clear_incident(
        site_id=site_id,
        resource_id=resource_id,
        incident_type=incident_type or None,
    )
    return {"status": "resolved", "site_id": site_id, "resource_id": resource_id, "deleted": deleted}


@router.delete("/api/incidents/bulk")
async def api_resolve_incidents_bulk(
    site_id: str = Query(...),
    incident_type: str = Query(...),
    _user: dict = Depends(api.require_user),
) -> dict:
    deleted = api.service.runtime_store.clear_incidents_bulk(
        site_id=site_id,
        incident_type=incident_type,
    )
    return {"status": "resolved", "site_id": site_id, "incident_type": incident_type, "deleted": deleted}


@router.get("/api/history/days")
async def api_history_days(
    source: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: dict = Depends(api.require_user),
) -> dict:
    return api.service.list_history_days(source=source, page=page, page_size=page_size, user=user)


@router.get("/api/history/incidents")
async def api_history_incidents(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(api.require_user),
) -> dict:
    return api.service.list_history_incidents(day=day, page=page, page_size=page_size)


@router.get("/api/incidents")
async def api_incidents_pending(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(api.require_user),
) -> dict:
    result = api.service.list_pending_incidents(page=page, page_size=page_size)
    items = list(result.get("items") or [])

    def _incident_row_id(item: dict[str, Any], rid: Optional[int]) -> str:
        site = str(item.get("site_id") or "").strip()
        rid_part = str(rid) if rid is not None else "none"
        incident_type = str(item.get("incident_type") or "").strip().upper() or "UNKNOWN"
        expediente = str(item.get("expediente") or "").strip().upper() or "none"
        return f"{site}:{rid_part}:{incident_type}:{expediente}"

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
    legacy_incident_ids = []
    for it in items:
        rid = _resolve_incident_resource(it)
        it["resource_id"] = rid
        incident_id = _incident_row_id(it, rid)
        legacy_id = f"{it.get('site_id')}:{rid if rid is not None else 'none'}"
        it["incident_id"] = incident_id
        incident_ids.append(incident_id)
        legacy_incident_ids.append(legacy_id)

    locks = api.service.runtime_store.get_incident_locks(
        incident_ids=list(dict.fromkeys(incident_ids + legacy_incident_ids))
    )
    for item in items:
        rid = item.get("resource_id")
        incident_id = str(item.get("incident_id") or "")
        legacy_id = f"{item.get('site_id')}:{rid if rid is not None else 'none'}"
        lock_info = locks.get(incident_id) or locks.get(legacy_id)
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


@router.get("/api/history/successes")
async def api_history_successes(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    user: dict = Depends(api.require_user),
) -> dict:
    return api.service.list_history_successes(day=day, page=page, page_size=page_size, user=user)


@router.get("/api/history/top-users")
async def api_history_top_users(
    limit: int = Query(500, ge=1, le=5000),
    day: str | None = Query(None),
    user: dict = Depends(api.require_user),
) -> dict:
    return api.service.list_history_top_users(limit=limit, day=day, user=user)


@router.get("/api/history/postgres-details")
async def api_history_postgres_details(
    site_id: str = Query(..., min_length=1),
    resource_id: int = Query(...),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(api.require_user),
) -> dict:
    return api.service.get_history_postgres_details(
        site_id=site_id,
        resource_id=resource_id,
        limit=limit,
    )


@router.get("/api/queue/days")
async def api_queue_days(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    _user: dict = Depends(api.require_user),
) -> dict:
    return api.service.list_queue_days(page=page, page_size=page_size)


@router.get("/api/queue/current")
async def api_queue_current(
    day: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(api.require_user),
) -> dict:
    return api.service.list_queue_current(day=day, page=page, page_size=page_size)


@router.get("/api/queue/live")
async def api_queue_live(
    day: str | None = Query(None),
    _user: dict = Depends(api.require_user),
) -> dict:
    item = api.service.get_queue_live(day=day)
    if not item:
        return {"item": None}
    return {"item": item}


@router.get("/api/queue/completion-marker")
async def api_queue_completion_marker(
    day: str | None = Query(None),
    _user: dict = Depends(api.require_user),
) -> dict:
    return api.service.get_queue_completion_marker(day=day)


@router.get("/api/queue/live-viewer")
async def api_queue_live_viewer(
    day: str | None = Query(None),
    _user: dict = Depends(api.require_user),
) -> dict:
    # noVNC contract expected by dashboard-frontend/components/monitor/LiveScreencast.tsx
    novnc_url = _build_novnc_proxy_url()
    enabled = True

    day_value = (day or "").strip() or None
    snapshot = api.service.get_queue_live(day=day_value)
    marker = api.service.get_queue_completion_marker(day=day_value)
    payload: dict[str, Any] = {
        "enabled": enabled,
        "novnc_url": novnc_url if enabled else None,
        "day": marker.get("day") or day_value,
        "is_complete": bool(marker.get("is_complete")),
        "completed_at": marker.get("completed_at"),
        "source": marker.get("source") or "redis",
        "item": snapshot,
    }
    if not snapshot:
        payload["status"] = "idle"
        payload["message"] = "No hay recurso en procesamiento ahora mismo."
        return payload

    payload["status"] = "processing"
    payload["message"] = "Procesando recurso en tiempo real."
    return payload


@router.get("/api/control/status")
async def api_control_status(_admin: dict = Depends(api.require_admin)):
    status_map = {
        "worker": api.process_manager.get_status("worker"),
        "brain": api.process_manager.get_status("brain"),
        "frontend": (
            "running"
            if api._frontend_process and api._frontend_process.returncode is None
            else "stopped"
        ),
    }
    return {"status": status_map, **status_map}


@router.post("/api/control/{process_name}/start")
async def api_start_process(process_name: str, _admin: dict = Depends(api.require_admin)):
    pname = process_name.lower()
    if pname not in api.CONTROL_PROCESS_NAMES and pname != "frontend":
        raise HTTPException(status_code=400, detail=f"Proceso desconocido: {process_name}")

    if pname == "frontend":
        await api._start_frontend_server()
        return {
            "status": api.process_manager.get_status("frontend"),
            "message": "Frontend iniciado",
            "process_name": "frontend",
        }

    result = await api.process_manager.start_process(pname)
    return {
        "status": api.process_manager.get_status(pname),
        "message": result,
        "process_name": pname,
    }


@router.post("/api/control/{process_name}/stop")
async def api_stop_process(process_name: str, _admin: dict = Depends(api.require_admin)):
    pname = process_name.lower()
    if pname not in api.CONTROL_PROCESS_NAMES and pname != "frontend":
        raise HTTPException(status_code=400, detail=f"Proceso desconocido: {process_name}")

    if pname == "frontend":
        await api._stop_frontend_server()
        return {
            "status": "stopped",
            "message": "Frontend detenido",
            "process_name": "frontend",
        }

    result = await api.process_manager.stop_process(pname)
    return {
        "status": api.process_manager.get_status(pname),
        "message": result,
        "process_name": pname,
    }


@router.post("/api/control/{process_name}/restart")
async def api_restart_process(process_name: str, _admin: dict = Depends(api.require_admin)):
    pname = process_name.lower()
    if pname not in api.CONTROL_PROCESS_NAMES and pname != "frontend":
        raise HTTPException(status_code=400, detail=f"Proceso desconocido: {process_name}")

    if pname == "frontend":
        await api._stop_frontend_server()
        await api._start_frontend_server()
        return {
            "status": api.process_manager.get_status("frontend"),
            "message": "Frontend reiniciado",
            "process_name": "frontend",
        }

    result = await api.process_manager.restart_process(pname)
    return {
        "status": api.process_manager.get_status(pname),
        "message": result,
        "process_name": pname,
    }


@router.get("/api/logs/{process_name}")
async def api_get_logs(
    process_name: str,
    lines: int = Query(100, ge=1, le=2000),
    _admin: dict = Depends(api.require_admin),
):
    pname = process_name.lower()
    if pname not in api.CONTROL_PROCESS_NAMES and pname not in {"frontend", "playwright_runner"}:
        raise HTTPException(status_code=400, detail=f"Proceso desconocido: {process_name}")

    safe_lines = min(max(int(lines), 1), 2000)
    if pname == "frontend":
        status = "stopped"
        if api._frontend_process and api._frontend_process.returncode is None:
            status = "running"
        elif api._frontend_process and api._frontend_process.returncode not in (0, None):
            status = "error"
        return {
            "name": "frontend",
            "status": status,
            "lines": safe_lines,
            "stdout": api._tail_text_file(api._FRONTEND_LOG_PATH, safe_lines),
            "stderr": [],
        }
    if pname == "worker":
        return {
            "name": "worker",
            "status": api.process_manager.get_status("worker"),
            "lines": safe_lines,
            "stdout": api._merge_tail_text_files([Path("logs") / "worker_out.log", api._RUNNER_LOG_PATH], safe_lines),
            "stderr": [],
        }
    try:
        return api.process_manager.get_logs(pname, lines=safe_lines)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/queue/pauses")
async def api_queue_pauses(
    active_only: bool = Query(True),
    _admin: dict = Depends(api.require_admin),
) -> dict:
    items = api.service.list_processing_pauses(active_only=active_only)
    return {"items": items, "total": len(items)}


@router.post("/api/queue/pauses/{site_id}")
async def api_pause_site_processing(
    site_id: str,
    minutes: int | None = Query(None, ge=1),
    reason: str | None = Query(None),
    _admin: dict = Depends(api.require_admin),
) -> dict:
    try:
        return api.service.pause_site_processing(site_id=site_id, reason=reason, minutes=minutes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/queue/pauses/{site_id}")
async def api_unpause_site_processing(site_id: str, _admin: dict = Depends(api.require_admin)) -> dict:
    try:
        return api.service.unpause_site_processing(site_id=site_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/queue/item-pauses")
async def api_queue_item_pauses(
    active_only: bool = Query(True),
    _admin: dict = Depends(api.require_admin),
) -> dict:
    items = api.service.list_item_processing_pauses(active_only=active_only)
    return {"items": items, "total": len(items)}


@router.post("/api/queue/items/{site_id}/{resource_id}/pause")
async def api_pause_queue_item(
    site_id: str,
    resource_id: int,
    minutes: int | None = Query(None, ge=1),
    reason: str | None = Query(None),
    _admin: dict = Depends(api.require_admin),
) -> dict:
    try:
        return api.service.pause_queue_item_processing(
            site_id=site_id,
            resource_id=resource_id,
            reason=reason,
            minutes=minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/queue/items/{site_id}/{resource_id}/pause")
async def api_unpause_queue_item(site_id: str, resource_id: int, _admin: dict = Depends(api.require_admin)) -> dict:
    try:
        return api.service.unpause_queue_item_processing(site_id=site_id, resource_id=resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/queue/items/{site_id}/{resource_id}")
async def api_delete_queue_item(site_id: str, resource_id: int, _admin: dict = Depends(api.require_admin)) -> dict:
    try:
        result = api.service.remove_queue_item(site_id=site_id, resource_id=resource_id)
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


@router.post("/api/queue/items/{site_id}/{resource_id}/recover")
async def api_recover_queue_item(
    site_id: str,
    resource_id: int,
    heartbeat_timeout_seconds: int | None = Query(None, ge=1),
    _user: dict = Depends(api.require_user),
) -> dict:
    try:
        return api.service.recover_queue_item_processing(
            site_id=site_id,
            resource_id=resource_id,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/queue/recover-stuck")
async def api_recover_stuck_queue_items(
    heartbeat_timeout_seconds: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=2000),
    site_id: str | None = Query(None),
    resource_id: int | None = Query(None),
    _admin: dict = Depends(api.require_admin),
) -> dict:
    try:
        return api.service.recover_stuck_queue_items(
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            limit=limit,
            site_id=site_id,
            resource_id=resource_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
