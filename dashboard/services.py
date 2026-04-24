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
DEFAULT_DASHBOARD_ASSIGNED_USER = "Guillen Vera"
_AUTH_TOKEN_RE = re.compile(r"(autorizaci|authorization|autoritzaci|(?:^|[^a-z])aut(?:[^a-z]|$))", re.IGNORECASE)
_AUTH_MISSING_RE = re.compile(
    r"(missing|falt(?:a|an|aba|ante)?|sin\s+aut|no\s+(?:se\s+)?(?:encuentra|encontro|existe)|ausent)",
    re.IGNORECASE,
)


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
            "se usa fallback fijo UsuarioAsignado=%s.",
            DEFAULT_DASHBOARD_ASSIGNED_USER,
        )
        return DEFAULT_DASHBOARD_ASSIGNED_USER

    resolved = _run_fetch_user_sync(email, password, logger)
    if resolved:
        return resolved
    logger.warning(
        "No se pudo resolver UsuarioAsignado en XVIA; se usa fallback fijo=%s.",
        DEFAULT_DASHBOARD_ASSIGNED_USER,
    )
    return DEFAULT_DASHBOARD_ASSIGNED_USER


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
        self.sqlserver_conn_str = sqlserver_conn_str

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

    async def _publish_admin_alert_async(
        self,
        *,
        title: str,
        body: str,
        level: str = "info",
        sent_by: str = "dashboard",
        internal_note: str | None = None,
    ) -> None:
        redis = get_redis_client()
        if redis is None:
            return
        event = {
            "type": "admin.alert",
            "timestamp": datetime.now().astimezone().isoformat(),
            "data": {
                "title": str(title or "").strip() or "Aviso operativo",
                "body": str(body or "").strip() or "Sin detalle",
                "level": str(level or "info").strip().lower() or "info",
                "template_id": None,
                "internal_note": (str(internal_note or "").strip() or None),
                "sent_by": str(sent_by or "dashboard"),
            },
        }
        await redis.publish("channel:ui_updates", json.dumps(event, ensure_ascii=False))

    def _publish_admin_alert_best_effort(
        self,
        *,
        title: str,
        body: str,
        level: str = "info",
        sent_by: str = "dashboard",
        internal_note: str | None = None,
    ) -> None:
        try:
            self._run_coro_sync(
                self._publish_admin_alert_async(
                    title=title,
                    body=body,
                    level=level,
                    sent_by=sent_by,
                    internal_note=internal_note,
                )
            )
        except Exception as exc:
            self.logger.warning("No se pudo publicar admin.alert (best-effort): %s", exc)

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

    @staticmethod
    def _extract_resource_id_from_incident(item: dict[str, Any]) -> Optional[int]:
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

    @staticmethod
    def _build_incident_row_id(item: dict[str, Any], rid: Optional[int]) -> str:
        site = str(item.get("site_id") or "").strip()
        rid_part = str(rid) if rid is not None else "none"
        incident_type = str(item.get("incident_type") or "").strip().upper() or "UNKNOWN"
        expediente = str(item.get("expediente") or "").strip().upper() or "none"
        return f"{site}:{rid_part}:{incident_type}:{expediente}"

    @staticmethod
    def _to_int_or_none(value: Any) -> Optional[int]:
        try:
            if value is None or str(value).strip() == "":
                return None
            return int(str(value).strip())
        except Exception:
            return None

    def _looks_like_missing_authorization_incident(self, item: dict[str, Any]) -> bool:
        text = " ".join(
            part for part in (
                str(item.get("incident_type") or "").strip(),
                str(item.get("reason") or "").strip(),
            )
            if part
        )
        if not text:
            return False
        return bool(_AUTH_TOKEN_RE.search(text) and _AUTH_MISSING_RE.search(text))

    def _resolve_client_folder_context(
        self,
        *,
        numclient: int | None,
        conn_str: str | None,
        sujeto_recurso: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from core.client_documentation import client_identity_from_db, client_identity_from_payload
        from core.client_paths import get_ruta_cliente_documentacion, resolve_client_docs_base_path

        identity = None
        if numclient is not None and conn_str:
            try:
                identity = client_identity_from_db(
                    int(numclient),
                    conn_str,
                    sujeto_recurso=sujeto_recurso,
                )
            except Exception:
                identity = None

        if identity is None and isinstance(payload, dict):
            try:
                identity = client_identity_from_payload(payload)
            except Exception:
                identity = None

        if identity is None:
            return {"exists": False, "path": None}

        try:
            base_path = resolve_client_docs_base_path()
            client_root = get_ruta_cliente_documentacion(identity, base_path)
        except Exception:
            return {"exists": False, "path": None}

        return {"exists": client_root.exists(), "path": str(client_root)}

    def _enrich_incident_items_with_gesdoc(
        self,
        *,
        items: list[dict[str, Any]],
        conn_str: str | None,
    ) -> None:
        if not items:
            return

        for item in items:
            item.setdefault("gesdoc_missing_auth_candidate", False)
            item.setdefault("client_folder_exists", False)
            item.setdefault("gesdoc_ui_variant", "default")

        rid_list: list[int] = []
        for item in items:
            rid = self._extract_resource_id_from_incident(item)
            if rid is not None:
                item["resource_id"] = rid
                rid_list.append(rid)

        metadata_map: dict[int, dict[str, Any]] = {}
        if conn_str and rid_list:
            try:
                from core.repositories.resource_repository import ResourceRepository

                repo = ResourceRepository(conn_str=conn_str, logger=self.logger)
                resources = repo.get_resources_by_ids(site_id="all", resource_ids=rid_list)
                metadata_map = {
                    int(resource.id): dict(resource.metadata or {})
                    for resource in resources
                    if getattr(resource, "id", None) is not None
                }
            except Exception as exc:
                self.logger.warning("Error cargando metadata de recursos para incidencias GESDOC: %s", exc)

        folder_cache: dict[tuple[int, str], dict[str, Any]] = {}

        for item in items:
            rid = self._extract_resource_id_from_incident(item)
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            metadata = metadata_map.get(rid or -1, {})

            numclient = self._to_int_or_none(
                item.get("numclient")
                or metadata.get("numclient")
                or payload.get("numclient")
                or payload.get("idCliente")
                or payload.get("client_id")
                or payload.get("id_cliente")
            )
            cliente_tipo = self._to_int_or_none(
                item.get("cliente_tipo")
                or metadata.get("cliente_tipo")
                or payload.get("cliente_tipo")
                or payload.get("tipodecliente")
            )
            sujeto_recurso = (
                str(
                    metadata.get("SujetoRecurso")
                    or metadata.get("sujeto_recurso")
                    or payload.get("sujeto_recurso")
                    or payload.get("SujetoRecurso")
                    or ""
                ).strip()
                or None
            )

            if numclient is not None:
                item["numclient"] = numclient
            if cliente_tipo is not None:
                item["cliente_tipo"] = cliente_tipo

            is_candidate = bool(numclient is not None and self._looks_like_missing_authorization_incident(item))
            item["gesdoc_missing_auth_candidate"] = is_candidate
            if not is_candidate:
                item["client_folder_exists"] = False
                item["gesdoc_ui_variant"] = "default"
                continue

            cache_key = (int(numclient), sujeto_recurso or "")
            if cache_key not in folder_cache:
                folder_cache[cache_key] = self._resolve_client_folder_context(
                    numclient=numclient,
                    conn_str=conn_str,
                    sujeto_recurso=sujeto_recurso,
                    payload=payload,
                )
            folder_ctx = folder_cache[cache_key]
            exists = bool(folder_ctx.get("exists"))
            item["client_folder_exists"] = exists
            item["gesdoc_ui_variant"] = "purple" if exists else "default"
            if folder_ctx.get("path"):
                item["client_folder_path"] = folder_ctx.get("path")

    def get_pending_gesdoc_incident(
        self,
        *,
        site_id: str,
        resource_id: int,
        user: Optional[dict[str, Any]] = None,
        require_lock_owner: bool = True,
    ) -> dict[str, Any]:
        site = str(site_id or "").strip()
        if not site:
            raise DashboardNotFoundError("site_id es obligatorio.")
        rid = int(resource_id)
        items = self.incidents_history_repo.list_incidents_for_resource(
            day=utc_today_iso(),
            site_id=site,
            resource_id=rid,
            statuses=["NEW", "REVIEWED"],
        )
        if not items:
            raise DashboardNotFoundError(f"No hay incidencia pendiente para {site}/{rid}.")

        self._enrich_incident_items_with_gesdoc(items=items, conn_str=self.sqlserver_conn_str)
        candidates = [item for item in items if item.get("gesdoc_missing_auth_candidate")]
        if not candidates:
            raise DashboardNotFoundError(f"La incidencia {site}/{rid} no es candidata a operativa GESDOC.")

        chosen = next((item for item in candidates if item.get("gesdoc_ui_variant") == "purple"), candidates[0])
        incident_id = self._build_incident_row_id(chosen, rid)
        legacy_id = f"{site}:{rid}"
        chosen["incident_id"] = incident_id
        locks = self.runtime_store.get_incident_locks(incident_ids=[incident_id, legacy_id])
        lock_info = locks.get(incident_id) or locks.get(legacy_id)
        if lock_info:
            chosen["locked"] = True
            chosen["lock_user_id"] = lock_info.get("user_id")
            chosen["lock_username"] = lock_info.get("username")
            chosen["lock_expires_at"] = lock_info.get("expires_at")
        else:
            chosen["locked"] = False
            chosen["lock_user_id"] = None
            chosen["lock_username"] = None
            chosen["lock_expires_at"] = None

        if require_lock_owner:
            current_user_id = str((user or {}).get("sub") or "").strip()
            if not lock_info:
                raise DashboardConflictError("La incidencia debe estar bloqueada antes de consultar GESDOC.")
            lock_user_id = str(lock_info.get("user_id") or "").strip()
            if not current_user_id or lock_user_id != current_user_id:
                owner = lock_info.get("username") or lock_user_id or "otro usuario"
                raise DashboardConflictError(f"La incidencia está bloqueada por {owner}.")

        return chosen

    @staticmethod
    def _history_user_candidates(user: Optional[dict[str, Any]]) -> list[str]:
        if not isinstance(user, dict):
            return []
        candidates = []
        for key in ("xvia_username", "username"):
            value = str(user.get(key) or "").strip()
            if value and value not in candidates:
                candidates.append(value)
        return candidates

    def list_history_days(
        self,
        *,
        source: str,
        page: int,
        page_size: int,
        user: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        source_norm = (source or "all").strip().lower()
        user_candidates = self._history_user_candidates(user)
        if source_norm == "incidents":
            days = self.incidents_history_repo.list_days(source="incidents")
        elif source_norm == "success":
            if isinstance(self.success_history_repo, SQLServerHistoryRepository):
                # SQL Server keeps filtering by configured UsuarioAsignado (existing behavior).
                days = self.success_history_repo.list_days(source="success")
            else:
                days = self.success_history_repo.list_days(source="success", user_candidates=user_candidates)
        else:
            if isinstance(self.success_history_repo, SQLServerHistoryRepository):
                # SQL Server keeps filtering by configured UsuarioAsignado (existing behavior).
                success_days = self.success_history_repo.list_days(source="success")
            else:
                success_days = self.success_history_repo.list_days(source="success", user_candidates=user_candidates)
            days = sorted(
                set(success_days)
                | set(self.incidents_history_repo.list_days(source="incidents")),
                reverse=True,
            )
        return self._paginate(days, page, page_size)

    def list_history_incidents(self, *, day: str | None, page: int, page_size: int) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        return self.incidents_history_repo.list_incidents(day=day_value, page=page, page_size=page_size)

    def list_pending_incidents(self, *, page: int, page_size: int) -> dict[str, Any]:
        try:
            cleanup = self.runtime_store.purge_completed_resources_from_operational_tables()
            if int(cleanup.get("deleted_incidents") or 0) > 0:
                self.logger.info(
                    "Incidencias depuradas por completado local: %s",
                    int(cleanup.get("deleted_incidents") or 0),
                )
        except Exception as exc:
            self.logger.warning("No se pudo depurar incidencias por completado local: %s", exc)

        day_value = utc_today_iso()
        res = self.incidents_history_repo.list_incidents(
            day=day_value,
            page=page,
            page_size=page_size,
            statuses=["NEW", "REVIEWED"],
        )
        items = res.get("items") or []
        conn_str = getattr(self, "sqlserver_conn_str", None)
        if not conn_str:
            try:
                conn_str = build_sqlserver_connection_string()
            except Exception:
                pass

        if not items:
            return res

        def _fetch_sqlserver_completed_ids(resource_ids: list[int]) -> set[int]:
            if not resource_ids:
                return set()
            try:
                import pyodbc
            except Exception:
                return set()

            done: set[int] = set()
            ids = sorted({int(x) for x in resource_ids})
            chunk = 500
            conn = pyodbc.connect(conn_str, autocommit=True)
            try:
                cur = conn.cursor()
                for i in range(0, len(ids), chunk):
                    batch = ids[i : i + chunk]
                    placeholders = ",".join(["?"] * len(batch))
                    query = (
                        f"SELECT idRecurso FROM Recursos.RecursosExp "
                        f"WHERE idRecurso IN ({placeholders}) "
                        "AND (Estado = 2 OR FUsuarioCompletado IS NOT NULL)"
                    )
                    cur.execute(query, batch)
                    for row in cur.fetchall():
                        try:
                            done.add(int(row[0]))
                        except Exception:
                            continue
            finally:
                conn.close()
            return done

        try:
            rids = []
            rid_to_sites: dict[int, set[str]] = {}
            for it in items:
                rid = self._extract_resource_id_from_incident(it)
                if rid is None:
                    continue
                it["resource_id"] = rid
                rids.append(rid)
                site = str(it.get("site_id") or "").strip()
                if site:
                    rid_to_sites.setdefault(rid, set()).add(site)

            sql_completed_ids = _fetch_sqlserver_completed_ids(rids)
            if sql_completed_ids:
                removed = 0
                for rid in sorted(sql_completed_ids):
                    for site in sorted(rid_to_sites.get(rid, set())):
                        removed += int(
                            self.incidents_history_repo.clear_incident(
                                site_id=site,
                                resource_id=rid,
                                incident_type=None,
                            )
                        )
                if removed > 0:
                    self.logger.info(
                        "Incidencias depuradas por completado en SQL Server: %s (resources=%s)",
                        removed,
                        len(sql_completed_ids),
                    )
                    res = self.incidents_history_repo.list_incidents(
                        day=day_value,
                        page=page,
                        page_size=page_size,
                        statuses=["NEW", "REVIEWED"],
                    )
                    items = res.get("items") or []

            self._enrich_incident_items_with_gesdoc(items=items, conn_str=conn_str)
        except Exception as exc:
            self.logger.warning("Error enriqueciendo incidencias con datos GESDOC: %s", exc)

        return res

    def list_history_successes(
        self,
        *,
        day: str | None,
        page: int,
        page_size: int,
        user: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        day_value = (day or "").strip() or utc_today_iso()
        user_candidates = self._history_user_candidates(user)
        if isinstance(self.success_history_repo, SQLServerHistoryRepository):
            return self.success_history_repo.list_successes(
                day=day_value,
                page=page,
                page_size=page_size,
            )
        return self.success_history_repo.list_successes(
            day=day_value,
            page=page,
            page_size=page_size,
            user_candidates=user_candidates,
        )

    def list_history_top_users(
        self,
        *,
        limit: int = 500,
        day: str | None = None,
        user: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit), 5000))
        day_value = (day or "").strip() or None
        user_candidates = self._history_user_candidates(user)
        if hasattr(self.success_history_repo, "list_top_users"):
            items = self.success_history_repo.list_top_users(limit=safe_limit, day=day_value)
        else:
            items = []

        # SQL Server fallback: if global query returns empty, rebuild ranking by
        # aggregating each historical day (day queries are usually stable).
        if (
            not day_value
            and not items
            and isinstance(self.success_history_repo, SQLServerHistoryRepository)
            and hasattr(self.success_history_repo, "list_days")
        ):
            try:
                per_user_totals: dict[str, int] = {}
                days = self.success_history_repo.list_days(source="success")
                for d in days:
                    day_items = self.success_history_repo.list_top_users(limit=5000, day=d)
                    for row in day_items:
                        user_name = str(row.get("usuario_asignado") or "").strip()
                        if not user_name:
                            continue
                        per_user_totals[user_name] = per_user_totals.get(user_name, 0) + int(
                            row.get("total_recursos") or 0
                        )
                items = [
                    {"usuario_asignado": user_name, "total_recursos": total}
                    for user_name, total in per_user_totals.items()
                ]
                items.sort(key=lambda r: (-int(r.get("total_recursos") or 0), str(r.get("usuario_asignado") or "")))
                items = items[:safe_limit]
            except Exception as exc:
                self.logger.warning("Fallback de top global por dias fallo: %s", exc)

        # MORRIGAN = total real mostrado en Historial (mismas reglas/filtros del listado de success).
        morrigan_total = 0
        try:
            if day_value:
                if isinstance(self.success_history_repo, SQLServerHistoryRepository):
                    one_day = self.success_history_repo.list_successes(day=day_value, page=1, page_size=1)
                else:
                    one_day = self.success_history_repo.list_successes(
                        day=day_value,
                        page=1,
                        page_size=1,
                        user_candidates=user_candidates,
                    )
                morrigan_total = int(one_day.get("total") or 0)
            else:
                if isinstance(self.success_history_repo, SQLServerHistoryRepository):
                    success_days = self.success_history_repo.list_days(source="success")
                else:
                    success_days = self.success_history_repo.list_days(
                        source="success",
                        user_candidates=user_candidates,
                    )
                for one_day in success_days:
                    if isinstance(self.success_history_repo, SQLServerHistoryRepository):
                        day_result = self.success_history_repo.list_successes(day=one_day, page=1, page_size=1)
                    else:
                        day_result = self.success_history_repo.list_successes(
                            day=one_day,
                            page=1,
                            page_size=1,
                            user_candidates=user_candidates,
                        )
                    morrigan_total += int(day_result.get("total") or 0)
        except Exception as exc:
            self.logger.warning("No se pudo calcular morrigan_total desde historial: %s", exc)
            morrigan_total = 0

        if morrigan_total <= 0 and items:
            morrigan_total = int(sum(int(it.get("total_recursos") or 0) for it in items))

        morrigan_today_total = 0
        try:
            today_value = utc_today_iso()
            if isinstance(self.success_history_repo, SQLServerHistoryRepository):
                today_result = self.success_history_repo.list_successes(day=today_value, page=1, page_size=1)
            else:
                today_result = self.success_history_repo.list_successes(
                    day=today_value,
                    page=1,
                    page_size=1,
                    user_candidates=user_candidates,
                )
            morrigan_today_total = int(today_result.get("total") or 0)
        except Exception as exc:
            self.logger.warning("No se pudo calcular morrigan_today_total desde historial: %s", exc)
            morrigan_today_total = 0

        return {
            "items": items,
            "total": len(items),
            "limit": safe_limit,
            "day": day_value,
            "morrigan_total": morrigan_total,
            "morrigan_today_total": morrigan_today_total,
        }

    def get_history_postgres_details(
        self,
        *,
        site_id: str,
        resource_id: int,
        limit: int = 200,
    ) -> dict[str, Any]:
        site = str(site_id or "").strip()
        if not site:
            raise ValueError("site_id es obligatorio.")
        try:
            rid = int(resource_id)
        except Exception as exc:
            raise ValueError("resource_id debe ser entero.") from exc
        safe_limit = max(1, min(int(limit), 1000))
        primary = self.incidents_history_repo.list_postgres_details(
            site_id=site,
            resource_id=rid,
            limit=safe_limit,
        )
        if primary.get("total"):
            return primary

        # Fallback: cuando el historial visible viene de SQL Server, site_id puede
        # ser el nombre del organismo y no el identificador técnico de PG.
        return self.incidents_history_repo.list_postgres_details(
            site_id=None,
            resource_id=rid,
            limit=safe_limit,
        )

    @staticmethod
    def _extract_variant_from_payload(payload: dict[str, Any] | None) -> tuple[str | None, str | None]:
        data = payload if isinstance(payload, dict) else {}
        protocol = (
            data.get("protocol")
            or data.get("protocolo")
            or data.get("naturaleza")
        )
        fase = data.get("fase_procedimiento") or data.get("FaseProcedimiento")
        protocol_text = str(protocol).strip() if protocol is not None else ""
        fase_text = str(fase).strip() if fase is not None else ""
        return (protocol_text or None, fase_text or None)

    def _get_resource_variant(self, *, site_id: str, resource_id: int) -> tuple[str | None, str | None]:
        try:
            details = self.get_history_postgres_details(site_id=site_id, resource_id=resource_id, limit=25)
        except Exception:
            return (None, None)

        for item in details.get("items") or []:
            protocol, fase = self._extract_variant_from_payload(item.get("payload"))
            if protocol or fase:
                return (protocol, fase)
            protocol_value = str(item.get("protocol") or "").strip() or None
            if protocol_value:
                return (protocol_value, None)
        return (None, None)

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
        items = self.admin_store.list_blocked_resources(site_id=site_id)
        for item in items:
            site = str(item.get("site_id") or "").strip()
            rid = item.get("resource_id")
            if not site or rid is None:
                item.setdefault("protocol", None)
                item.setdefault("fase_procedimiento", None)
                continue
            try:
                protocol, fase = self._get_resource_variant(site_id=site, resource_id=int(rid))
            except Exception:
                protocol, fase = (None, None)
            item["protocol"] = protocol
            item["fase_procedimiento"] = fase
        return items

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
        
        queue_removed = False
        try:
            res = self.remove_queue_item(site_id=site, resource_id=rid)
            queue_removed = res.get("removed", False)
        except Exception as exc:
            self.logger.warning("No se pudo remover el recurso %s de las colas tras bloqueo: %s", rid, exc)
            
        return {"site_id": site, "resource_id": rid, "blocked": True, "queue_removed": queue_removed}

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
            # Delete from MinIO
            try:
                from core.screenshot_store import get_screenshot_store

                store = get_screenshot_store()
                store.delete_screenshot(site_id=site, resource_id=rid)
            except Exception as e:
                self.logger.warning("Fallo al borrar screenshot al desbloquear site=%s resource_id=%s: %s", site, rid, e)

            self._clear_resource_dedupe_keys(site_id=site, resource_id=rid)
            try:
                # Al desbloquear, limpiar la incidencia operativa asociada para
                # evitar que quede pendiente visualmente aunque ya no este bloqueado.
                self.incidents_history_repo.clear_incident(
                    site_id=site,
                    resource_id=rid,
                    incident_type="RESOURCE_BLOCKED",
                )
            except Exception as exc:
                self.logger.warning(
                    "No se pudo limpiar incidencia RESOURCE_BLOCKED site=%s resource_id=%s: %s",
                    site,
                    rid,
                    exc,
                )
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
        if "claim_limit_per_tick" in updates:
            raw = updates.get("claim_limit_per_tick")
            if raw in (None, "", "null"):
                updates["claim_limit_per_tick"] = None
            else:
                try:
                    value = int(raw)
                except Exception as exc:
                    raise ValueError("claim_limit_per_tick debe ser entero o null.") from exc
                if value <= 0:
                    raise ValueError("claim_limit_per_tick debe ser > 0.")
                updates["claim_limit_per_tick"] = value
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
        raw_pending_payload = dict(pending.get("payload") or {})
        # Compatibilidad: algunos pendientes históricos guardaron un sobre con
        # normalized_payload en lugar del payload de ejecución directo.
        nested_normalized = raw_pending_payload.get("normalized_payload")
        if isinstance(nested_normalized, dict) and nested_normalized:
            payload = dict(nested_normalized)
            # Conservamos fallbacks del sobre externo por si faltan campos.
            for k, v in raw_pending_payload.items():
                payload.setdefault(str(k), v)
        else:
            payload = raw_pending_payload
        if not payload:
            raise ValueError(f"pending_id {pid} sin payload.")

        # Guard-rail: asegurar idRecurso en raíz para worker/document_fetcher.
        rid_value = payload.get("idRecurso")
        if rid_value is None or str(rid_value).strip() == "":
            rid_value = (
                payload.get("external_resource_id")
                if payload.get("external_resource_id") is not None
                else pending.get("resource_id")
            )
            if rid_value is not None and str(rid_value).strip() != "":
                payload["idRecurso"] = rid_value

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
        try:
            rid = pending.get("resource_id")
            rid_txt = f" (recurso {rid})" if rid is not None else ""
            self._publish_admin_alert_best_effort(
                title=f"Autorización aprobada{rid_txt}",
                body=f"Se autorizó {site_id}{rid_txt} y se movió a cola de trabajo.",
                level="info",
                sent_by=user,
                internal_note="pending_auth_approved",
            )
        except Exception:
            pass
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
        try:
            rid = pending.get("resource_id")
            rid_txt = f" (recurso {rid})" if rid is not None else ""
            site_id = str(pending.get("site_id") or "").strip() or "site"
            self._publish_admin_alert_best_effort(
                title=f"Autorización rechazada{rid_txt}",
                body=f"Se rechazó {site_id}{rid_txt}. Motivo: {reject_reason}",
                level="warning",
                sent_by=user,
                internal_note="pending_auth_rejected",
            )
        except Exception:
            pass
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
        from core.client_documentation import client_identity_from_payload
        from core.client_paths import (
            get_phase_folder_name,
            get_ruta_cliente_documentacion,
            get_ruta_recursos_telematicos,
            resolve_client_docs_base_path,
        )

        fase_procedimiento = payload.get("fase_procedimiento")
        try:
            base_path = resolve_client_docs_base_path()
            client = client_identity_from_payload(payload)
            ruta_cliente = get_ruta_cliente_documentacion(client, base_path=base_path)
            ruta = get_ruta_recursos_telematicos(
                client=client,
                base_path=base_path,
                fase_procedimiento=str(fase_procedimiento or ""),
            )
            phase_folder = get_phase_folder_name(str(fase_procedimiento or ""))
        except Exception as exc:
            self.logger.warning("Error construyendo ruta recursos telematicos: %s", exc)
            # Fallback: usar solo RECURSOS TELEMATICOS sin subfase
            from core.client_documentation import (
                client_identity_from_payload,
            )
            from core.client_paths import (
                find_or_create_normalized_subfolder,
                get_ruta_cliente_documentacion,
                resolve_client_docs_base_path,
            )

            base_path = resolve_client_docs_base_path()
            client = client_identity_from_payload(payload)
            ruta_base = get_ruta_cliente_documentacion(client, base_path=base_path)
            ruta = find_or_create_normalized_subfolder(ruta_base, "RECURSOS TELEMATICOS")
            ruta_cliente = ruta_base
            phase_folder = None

        return {
            "path": str(ruta),
            "exists": ruta.exists(),
            "fase_procedimiento": (str(fase_procedimiento or "").strip() or None),
            "fase_folder": phase_folder,
            "ruta_cliente": str(ruta_cliente),
        }
