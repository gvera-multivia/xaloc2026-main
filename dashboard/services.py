from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from core.sqlite_db import SQLiteDatabase
from core.sqlserver_utils import build_sqlserver_connection_string
from core.xvia_auth import LOGIN_URL, extract_csrf_token
from .repositories import (
    PostgresHistoryRepository,
    SQLServerHistoryRepository,
    SqliteHistoryRepository,
    SqliteQueueRepository,
    utc_today_iso,
)


XVIA_HOME_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/home"
USER_RE = re.compile(r'<i class="fa fa-user-circle"[^>]*></i>\s*([^<]+)')


def _fetch_xvia_assigned_user(email: str, password: str, logger: logging.Logger) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Origin": "http://www.xvia-grupoeuropa.net",
        "Connection": "keep-alive",
    }
    try:
        with requests.Session() as session:
            session.headers.update(headers)
            resp_login = session.get(LOGIN_URL, timeout=30)
            token = extract_csrf_token(resp_login.text)
            if not token:
                logger.warning("No se pudo extraer token CSRF en login XVIA para resolver UsuarioAsignado.")
                return None

            data = {
                "_token": token,
                "email": email.strip(),
                "password": password.strip(),
                "remember": "on",
            }
            session.post(LOGIN_URL, data=data, allow_redirects=True, timeout=30)
            resp_home = session.get(XVIA_HOME_URL, timeout=30)
            match = USER_RE.search(resp_home.text)
            if not match:
                logger.warning("No se pudo extraer el nombre de usuario XVIA desde /home.")
                return None
            user_name = (match.group(1) or "").strip()
            return user_name or None
    except Exception as exc:
        logger.warning("No se pudo resolver UsuarioAsignado en XVIA: %s", exc)
        return None


def _run_fetch_user_sync(email: str, password: str, logger: logging.Logger) -> Optional[str]:
    try:
        return _fetch_xvia_assigned_user(email, password, logger)
    except Exception as exc:
        logger.warning("Error resolviendo UsuarioAsignado de XVIA: %s", exc)
        return None


def resolve_dashboard_assigned_user(logger: logging.Logger) -> Optional[str]:
    explicit_user = (os.getenv("DASHBOARD_ASSIGNED_USER") or os.getenv("XVIA_ASSIGNED_USER") or "").strip()
    if explicit_user:
        return explicit_user

    email = (os.getenv("XVIA_EMAIL") or "").strip()
    password = (os.getenv("XVIA_PASSWORD") or "").strip()
    if not email or not password:
        logger.warning(
            "Sin DASHBOARD_ASSIGNED_USER/XVIA_ASSIGNED_USER ni credenciales XVIA; "
            "el historico SQL Server no filtrara por UsuarioAsignado."
        )
        return None

    return _run_fetch_user_sync(email, password, logger)


