from __future__ import annotations

import asyncio
import logging
import os
import re
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import requests

from core.runtime_flags import get_queue_mode, get_report_pg_dsn, is_pg_source_of_truth_enabled
from core.redis_client import get_redis_client
from core.sqlserver_utils import build_sqlserver_connection_string
from core.pg_admin_store import PgAdminStore
from core.pg_pending_authorization_store import PgPendingAuthorizationStore
from core.pg_runtime_store import PgRuntimeStore
from core.queue_gateway import build_queue_gateway
from core.xvia_auth import LOGIN_URL, extract_csrf_token
from .repositories import (
    PostgresQueueRepository,
    PostgresHistoryRepository,
    SQLServerHistoryRepository,
    utc_today_iso,
)


XVIA_HOME_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/home"
USER_RE = re.compile(r'<i class="fa fa-user-circle"[^>]*></i>\s*([^<]+)')


class DashboardNotFoundError(ValueError):
    pass


class DashboardConflictError(ValueError):
    pass


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


def resolve_dashboard_history_source() -> str:
    raw = (os.getenv("DASHBOARD_HISTORY_SOURCE") or "pg").strip().lower()
    if raw in {"sqlserver", "pg", "auto"}:
        return raw
    return "pg"


class DashboardService:
    def __init__(
        self,
        *,
        sqlite_db_path: str | None = None,
        queue_backend: str | None = None,
        pg_dsn: str | None = None,
    ):
        self.logger = logging.getLogger("dashboard.service")
        sqlserver_assigned_user = resolve_dashboard_assigned_user(self.logger) or ""
        if sqlserver_assigned_user:
            self.logger.info("Filtro de historico SQL Server por UsuarioAsignado=%s", sqlserver_assigned_user)

        sqlserver_conn_str = ""
        try:
            sqlserver_conn_str = build_sqlserver_connection_string()
        except Exception:
            sqlserver_conn_str = ""

        pg_dsn_value = get_report_pg_dsn(pg_dsn)
        has_valid_pg_dsn = bool(pg_dsn_value) and is_pg_source_of_truth_enabled()
        if not has_valid_pg_dsn:
            raise RuntimeError("DashboardService requiere PostgreSQL activo. SQLite eliminado.")
        has_valid_sqlserver = bool(sqlserver_conn_str)
        history_source = resolve_dashboard_history_source()
        if history_source == "pg" and has_valid_pg_dsn:
            self.success_history_repo = PostgresHistoryRepository(
                pg_dsn=pg_dsn_value,
                logger=self.logger,
            )
        elif history_source == "sqlserver" and has_valid_sqlserver:
            self.success_history_repo = SQLServerHistoryRepository(
                conn_str=sqlserver_conn_str,
                assigned_user=sqlserver_assigned_user,
                logger=self.logger,
            )
        elif history_source == "auto":
            if has_valid_pg_dsn:
                self.success_history_repo = PostgresHistoryRepository(
                    pg_dsn=pg_dsn_value,
                    logger=self.logger,
                )
            elif has_valid_sqlserver:
                self.success_history_repo = SQLServerHistoryRepository(
                    conn_str=sqlserver_conn_str,
                    assigned_user=sqlserver_assigned_user,
                    logger=self.logger,
                )
            else:
                self.success_history_repo = PostgresHistoryRepository(pg_dsn=pg_dsn_value, logger=self.logger)
        else:
            self.success_history_repo = PostgresHistoryRepository(pg_dsn=pg_dsn_value, logger=self.logger)
        self.incidents_history_repo = PostgresHistoryRepository(pg_dsn=pg_dsn_value, logger=self.logger)
        resolved_queue_mode = get_queue_mode(queue_backend)
        self.queue_repo = PostgresQueueRepository(
            pg_dsn=pg_dsn_value,
            logger=self.logger,
        )
        self.queue_backend = resolved_queue_mode
        self.runtime_store = PgRuntimeStore(pg_dsn_value, logger=self.logger)
        self.admin_store = PgAdminStore(pg_dsn_value, logger=self.logger)
        self.pending_auth_store = PgPendingAuthorizationStore(pg_dsn_value, logger=self.logger)

    @staticmethod
    def _run_coro_sync(coro):
        try:
            asyncio.get_running_loop()
            loop_running = True
        except RuntimeError:
            loop_running = False

        if not loop_running:
            return asyncio.run(coro)

        result: dict[str, Any] = {"value": None, "error": None}

        def _runner() -> None:
            try:
                result["value"] = asyncio.run(coro)
            except Exception as exc:
                result["error"] = exc

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join()
        if result["error"] is not None:
            raise result["error"]
        return result["value"]

    def _ensure_site_config_exists(self, site_id: str) -> bool:
        site = (site_id or "").strip()
        if not site:
            return False
        if self.admin_store is not None and self.admin_store.get_organismo_config(site):
            return True

        cfg_path = Path("organismo_config.json")
        if not cfg_path.exists():
            return False
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            configs = raw.get("configs") if isinstance(raw, dict) else None
            if not isinstance(configs, list):
                return False
            match = next((c for c in configs if str(c.get("site_id") or "").strip() == site), None)
            if not isinstance(match, dict):
                return False
            self.admin_store.upsert_organismo_config(match)
            return self.admin_store.get_organismo_config(site) is not None
        except Exception:
            return False

    async def _clear_resource_dedupe_keys_async(self, *, site_id: str, resource_id: int) -> None:
        site = (site_id or "").strip()
        rid = int(resource_id)
        if not site:
            return
        redis = get_redis_client()
        if redis is None:
            return
        keys = (
            f"dedupe:resource:{site}:{rid}",
            f"brain-claim:resource:{site}:{rid}",
        )
        try:
            await redis.delete(*keys)
        except Exception as exc:
            self.logger.warning(
                "No se pudieron limpiar dedupe keys site=%s resource_id=%s: %s",
                site,
                rid,
                exc,
            )

    def _clear_resource_dedupe_keys(self, *, site_id: str, resource_id: int) -> None:
        try:
            self._run_coro_sync(
                self._clear_resource_dedupe_keys_async(site_id=site_id, resource_id=resource_id)
            )
        except Exception as exc:
            self.logger.warning(
                "Fallo limpiando dedupe keys site=%s resource_id=%s: %s",
                site_id,
                resource_id,
                exc,
            )

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
        day_value = (day or "").strip() or None
        return self.queue_repo.list_current(day=day_value, page=page, page_size=page_size)

    def get_queue_live(self, *, day: str | None) -> Optional[dict[str, Any]]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.get_live(day=day_value)

    def get_queue_completion_marker(self, *, day: str | None) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.queue_repo.get_completion_marker(day=day_value)

    def list_processing_pauses(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        return self.runtime_store.list_site_processing_pauses(active_only=active_only)

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

        self.runtime_store.set_site_processing_pause(
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
        removed = self.runtime_store.clear_site_processing_pause(site_id=site)
        return {"site_id": site, "paused": False, "removed": bool(removed)}

    def list_item_processing_pauses(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        return self.runtime_store.list_resource_processing_pauses(active_only=active_only)

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

        self.runtime_store.set_resource_processing_pause(
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

        removed = self.runtime_store.clear_resource_processing_pause(site_id=site, resource_id=rid)
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
        result = self.runtime_store.reconcile_processing_with_worker_runtime(
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
        result = self.runtime_store.reconcile_processing_with_worker_runtime(
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

        remove_result = self.queue_repo.cancel_queue_item(site_id=site, resource_id=rid)
        if remove_result.get("removed"):
            self._clear_resource_dedupe_keys(site_id=site, resource_id=rid)
            return {
                "removed": True,
                "site_id": site,
                "resource_id": rid,
                "reason": remove_result.get("reason") or "removed",
                "job_id": remove_result.get("job_id"),
                "recovered_processing": False,
                "recovery_attempted": False,
                "recovery_reason": None,
                "recovery_heartbeat_timeout_seconds": None,
            }

        reason = str(remove_result.get("reason") or "unknown")
        if reason != "processing":
            return {
                "removed": False,
                "site_id": site,
                "resource_id": rid,
                "reason": reason,
                "recovered_processing": False,
                "recovery_attempted": False,
                "recovery_reason": None,
                "recovery_heartbeat_timeout_seconds": None,
            }

        recovery = self.recover_queue_item_processing(site_id=site, resource_id=rid)
        if not recovery.get("released"):
            return {
                "removed": False,
                "site_id": site,
                "resource_id": rid,
                "reason": "processing_owner_alive_or_not_recoverable",
                "recovered_processing": False,
                "recovery_attempted": True,
                "recovery_reason": recovery.get("reason"),
                "recovery_heartbeat_timeout_seconds": recovery.get("heartbeat_timeout_seconds"),
            }

        remove_result_after = self.queue_repo.cancel_queue_item(site_id=site, resource_id=rid)
        if remove_result_after.get("removed"):
            self._clear_resource_dedupe_keys(site_id=site, resource_id=rid)
        return {
            "removed": bool(remove_result_after.get("removed")),
            "site_id": site,
            "resource_id": rid,
            "reason": remove_result_after.get("reason") or "unknown",
            "job_id": remove_result_after.get("job_id"),
            "recovered_processing": True,
            "recovery_attempted": True,
            "recovery_reason": recovery.get("reason"),
            "recovery_heartbeat_timeout_seconds": recovery.get("heartbeat_timeout_seconds"),
        }

    def list_blacklist(self, *, site_id: str | None = None) -> list[dict[str, Any]]:
        return self.admin_store.list_blocked_resources(site_id=site_id)

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
        self.admin_store.block_resource(
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
        removed = self.admin_store.unblock_resource(site_id=site, resource_id=rid)
        if removed:
            self._clear_resource_dedupe_keys(site_id=site, resource_id=rid)
        return {"site_id": site, "resource_id": rid, "unblocked": bool(removed)}

    def list_organismo_configs(self) -> list[dict[str, Any]]:
        seeded = self.admin_store.seed_organismo_config_if_empty()
        if seeded:
            self.logger.info("Seed organismo_config en PG: %s", seeded)
        return self.admin_store.list_organismo_configs()

    def update_organismo_config(self, *, site_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        if "active" in updates:
            updates["active"] = 1 if bool(updates["active"]) else 0
        updated = self.admin_store.update_organismo_config(site_id=site, updates=updates)
        if not updated:
            raise ValueError("No se actualizo configuracion: site no existe o payload vacio.")
        row = self.admin_store.get_organismo_config(site)
        return {"updated": True, "item": row}

    def set_organismo_active(self, *, site_id: str, active: bool) -> dict[str, Any]:
        site = (site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        row = self.admin_store.get_organismo_config(site)
        if not row:
            created = self._ensure_site_config_exists(site)
            if not created:
                raise ValueError(f"site_id no existe en organismo_config: {site}")
            row = self.admin_store.get_organismo_config(site)
        updated = self.admin_store.update_organismo_config(site_id=site, updates={"active": bool(active)})
        if not updated:
            raise ValueError("No se pudo actualizar el estado activo del organismo.")
        row = self.admin_store.get_organismo_config(site)
        return {"updated": True, "item": row}

    # ==========================================================================
    # PENDING AUTHORIZATION QUEUE
    # ==========================================================================

    def list_pending_authorizations(
        self, *, authorization_type: str | None = None
    ) -> dict[str, Any]:
        auth_type = (authorization_type or "").strip() or None
        items = self.pending_auth_store.list_pending_authorizations(authorization_type=auth_type)
        return {
            "items": items,
            "total": len(items),
        }

    def approve_pending_authorization(
        self, *, pending_id: int, authorized_by: str = "dashboard"
    ) -> dict[str, Any]:
        pid = int(pending_id)
        user = (authorized_by or "").strip() or "dashboard"

        pending = self.pending_auth_store.get_pending_authorization(pending_id=pid)
        if not pending:
            return {
                "ok": True,
                "pending_id": pid,
                "noop": True,
                "reason": "pending_not_found",
            }
        if str(pending.get("status") or "").strip().lower() != "pending":
            return {
                "ok": True,
                "pending_id": pid,
                "noop": True,
                "reason": "pending_not_in_pending_status",
            }

        site_id = str(pending.get("site_id") or "").strip()
        if not site_id:
            raise ValueError(f"pending_id {pid} sin site_id.")
        payload = dict(pending.get("payload") or {})
        if not payload:
            raise ValueError(f"pending_id {pid} sin payload.")

        protocol = payload.get("protocol") or payload.get("naturaleza")
        if protocol is not None:
            protocol = str(protocol).strip() or None
        if site_id == "base_online" and protocol:
            protocol = str(protocol).upper()
        if site_id == "base_online" and not protocol:
            protocol = "GENERIC"

        queue_gateway = build_queue_gateway(backend=self.queue_backend, db=self.runtime_store)
        enqueued, job_id = self._run_coro_sync(
            queue_gateway.enqueue(
                site_id=site_id,
                protocol=protocol,
                payload=payload,
            )
        )
        notes = f"job_id={job_id};enqueued={bool(enqueued)}"
        marked = self.pending_auth_store.mark_pending_as_moved_to_queue(
            pending_id=pid,
            authorized_by=user,
            notes=notes,
        )
        if not marked:
            return {
                "ok": True,
                "pending_id": pid,
                "authorized_by": user,
                "site_id": site_id,
                "resource_id": pending.get("resource_id"),
                "job_id": job_id,
                "enqueued": bool(enqueued),
                "moved_to_queue": False,
                "noop": True,
                "reason": "pending_state_changed_before_mark",
            }
        return {
            "ok": True,
            "pending_id": pid,
            "authorized_by": user,
            "site_id": site_id,
            "resource_id": pending.get("resource_id"),
            "job_id": job_id,
            "enqueued": bool(enqueued),
            "moved_to_queue": True,
        }

    def reject_pending_authorization(
        self,
        *,
        pending_id: int,
        reason: str,
        rejected_by: str = "dashboard",
    ) -> dict[str, Any]:
        pid = int(pending_id)
        reject_reason = (reason or "").strip()
        user = (rejected_by or "").strip() or "dashboard"
        if not reject_reason:
            raise ValueError("reason es obligatorio.")
        pending = self.pending_auth_store.get_pending_authorization(pending_id=pid)
        if not pending:
            return {
                "ok": True,
                "pending_id": pid,
                "noop": True,
                "reason": "pending_not_found",
            }
        if str(pending.get("status") or "").strip().lower() != "pending":
            return {
                "ok": True,
                "pending_id": pid,
                "noop": True,
                "reason": "pending_not_in_pending_status",
            }
        rejected = self.pending_auth_store.reject_pending_authorization(
            pending_id=pid,
            reason=reject_reason,
            rejected_by=user,
        )
        if not rejected:
            return {
                "ok": True,
                "pending_id": pid,
                "rejected_by": user,
                "reason": reject_reason,
                "rejected": False,
                "noop": True,
                "state_changed": True,
            }
        return {
            "ok": True,
            "pending_id": pid,
            "rejected_by": user,
            "reason": reject_reason,
            "rejected": True,
        }

    # ==========================================================================
    # CLIENT FOLDER RESOLVER
    # ==========================================================================

    def resolve_client_folder(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        """Calcula la ruta a la carpeta de justificantes del cliente (RECURSOS TELEMATICOS + subfase)."""
        from sites.xaloc_girona.flows.descarga_justificante import (
            _construir_ruta_recursos_telematicos,
        )

        fase_procedimiento = payload.get("fase_procedimiento")
        try:
            ruta = _construir_ruta_recursos_telematicos(payload, fase_procedimiento)
        except Exception as exc:
            self.logger.warning("Error construyendo ruta recursos telematicos: %s", exc)
            # Fallback: usar solo RECURSOS TELEMATICOS sin subfase
            from core.client_documentation import (
                client_identity_from_payload,
            )
            from core.client_paths import get_ruta_cliente_documentacion, resolve_client_docs_base_path

            base_path = resolve_client_docs_base_path()
            client = client_identity_from_payload(payload)
            ruta_base = get_ruta_cliente_documentacion(client, base_path=base_path)
            ruta = ruta_base / "RECURSOS TELEMATICOS"

        return {
            "path": str(ruta),
            "exists": ruta.exists(),
        }
