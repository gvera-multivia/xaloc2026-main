import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

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
    ) -> None:
        return


@dataclass
class PostgresConfig:
    dsn: str

    @classmethod
    def from_env(cls) -> Optional["PostgresConfig"]:
        dsn = (os.getenv("REPORT_PG_DSN") or "").strip()
        if not dsn:
            return None
        lowered = dsn.lower()
        # Defensive guard: env flags like "1"/"true" are common and are not valid DSN values.
        if lowered in {"0", "1", "true", "false", "yes", "no", "on", "off", "enabled", "disabled"}:
            return None
        # Accept URL-style DSN (postgresql://...) or keyword DSN (host=... dbname=...).
        if "://" in dsn or "=" in dsn:
            return cls(dsn=dsn)
        return None


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
                        reason TEXT,
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
    ) -> None:
        ts_start = started_at or _utc_now()
        ts_end = ended_at or ts_start
        dedupe_key = self._incident_dedupe_key(
            site_id=site_id,
            incident_type=incident_type,
            resource_id=resource_id,
            expediente=expediente,
        )
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO realtime_incidents (
                        dedupe_key, site_id, resource_id, expediente, incident_type, reason,
                        day, started_at, ended_at, payload, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb, NOW()
                    )
                    ON CONFLICT (dedupe_key) DO UPDATE SET
                        reason = EXCLUDED.reason,
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
                        incident_type,
                        reason,
                        ts_start.date(),
                        ts_start,
                        ts_end,
                        _to_jsonb(payload),
                    ),
                )
            conn.commit()


def build_realtime_store(logger: Optional[logging.Logger] = None):
    log = logger or logging.getLogger("realtime_store")
    cfg = PostgresConfig.from_env()
    if cfg is None:
        log.info("Realtime store deshabilitado: falta o es invalido REPORT_PG_DSN.")
        return NullRealtimeStore()
    if psycopg is None:
        log.warning("Realtime store deshabilitado: falta dependencia psycopg.")
        return NullRealtimeStore()
    store = PostgresRealtimeStore(cfg, logger=log)
    try:
        store.ensure_schema()
    except Exception as exc:
        log.error("No se pudo inicializar esquema PostgreSQL realtime: %s", exc)
        return NullRealtimeStore()
    return store