class DashboardService:
    def __init__(
        self,
        *,
        sqlite_db_path: str | None = None,
        queue_backend: str | None = None,
        pg_dsn: str | None = None,
    ):
        self.logger = logging.getLogger("dashboard.service")
        sqlite_path = sqlite_db_path or os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db")
        sqlserver_assigned_user = resolve_dashboard_assigned_user(self.logger) or ""
        if sqlserver_assigned_user:
            self.logger.info("Filtro de historico SQL Server por UsuarioAsignado=%s", sqlserver_assigned_user)

        sqlserver_conn_str = ""
        try:
            sqlserver_conn_str = build_sqlserver_connection_string()
        except Exception:
            sqlserver_conn_str = ""

        pg_dsn_value = (pg_dsn or os.getenv("REPORT_PG_DSN") or "").strip()
        lowered = pg_dsn_value.lower()
        has_valid_pg_dsn = bool(
            pg_dsn_value
            and lowered not in {"0", "1", "true", "false", "yes", "no", "on", "off", "enabled", "disabled"}
            and ("://" in pg_dsn_value or "=" in pg_dsn_value)
        )
        has_valid_sqlserver = bool(sqlserver_conn_str)
        if has_valid_sqlserver:
            self.success_history_repo = SQLServerHistoryRepository(
                conn_str=sqlserver_conn_str,
                assigned_user=sqlserver_assigned_user,
                logger=self.logger,
            )
        elif has_valid_pg_dsn:
            self.success_history_repo = PostgresHistoryRepository(
                pg_dsn=pg_dsn_value,
                logger=self.logger,
            )
        else:
            self.success_history_repo = SqliteHistoryRepository(
                sqlite_db_path=sqlite_path,
                logger=self.logger,
            )
        self.incidents_history_repo = SqliteHistoryRepository(
            sqlite_db_path=sqlite_path,
            logger=self.logger,
        )
        self.queue_repo = SqliteQueueRepository(
            sqlite_db_path=sqlite_path,
            queue_backend=queue_backend or os.getenv("QUEUE_BACKEND", "sqlite"),
            logger=self.logger,
        )
        self.queue_backend = (queue_backend or os.getenv("QUEUE_BACKEND", "sqlite")).strip().lower()
        self.db = SQLiteDatabase(db_path=sqlite_path)

    @staticmethod
    def _worker_runtime_timeout_seconds() -> int:
        raw = (os.getenv("WORKER_HEARTBEAT_TIMEOUT_SECONDS") or "90").strip()
        try:
            return max(5, int(raw))
        except Exception:
            return 90

    @staticmethod
    def _paginate(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        return {"items": items[start:end], "page": page, "page_size": page_size, "total": len(items)}

    def list_history_days(self, *, source: str, page: int, page_size: int) -> dict[str, Any]:
        source_norm = (source or "all").strip().lower()
        if source_norm == "incidents":
            days = self.incidents_history_repo.list_days(source="incidents")
        elif source_norm == "success":
            days = self.success_history_repo.list_days(source="success")
        else:
            days = sorted(
                set(self.success_history_repo.list_days(source="success"))
                | set(self.incidents_history_repo.list_days(source="incidents")),
                reverse=True,
            )
        return self._paginate(days, page, page_size)

    def list_history_incidents(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.incidents_history_repo.list_incidents(day=day_value, page=page, page_size=page_size)

    def list_history_successes(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.success_history_repo.list_successes(day=day_value, page=page, page_size=page_size)

    def list_queue_days(self, *, page: int, page_size: int) -> dict[str, Any]:
        days = self.queue_repo.list_days()
        return self._paginate(days, page, page_size)

    def list_queue_current(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.list_current(day=day_value, page=page, page_size=page_size)

    def get_queue_live(self, *, day: str | None) -> Optional[dict[str, Any]]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.get_live(day=day_value)

    def get_queue_completion_marker(self, *, day: str | None) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.get_completion_marker(day=day_value)

    def list_processing_pauses(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        return self.db.list_site_processing_pauses(active_only=active_only)

    def pause_site_processing(
        self,
        *,
        site_id: str,
        reason: str | None = None,
        minutes: int | None = None,
    ) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")

        expires_at: str | None = None
        if minutes is not None:
            if minutes <= 0:
                raise ValueError("minutes debe ser > 0.")
            expires_at = (datetime.now() + timedelta(minutes=int(minutes))).isoformat()

        self.db.set_site_processing_pause(
            site_id=site,
            reason=(reason or "").strip() or None,
            expires_at=expires_at,
        )
        return {
            "site_id": site,
            "paused": True,
            "reason": (reason or "").strip() or None,
            "expires_at": expires_at,
        }

    def unpause_site_processing(self, *, site_id: str) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        removed = self.db.clear_site_processing_pause(site_id=site)
        return {"site_id": site, "paused": False, "removed": bool(removed)}

    def list_item_processing_pauses(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        return self.db.list_resource_processing_pauses(active_only=active_only)

    def pause_queue_item_processing(
        self,
        *,
        site_id: str,
        resource_id: int,
        reason: str | None = None,
        minutes: int | None = None,
    ) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        try:
            rid = int(resource_id)
        except Exception as exc:
            raise ValueError("resource_id debe ser entero.") from exc

        expires_at: str | None = None
        if minutes is not None:
            if minutes <= 0:
                raise ValueError("minutes debe ser > 0.")
            expires_at = (datetime.now() + timedelta(minutes=int(minutes))).isoformat()

        self.db.set_resource_processing_pause(
            site_id=site,
            resource_id=rid,
            reason=(reason or "").strip() or None,
            expires_at=expires_at,
        )
        return {
            "site_id": site,
            "resource_id": rid,
            "paused": True,
            "reason": (reason or "").strip() or None,
            "expires_at": expires_at,
        }

    def unpause_queue_item_processing(self, *, site_id: str, resource_id: int) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        try:
            rid = int(resource_id)
        except Exception as exc:
            raise ValueError("resource_id debe ser entero.") from exc

        removed = self.db.clear_resource_processing_pause(site_id=site, resource_id=rid)
        return {"site_id": site, "resource_id": rid, "paused": False, "removed": bool(removed)}

    def recover_stuck_queue_items(
        self,
        *,
        heartbeat_timeout_seconds: int | None = None,
        limit: int = 100,
        site_id: str | None = None,
        resource_id: int | None = None,
    ) -> dict[str, Any]:
        timeout = int(heartbeat_timeout_seconds or self._worker_runtime_timeout_seconds())
        result = self.db.reconcile_processing_with_worker_runtime(
            heartbeat_timeout_seconds=timeout,
            limit=max(1, int(limit)),
            site_id=(site_id or "").strip() or None,
            resource_id=resource_id,
        )
        result["heartbeat_timeout_seconds"] = timeout
        return result

    def recover_queue_item_processing(
        self,
        *,
        site_id: str,
        resource_id: int,
        heartbeat_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        try:
            rid = int(resource_id)
        except Exception as exc:
            raise ValueError("resource_id debe ser entero.") from exc

        timeout = int(heartbeat_timeout_seconds or self._worker_runtime_timeout_seconds())
        result = self.db.reconcile_processing_with_worker_runtime(
            heartbeat_timeout_seconds=timeout,
            limit=100,
            site_id=site,
            resource_id=rid,
        )
        released_item = next(
            (it for it in (result.get("items") or []) if str(it.get("site_id")) == site and int(it.get("resource_id") or -1) == rid),
            None,
        )
        return {
            "site_id": site,
            "resource_id": rid,
            "released": released_item is not None,
            "reason": (released_item or {}).get("reason") or "no_recovery_needed_or_owner_alive",
            "job_id": (released_item or {}).get("job_id"),
            "queue_ref": (released_item or {}).get("queue_ref"),
            "heartbeat_timeout_seconds": timeout,
        }

    def remove_queue_item(self, *, site_id: str, resource_id: int) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        try:
            rid = int(resource_id)
        except Exception as exc:
            raise ValueError("resource_id debe ser entero.") from exc

        if self.queue_backend != "sqlite":
            raise ValueError("Eliminar elementos de cola solo esta soportado en QUEUE_BACKEND=sqlite.")

        result = self.db.remove_pending_queue_item(site_id=site, resource_id=rid)
        if not result.get("removed") and (result.get("reason") or "") == "status_processing":
            recovered = self.recover_queue_item_processing(
                site_id=site,
                resource_id=rid,
            )
            if recovered.get("released"):
                result = self.db.remove_pending_queue_item(site_id=site, resource_id=rid)
                if result.get("removed"):
                    result["recovered_processing"] = True
                else:
                    result["recovered_processing"] = True
                    result["recovered_but_not_removed"] = True
            else:
                result["recovery_attempted"] = True
                result["recovery_reason"] = recovered.get("reason")
                result["recovery_heartbeat_timeout_seconds"] = recovered.get("heartbeat_timeout_seconds")

        if result.get("removed"):
            self.db.clear_resource_processing_pause(site_id=site, resource_id=rid)
            job_id = result.get("job_id")
            if job_id:
                self.db.update_job_run_state(
                    str(job_id),
                    "cancelled",
                    finished=True,
                    error_message="Cancelado manualmente desde dashboard.",
                )
        return result

    def list_blacklist(self, *, site_id: str | None = None) -> list[dict[str, Any]]:
        return self.db.list_blocked_resources(site_id=site_id)

    def block_blacklist(
        self,
        *,
        site_id: str,
        resource_id: int,
        reason: str | None = None,
        source: str | None = "manual",
    ) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        try:
            rid = int(resource_id)
        except Exception as exc:
            raise ValueError("resource_id debe ser entero.") from exc
        self.db.block_resource(
            site_id=site,
            resource_id=rid,
            reason=(reason or "").strip() or None,
            source=(source or "").strip() or "manual",
        )
        return {"site_id": site, "resource_id": rid, "blocked": True}

    def unblock_blacklist(self, *, site_id: str, resource_id: int) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        try:
            rid = int(resource_id)
        except Exception as exc:
            raise ValueError("resource_id debe ser entero.") from exc
        removed = self.db.unblock_resource(site_id=site, resource_id=rid)
        return {"site_id": site, "resource_id": rid, "unblocked": bool(removed)}

    def list_organismo_configs(self) -> list[dict[str, Any]]:
        return self.db.list_organismo_configs()

    def update_organismo_config(self, *, site_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        if "active" in updates:
            updates["active"] = 1 if bool(updates["active"]) else 0
        updated = self.db.update_organismo_config(site_id=site, updates=updates)
        if not updated:
            raise ValueError("No se actualizo configuracion: site no existe o payload vacio.")
        row = self.db.get_organismo_config(site)
        return {"updated": True, "item": row}
