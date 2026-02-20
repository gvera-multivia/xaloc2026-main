from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import psycopg

from core.pg_admin_store import PgAdminStore
from core.pg_job_store import build_pg_job_store
from core.runtime_flags import get_report_pg_dsn


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PgRuntimeStore:
    """Runtime store for worker/queue/dashboard controls backed by PostgreSQL."""

    def __init__(self, dsn: str, logger: Optional[logging.Logger] = None):
        self.dsn = dsn
        self.logger = logger or logging.getLogger("pg_runtime_store")
        self.job_store = build_pg_job_store(logger=self.logger)
        self.admin_store = PgAdminStore(dsn=dsn, logger=self.logger)
        self.ensure_schema()

    @classmethod
    def from_env(cls, logger: Optional[logging.Logger] = None) -> "PgRuntimeStore":
        dsn = get_report_pg_dsn()
        if not dsn:
            raise RuntimeError("PG_DSN/REPORT_PG_DSN es obligatorio. SQLite no esta soportado.")
        return cls(dsn=dsn, logger=logger)

    def _conn(self):
        return psycopg.connect(self.dsn)

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS worker_runtime (
                        worker_id TEXT PRIMARY KEY,
                        run_id TEXT,
                        pid INTEGER,
                        status TEXT NOT NULL DEFAULT 'online',
                        current_job_id TEXT,
                        last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS site_processing_pauses (
                        site_id TEXT PRIMARY KEY,
                        reason TEXT,
                        expires_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS resource_processing_pauses (
                        site_id TEXT NOT NULL,
                        resource_id BIGINT NOT NULL,
                        reason TEXT,
                        expires_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (site_id, resource_id)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS incident_locks (
                        incident_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        username TEXT,
                        expires_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            conn.commit()

    # Queue/job ledger API
    def upsert_job_run(
        self,
        *,
        job_id: str,
        site_id: str,
        resource_id: Optional[int],
        protocol: Optional[str],
        payload_snapshot: Optional[dict[str, Any]],
        state: str,
        attempt: int = 0,
        max_attempts: int = 3,
    ) -> None:
        self.job_store.upsert_job_run(
            job_id=job_id,
            site_id=site_id,
            resource_id=resource_id,
            protocol=protocol,
            payload_snapshot=payload_snapshot,
            state=state,
            attempt=attempt,
            max_attempts=max_attempts,
        )

    def update_job_run_state(
        self,
        job_id: str,
        state: str,
        *,
        attempt: Optional[int] = None,
        started: bool = False,
        finished: bool = False,
        error_message: Optional[str] = None,
        result_snapshot: Optional[dict[str, Any]] = None,
        worker_id: Optional[str] = None,
    ) -> None:
        self.job_store.update_job_run_state(
            job_id=job_id,
            state=state,
            attempt=attempt,
            started=started,
            finished=finished,
            error_message=error_message,
            result_snapshot=result_snapshot,
            worker_id=worker_id,
        )

    def count_job_runs(self, site_id: str, states: tuple[str, ...] = ("queued", "processing")) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM jobs
                    WHERE status = ANY(%s)
                      AND COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') = %s
                    """,
                    (list(states), str(site_id)),
                )
                row = cur.fetchone()
                return int(row[0] if row and row[0] is not None else 0)

    def get_job_status(self, *, job_id: str) -> Optional[str]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM jobs WHERE job_id = %s LIMIT 1", (str(job_id),))
                row = cur.fetchone()
                if not row or row[0] is None:
                    return None
                return str(row[0]).strip().lower()

    # Worker runtime API
    def upsert_worker_runtime(
        self,
        *,
        worker_id: str,
        run_id: str,
        pid: int,
        status: str,
        current_job_id: Optional[str],
    ) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO worker_runtime (
                        worker_id, run_id, pid, status, current_job_id, last_heartbeat_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (worker_id) DO UPDATE SET
                        run_id = EXCLUDED.run_id,
                        pid = EXCLUDED.pid,
                        status = EXCLUDED.status,
                        current_job_id = EXCLUDED.current_job_id,
                        last_heartbeat_at = NOW(),
                        updated_at = NOW()
                    """,
                    (worker_id, run_id, int(pid), status, current_job_id),
                )
            conn.commit()

    def mark_worker_runtime_offline(self, *, worker_id: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE worker_runtime
                    SET status = 'offline', updated_at = NOW(), last_heartbeat_at = NOW()
                    WHERE worker_id = %s
                    """,
                    (worker_id,),
                )
            conn.commit()

    def reconcile_processing_with_worker_runtime(
        self,
        *,
        heartbeat_timeout_seconds: int,
        limit: int,
        site_id: str | None = None,
        resource_id: int | None = None,
    ) -> dict[str, Any]:
        # No-op until full worker/job_attempt owner-tracking migration is completed in PG.
        return {"recovered": 0, "alive_workers": 0, "items": []}

    # Processing pause API
    def is_site_processing_paused(self, *, site_id: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM site_processing_pauses
                    WHERE site_id = %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    LIMIT 1
                    """,
                    (str(site_id),),
                )
                return cur.fetchone() is not None

    def is_resource_processing_paused(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM resource_processing_pauses
                    WHERE site_id = %s
                      AND resource_id = %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    LIMIT 1
                    """,
                    (str(site_id), int(resource_id)),
                )
                return cur.fetchone() is not None

    def list_site_processing_pauses(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE expires_at IS NULL OR expires_at > NOW()" if active_only else ""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT site_id, reason, expires_at, created_at, updated_at
                    FROM site_processing_pauses
                    {where}
                    ORDER BY updated_at DESC
                    """
                )
                rows = cur.fetchall()
        return [
            {
                "site_id": row[0],
                "reason": row[1],
                "expires_at": row[2].isoformat() if row[2] else None,
                "created_at": row[3].isoformat() if row[3] else None,
                "updated_at": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ]

    def set_site_processing_pause(self, *, site_id: str, reason: str | None = None, expires_at: str | None = None) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO site_processing_pauses (site_id, reason, expires_at, updated_at)
                    VALUES (%s, %s, %s::timestamptz, NOW())
                    ON CONFLICT (site_id) DO UPDATE SET
                        reason = EXCLUDED.reason,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                    """,
                    (str(site_id), reason, expires_at),
                )
            conn.commit()

    def clear_site_processing_pause(self, *, site_id: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM site_processing_pauses WHERE site_id = %s", (str(site_id),))
                removed = cur.rowcount > 0
            conn.commit()
        return removed

    def list_resource_processing_pauses(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE expires_at IS NULL OR expires_at > NOW()" if active_only else ""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT site_id, resource_id, reason, expires_at, created_at, updated_at
                    FROM resource_processing_pauses
                    {where}
                    ORDER BY updated_at DESC
                    """
                )
                rows = cur.fetchall()
        return [
            {
                "site_id": row[0],
                "resource_id": int(row[1]),
                "reason": row[2],
                "expires_at": row[3].isoformat() if row[3] else None,
                "created_at": row[4].isoformat() if row[4] else None,
                "updated_at": row[5].isoformat() if row[5] else None,
            }
            for row in rows
        ]

    def set_resource_processing_pause(
        self,
        *,
        site_id: str,
        resource_id: int,
        reason: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO resource_processing_pauses (site_id, resource_id, reason, expires_at, updated_at)
                    VALUES (%s, %s, %s, %s::timestamptz, NOW())
                    ON CONFLICT (site_id, resource_id) DO UPDATE SET
                        reason = EXCLUDED.reason,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                    """,
                    (str(site_id), int(resource_id), reason, expires_at),
                )
            conn.commit()

    def clear_resource_processing_pause(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM resource_processing_pauses WHERE site_id = %s AND resource_id = %s",
                    (str(site_id), int(resource_id)),
                )
                removed = cur.rowcount > 0
            conn.commit()
        return removed

    # Blacklist API
    def block_resource(self, *, site_id: str, resource_id: int, reason: str | None = None, source: str | None = None) -> None:
        self.admin_store.block_resource(site_id=site_id, resource_id=resource_id, reason=reason, source=source)

    # Incident locks API
    def acquire_incident_lock(
        self,
        *,
        incident_id: str,
        user_id: str,
        username: str | None = None,
        ttl_seconds: int = 1800,
    ) -> dict[str, Any]:
        incident = str(incident_id or "").strip()
        if not incident:
            raise ValueError("incident_id es obligatorio.")
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id es obligatorio.")
        ttl = max(30, int(ttl_seconds))
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, username, expires_at
                    FROM incident_locks
                    WHERE incident_id = %s
                    """,
                    (incident,),
                )
                row = cur.fetchone()
                now = datetime.now(timezone.utc)
                if row and row[2] and row[2] > now and str(row[0]) != uid:
                    return {
                        "acquired": False,
                        "owner_id": str(row[0]),
                        "owner_username": row[1],
                        "expires_at": row[2].isoformat() if row[2] else None,
                    }
                cur.execute(
                    """
                    INSERT INTO incident_locks (incident_id, user_id, username, expires_at, updated_at)
                    VALUES (%s, %s, %s, NOW() + (%s * INTERVAL '1 second'), NOW())
                    ON CONFLICT (incident_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        username = EXCLUDED.username,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                    """,
                    (incident, uid, username, ttl),
                )
            conn.commit()
        return {
            "acquired": True,
            "owner_id": uid,
            "owner_username": username,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat(),
        }

    def release_incident_lock(self, *, incident_id: str, user_id: str, is_admin: bool = False) -> dict[str, Any]:
        incident = str(incident_id or "").strip()
        uid = str(user_id or "").strip()
        if not incident:
            raise ValueError("incident_id es obligatorio.")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id FROM incident_locks WHERE incident_id = %s",
                    (incident,),
                )
                row = cur.fetchone()
                if not row:
                    return {"released": False, "reason": "not_locked"}
                owner_id = str(row[0] or "")
                if not is_admin and owner_id != uid:
                    return {"released": False, "reason": "not_owner"}
                cur.execute("DELETE FROM incident_locks WHERE incident_id = %s", (incident,))
            conn.commit()
        return {"released": True, "reason": "released"}

    def get_incident_locks(self, *, incident_ids: list[str]) -> dict[str, dict[str, Any]]:
        ids = [str(i).strip() for i in (incident_ids or []) if str(i).strip()]
        if not ids:
            return {}
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT incident_id, user_id, username, expires_at
                    FROM incident_locks
                    WHERE incident_id = ANY(%s)
                      AND expires_at > NOW()
                    """,
                    (ids,),
                )
                rows = cur.fetchall()
        return {
            str(row[0]): {
                "user_id": str(row[1] or ""),
                "username": row[2],
                "expires_at": row[3].isoformat() if row[3] else None,
            }
            for row in rows
        }
