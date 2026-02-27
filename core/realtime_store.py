import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from core.runtime_flags import get_report_pg_dsn, is_pg_source_of_truth_enabled

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency
    psycopg = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_jsonb(value: Optional[dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class NullRealtimeStore:
    enabled = False

    def ensure_schema(self) -> None:
        return

    def record_task_success(
        self,
        *,
        site_id: str,
        resource_id: Optional[int],
        job_id: Optional[str],
        protocol: Optional[str],
        payload: Optional[dict[str, Any]],
        result: Optional[dict[str, Any]],
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        return

    def record_task_failed_final(
        self,
        *,
        site_id: str,
        resource_id: Optional[int],
        job_id: Optional[str],
        protocol: Optional[str],
        payload: Optional[dict[str, Any]],
        error_message: str,
        started_at: datetime,
        ended_at: datetime,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        return

    def record_incident_once(
        self,
        *,
        site_id: str,
        incident_type: str,
        reason: str,
        resource_id: Optional[int],
        expediente: Optional[str],
        payload: Optional[dict[str, Any]],
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        error_code: Optional[str] = None,
        status: Optional[str] = None,
        screenshot_path: Optional[str] = None,
    ) -> None:
        return

    def purge_invalid_incidents(self) -> int:
        return 0


@dataclass
class PostgresConfig:
    dsn: str

    @classmethod
    def from_env(cls) -> Optional["PostgresConfig"]:
        if not is_pg_source_of_truth_enabled():
            return None
        dsn = get_report_pg_dsn()
        if not dsn:
            return None
        return cls(dsn=dsn)


class PostgresRealtimeStore:
    enabled = True

    def __init__(self, config: PostgresConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger("realtime_store")

    def _conn(self):
        if psycopg is None:
            raise RuntimeError("psycopg not installed")
        return psycopg.connect(self.config.dsn)

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS realtime_task_results (
                        id BIGSERIAL PRIMARY KEY,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        site_id TEXT NOT NULL,
                        resource_id BIGINT,
                        job_id TEXT,
                        protocol TEXT,
                        status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
                        day DATE NOT NULL,
                        started_at TIMESTAMPTZ NOT NULL,
                        ended_at TIMESTAMPTZ NOT NULL,
                        payload JSONB,
                        result JSONB,
                        error JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS ix_realtime_task_results_day_site
                    ON realtime_task_results(day, site_id, status)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS realtime_incidents (
                        id BIGSERIAL PRIMARY KEY,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        site_id TEXT NOT NULL,
                        resource_id BIGINT,
                        expediente TEXT,
                        incident_type TEXT NOT NULL,
                        error_code TEXT,
                        reason TEXT,
                        status TEXT NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'REVIEWED', 'RESOLVED')),
                        screenshot_path TEXT,
                        resolved_at TIMESTAMPTZ,
                        resolved_by TEXT,
                        day DATE NOT NULL,
                        started_at TIMESTAMPTZ NOT NULL,
                        ended_at TIMESTAMPTZ NOT NULL,
                        payload JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS ix_realtime_incidents_day_site
                    ON realtime_incidents(day, site_id, incident_type)
                    """
                )
                cur.execute("ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS error_code TEXT")
                cur.execute("ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS status TEXT")
                cur.execute("ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS screenshot_path TEXT")
                cur.execute("ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
                cur.execute("ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS resolved_by TEXT")
                cur.execute("UPDATE realtime_incidents SET error_code = incident_type WHERE error_code IS NULL")
                cur.execute("UPDATE realtime_incidents SET status = 'NEW' WHERE status IS NULL OR status = ''")
                cur.execute("ALTER TABLE realtime_incidents ALTER COLUMN status SET DEFAULT 'NEW'")
                cur.execute("ALTER TABLE realtime_incidents ALTER COLUMN status SET NOT NULL")
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'realtime_incidents_status_check'
                        ) THEN
                            ALTER TABLE realtime_incidents
                            ADD CONSTRAINT realtime_incidents_status_check
                            CHECK (status IN ('NEW', 'REVIEWED', 'RESOLVED'));
                        END IF;
                    END$$
                    """
                )
            conn.commit()

    def _task_dedupe_key(self, *, site_id: str, status: str, resource_id: Optional[int], job_id: Optional[str]) -> str:
        if resource_id is not None:
            return f"task:{site_id}:{status}:rid:{int(resource_id)}"
        return f"task:{site_id}:{status}:job:{job_id or 'unknown'}"

    def _incident_dedupe_key(
        self,
        *,
        site_id: str,
        incident_type: str,
        resource_id: Optional[int],
        expediente: Optional[str],
    ) -> str:
        if resource_id is not None:
            return f"incident:{site_id}:{incident_type}:rid:{int(resource_id)}"
        return f"incident:{site_id}:{incident_type}:exp:{(expediente or '').strip().upper()}"

    def record_task_success(
        self,
        *,
        site_id: str,
        resource_id: Optional[int],
        job_id: Optional[str],
        protocol: Optional[str],
        payload: Optional[dict[str, Any]],
        result: Optional[dict[str, Any]],
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        dedupe_key = self._task_dedupe_key(
            site_id=site_id,
            status="success",
            resource_id=resource_id,
            job_id=job_id,
        )
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO realtime_task_results (
                        dedupe_key, site_id, resource_id, job_id, protocol, status,
                        day, started_at, ended_at, payload, result, error, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'success',
                        %s, %s, %s, %s::jsonb, %s::jsonb, NULL, NOW()
                    )
                    ON CONFLICT (dedupe_key) DO UPDATE SET
                        job_id = EXCLUDED.job_id,
                        protocol = EXCLUDED.protocol,
                        day = EXCLUDED.day,
                        started_at = EXCLUDED.started_at,
                        ended_at = EXCLUDED.ended_at,
                        payload = EXCLUDED.payload,
                        result = EXCLUDED.result,
                        error = NULL,
                        updated_at = NOW()
                    """,
                    (
                        dedupe_key,
                        site_id,
                        resource_id,
                        job_id,
                        protocol,
                        started_at.date(),
                        started_at,
                        ended_at,
                        _to_jsonb(payload),
                        _to_jsonb(result),
                    ),
                )
            conn.commit()

    def record_task_failed_final(
        self,
        *,
        site_id: str,
        resource_id: Optional[int],
        job_id: Optional[str],
        protocol: Optional[str],
        payload: Optional[dict[str, Any]],
        error_message: str,
        started_at: datetime,
        ended_at: datetime,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        dedupe_key = self._task_dedupe_key(
            site_id=site_id,
            status="failed",
            resource_id=resource_id,
            job_id=job_id,
        )
        error_body = {"message": error_message}
        if extra:
            error_body["extra"] = extra
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO realtime_task_results (
                        dedupe_key, site_id, resource_id, job_id, protocol, status,
                        day, started_at, ended_at, payload, result, error, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'failed',
                        %s, %s, %s, %s::jsonb, NULL, %s::jsonb, NOW()
                    )
                    ON CONFLICT (dedupe_key) DO UPDATE SET
                        job_id = EXCLUDED.job_id,
                        protocol = EXCLUDED.protocol,
                        day = EXCLUDED.day,
                        started_at = EXCLUDED.started_at,
                        ended_at = EXCLUDED.ended_at,
                        payload = EXCLUDED.payload,
                        result = NULL,
                        error = EXCLUDED.error,
                        updated_at = NOW()
                    """,
                    (
                        dedupe_key,
                        site_id,
                        resource_id,
                        job_id,
                        protocol,
                        started_at.date(),
                        started_at,
                        ended_at,
                        _to_jsonb(payload),
                        _to_jsonb(error_body),
                    ),
                )
            conn.commit()

    def record_incident_once(
        self,
        *,
        site_id: str,
        incident_type: str,
        reason: str,
        resource_id: Optional[int],
        expediente: Optional[str],
        payload: Optional[dict[str, Any]],
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        error_code: Optional[str] = None,
        status: Optional[str] = None,
        screenshot_path: Optional[str] = None,
    ) -> None:
        ts_start = started_at or _utc_now()
        ts_end = ended_at or ts_start
        incident_type_value = str(incident_type or error_code or "UNKNOWN_INCIDENT").strip() or "UNKNOWN_INCIDENT"
        reason_value = str(reason or "").strip()
        error_code_value = str(error_code or incident_type_value).strip() or incident_type_value
        status_value = str(status or "NEW").strip().upper() or "NEW"
        if status_value not in {"NEW", "REVIEWED", "RESOLVED"}:
            status_value = "NEW"
        screenshot_value = str(screenshot_path or "").strip() or None
        dedupe_key = self._incident_dedupe_key(
            site_id=site_id,
            incident_type=incident_type_value,
            resource_id=resource_id,
            expediente=expediente,
        )
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO realtime_incidents (
                        dedupe_key, site_id, resource_id, expediente, incident_type, error_code, reason, status,
                        screenshot_path, day, started_at, ended_at, payload, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s::jsonb, NOW()
                    )
                    ON CONFLICT (dedupe_key) DO UPDATE SET
                        incident_type = EXCLUDED.incident_type,
                        error_code = EXCLUDED.error_code,
                        reason = EXCLUDED.reason,
                        status = EXCLUDED.status,
                        screenshot_path = EXCLUDED.screenshot_path,
                        day = EXCLUDED.day,
                        started_at = EXCLUDED.started_at,
                        ended_at = EXCLUDED.ended_at,
                        payload = EXCLUDED.payload,
                        updated_at = NOW()
                    """,
                    (
                        dedupe_key,
                        site_id,
                        resource_id,
                        expediente,
                        incident_type_value,
                        error_code_value,
                        reason_value,
                        status_value,
                        screenshot_value,
                        ts_start.date(),
                        ts_start,
                        ts_end,
                        _to_jsonb(payload),
                    ),
                )
            conn.commit()

    def purge_invalid_incidents(self) -> int:
        # En PG limpiamos incidencias de recursos que ya tienen resultado exitoso.
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM realtime_incidents ri
                    WHERE ri.resource_id IS NOT NULL
                      AND EXISTS (
                        SELECT 1
                        FROM realtime_task_results rtr
                        WHERE rtr.status = 'success'
                          AND rtr.site_id = ri.site_id
                          AND rtr.resource_id = ri.resource_id
                      )
                    """
                )
                deleted = int(cur.rowcount or 0)
            conn.commit()
            return deleted


class SqliteRealtimeStore:
    enabled = True

    def __init__(self, sqlite_db_path: str, logger: Optional[logging.Logger] = None):
        self.sqlite_db_path = Path(sqlite_db_path)
        self.logger = logger or logging.getLogger("realtime_store")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        self.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS realtime_task_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    site_id TEXT NOT NULL,
                    resource_id INTEGER,
                    job_id TEXT,
                    protocol TEXT,
                    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
                    day TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    payload TEXT,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_realtime_task_results_day_site
                ON realtime_task_results(day, site_id, status)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS realtime_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    site_id TEXT NOT NULL,
                    resource_id INTEGER,
                    expediente TEXT,
                    incident_type TEXT NOT NULL,
                    error_code TEXT,
                    reason TEXT,
                    status TEXT NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'REVIEWED', 'RESOLVED')),
                    screenshot_path TEXT,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    day TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_realtime_incidents_day_site
                ON realtime_incidents(day, site_id, incident_type)
                """
            )
            for ddl in (
                "ALTER TABLE realtime_incidents ADD COLUMN error_code TEXT",
                "ALTER TABLE realtime_incidents ADD COLUMN status TEXT",
                "ALTER TABLE realtime_incidents ADD COLUMN screenshot_path TEXT",
                "ALTER TABLE realtime_incidents ADD COLUMN resolved_at TEXT",
                "ALTER TABLE realtime_incidents ADD COLUMN resolved_by TEXT",
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            conn.execute("UPDATE realtime_incidents SET error_code = incident_type WHERE error_code IS NULL")
            conn.execute("UPDATE realtime_incidents SET status = 'NEW' WHERE status IS NULL OR status = ''")
            conn.commit()

    def _task_dedupe_key(self, *, site_id: str, status: str, resource_id: Optional[int], job_id: Optional[str]) -> str:
        if resource_id is not None:
            return f"task:{site_id}:{status}:rid:{int(resource_id)}"
        return f"task:{site_id}:{status}:job:{job_id or 'unknown'}"

    def _incident_dedupe_key(
        self,
        *,
        site_id: str,
        incident_type: str,
        resource_id: Optional[int],
        expediente: Optional[str],
    ) -> str:
        if resource_id is not None:
            return f"incident:{site_id}:{incident_type}:rid:{int(resource_id)}"
        return f"incident:{site_id}:{incident_type}:exp:{(expediente or '').strip().upper()}"

    def record_task_success(
        self,
        *,
        site_id: str,
        resource_id: Optional[int],
        job_id: Optional[str],
        protocol: Optional[str],
        payload: Optional[dict[str, Any]],
        result: Optional[dict[str, Any]],
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        dedupe_key = self._task_dedupe_key(
            site_id=site_id,
            status="success",
            resource_id=resource_id,
            job_id=job_id,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO realtime_task_results (
                    dedupe_key, site_id, resource_id, job_id, protocol, status,
                    day, started_at, ended_at, payload, result, error, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, 'success',
                    ?, ?, ?, ?, ?, NULL, CURRENT_TIMESTAMP
                )
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    job_id = excluded.job_id,
                    protocol = excluded.protocol,
                    day = excluded.day,
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    payload = excluded.payload,
                    result = excluded.result,
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    dedupe_key,
                    site_id,
                    resource_id,
                    job_id,
                    protocol,
                    started_at.date().isoformat(),
                    started_at.isoformat(),
                    ended_at.isoformat(),
                    _to_jsonb(payload),
                    _to_jsonb(result),
                ),
            )
            conn.commit()

    def record_task_failed_final(
        self,
        *,
        site_id: str,
        resource_id: Optional[int],
        job_id: Optional[str],
        protocol: Optional[str],
        payload: Optional[dict[str, Any]],
        error_message: str,
        started_at: datetime,
        ended_at: datetime,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        dedupe_key = self._task_dedupe_key(
            site_id=site_id,
            status="failed",
            resource_id=resource_id,
            job_id=job_id,
        )
        error_body = {"message": error_message}
        if extra:
            error_body["extra"] = extra
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO realtime_task_results (
                    dedupe_key, site_id, resource_id, job_id, protocol, status,
                    day, started_at, ended_at, payload, result, error, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, 'failed',
                    ?, ?, ?, ?, NULL, ?, CURRENT_TIMESTAMP
                )
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    job_id = excluded.job_id,
                    protocol = excluded.protocol,
                    day = excluded.day,
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    payload = excluded.payload,
                    result = NULL,
                    error = excluded.error,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    dedupe_key,
                    site_id,
                    resource_id,
                    job_id,
                    protocol,
                    started_at.date().isoformat(),
                    started_at.isoformat(),
                    ended_at.isoformat(),
                    _to_jsonb(payload),
                    _to_jsonb(error_body),
                ),
            )
            conn.commit()

    def record_incident_once(
        self,
        *,
        site_id: str,
        incident_type: str,
        reason: str,
        resource_id: Optional[int],
        expediente: Optional[str],
        payload: Optional[dict[str, Any]],
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        error_code: Optional[str] = None,
        status: Optional[str] = None,
        screenshot_path: Optional[str] = None,
    ) -> None:
        ts_start = started_at or _utc_now()
        ts_end = ended_at or ts_start
        incident_type_value = str(incident_type or error_code or "UNKNOWN_INCIDENT").strip() or "UNKNOWN_INCIDENT"
        reason_value = str(reason or "").strip()
        error_code_value = str(error_code or incident_type_value).strip() or incident_type_value
        status_value = str(status or "NEW").strip().upper() or "NEW"
        if status_value not in {"NEW", "REVIEWED", "RESOLVED"}:
            status_value = "NEW"
        screenshot_value = str(screenshot_path or "").strip() or None
        dedupe_key = self._incident_dedupe_key(
            site_id=site_id,
            incident_type=incident_type_value,
            resource_id=resource_id,
            expediente=expediente,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO realtime_incidents (
                    dedupe_key, site_id, resource_id, expediente, incident_type, error_code, reason, status,
                    screenshot_path, day, started_at, ended_at, payload, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
                )
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    incident_type = excluded.incident_type,
                    error_code = excluded.error_code,
                    reason = excluded.reason,
                    status = excluded.status,
                    screenshot_path = excluded.screenshot_path,
                    day = excluded.day,
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    dedupe_key,
                    site_id,
                    resource_id,
                    expediente,
                    incident_type_value,
                    error_code_value,
                    reason_value,
                    status_value,
                    screenshot_value,
                    ts_start.date().isoformat(),
                    ts_start.isoformat(),
                    ts_end.isoformat(),
                    _to_jsonb(payload),
                ),
            )
            conn.commit()

    def purge_invalid_incidents(self) -> int:
        # Limpia incidencias de recursos:
        # 1) ya completados con exito
        # 2) actualmente seleccionados/en cola (pending/processing/queued)
        with self._conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    DELETE FROM realtime_incidents
                    WHERE resource_id IS NOT NULL
                      AND (
                        EXISTS (
                            SELECT 1
                            FROM realtime_task_results rtr
                            WHERE rtr.status = 'success'
                              AND rtr.site_id = realtime_incidents.site_id
                              AND rtr.resource_id = realtime_incidents.resource_id
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM tramite_queue tq
                            WHERE tq.site_id = realtime_incidents.site_id
                              AND tq.resource_id = realtime_incidents.resource_id
                              AND tq.status IN ('pending', 'processing')
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM job_runs jr
                            WHERE jr.site_id = realtime_incidents.site_id
                              AND jr.resource_id = realtime_incidents.resource_id
                              AND jr.state IN ('queued', 'processing')
                        )
                      )
                    """
                )
            except sqlite3.OperationalError:
                # Compatibilidad con esquemas antiguos sin job_runs/tramite_queue.
                cur.execute(
                    """
                    DELETE FROM realtime_incidents
                    WHERE resource_id IS NOT NULL
                      AND EXISTS (
                        SELECT 1
                        FROM realtime_task_results rtr
                        WHERE rtr.status = 'success'
                          AND rtr.site_id = realtime_incidents.site_id
                          AND rtr.resource_id = realtime_incidents.resource_id
                      )
                    """
                )
            deleted = int(cur.rowcount or 0)
            conn.commit()
            return deleted


def build_realtime_store(logger: Optional[logging.Logger] = None):
    log = logger or logging.getLogger("realtime_store")
    cfg = PostgresConfig.from_env()
    if cfg is not None and psycopg is not None:
        store = PostgresRealtimeStore(cfg, logger=log)
        try:
            store.ensure_schema()
            log.info("Realtime store activo en PostgreSQL.")
            return store
        except Exception as exc:
            log.error("No se pudo inicializar esquema PostgreSQL realtime: %s", exc)
    raise RuntimeError("Realtime store requiere PostgreSQL activo. Fallback SQLite eliminado.")
