from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Running as internal backend service: no frontend proxy here.
os.environ.setdefault("DASHBOARD_ENABLE_FRONTEND_PROXY", "0")
from fastapi import Body, Depends, HTTPException

from core.redis_client import get_redis_client
from dashboard_api import app, require_admin

__all__ = ["app"]

_ALLOWED_LEVELS = {"info", "warning", "critical"}
_DB_PATH = Path((os.getenv("DASHBOARD_TEMPLATES_DB") or "db/notification_templates.db").strip() or "db/notification_templates.db")

_DEFAULT_TEMPLATES = [
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


def _ensure_templates_table() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_templates (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                level TEXT NOT NULL CHECK(level IN ('info','warning','critical')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notification_templates_level ON notification_templates(level)"
        )
        conn.commit()


def _seed_default_templates() -> None:
    _ensure_templates_table()
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_DB_PATH) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM notification_templates")
        count = int(cur.fetchone()[0] or 0)
        if count > 0:
            return
        for tpl in _DEFAULT_TEMPLATES:
            conn.execute(
                """
                INSERT INTO notification_templates (id, label, title, body, level, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tpl["id"],
                    tpl["label"],
                    tpl["title"],
                    tpl["body"],
                    tpl["level"],
                    now_iso,
                    now_iso,
                ),
            )
        conn.commit()


def _validate_template_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, str]:
    data: dict[str, str] = {}

    def _read_str(key: str) -> str:
        return str(payload.get(key) or "").strip()

    required_fields = ["label", "title", "body", "level"] if not partial else []
    for field in required_fields:
        if not _read_str(field):
            raise HTTPException(status_code=400, detail=f"Campo '{field}' obligatorio.")

    for field in ["label", "title", "body", "level"]:
        value = _read_str(field)
        if value:
            data[field] = value

    if "level" in data and data["level"] not in _ALLOWED_LEVELS:
        raise HTTPException(status_code=400, detail="Campo 'level' invalido (info|warning|critical).")

    return data


def _template_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "label": str(row["label"]),
        "title": str(row["title"]),
        "body": str(row["body"]),
        "level": str(row["level"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


@app.on_event("startup")
async def _dashboard_backend_startup() -> None:
    _seed_default_templates()


@app.get("/api/admin/notifications/templates")
async def api_admin_list_notification_templates(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    _ensure_templates_table()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, label, title, body, level, created_at, updated_at
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

    data = _validate_template_payload(payload, partial=False)
    now_iso = datetime.now(timezone.utc).isoformat()
    _ensure_templates_table()

    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO notification_templates (id, label, title, body, level, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    data["label"],
                    data["title"],
                    data["body"],
                    data["level"],
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

    data = _validate_template_payload(payload, partial=True)
    if not data:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar.")

    now_iso = datetime.now(timezone.utc).isoformat()
    set_fields = [f"{key} = ?" for key in data.keys()]
    set_fields.append("updated_at = ?")
    values = [*data.values(), now_iso, template_id]

    _ensure_templates_table()
    with sqlite3.connect(_DB_PATH) as conn:
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
            SELECT id, label, title, body, level, created_at, updated_at
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

    _ensure_templates_table()
    with sqlite3.connect(_DB_PATH) as conn:
        cur = conn.execute("DELETE FROM notification_templates WHERE id = ?", (template_id,))
        if int(cur.rowcount or 0) == 0:
            raise HTTPException(status_code=404, detail=f"Plantilla '{template_id}' no encontrada.")
        conn.commit()

    return {"ok": True, "deleted": True, "id": template_id}


@app.post("/api/admin/notifications/broadcast")
async def api_admin_broadcast_notification(
    payload: dict[str, Any] = Body(...),
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """
    Broadcast admin notification to all websocket listeners (Electron included).
    """
    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    level = str(payload.get("level") or "info").strip().lower()
    template_id = str(payload.get("template_id") or "").strip()
    internal_note = str(payload.get("internal_note") or "").strip()

    if not title:
        raise HTTPException(status_code=400, detail="Campo 'title' obligatorio.")
    if not body:
        raise HTTPException(status_code=400, detail="Campo 'body' obligatorio.")
    if level not in _ALLOWED_LEVELS:
        raise HTTPException(status_code=400, detail="Campo 'level' invalido (info|warning|critical).")

    redis = get_redis_client()
    if not redis:
        raise HTTPException(status_code=503, detail="Redis no disponible para broadcast.")

    event = {
        "type": "admin.alert",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "title": title,
            "body": body,
            "level": level,
            "template_id": template_id or None,
            "internal_note": internal_note or None,
            "sent_by": str(admin.get("username") or admin.get("sub") or "admin"),
        },
    }

    try:
        subscribers = await redis.publish("channel:ui_updates", json.dumps(event, ensure_ascii=False))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo publicar la notificacion: {exc}") from exc

    return {"ok": True, "published_to_subscribers": int(subscribers), "event": event}
