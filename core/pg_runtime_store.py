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
        self._worker_singleton_lock_conn: Any | None = None
        self._worker_singleton_lock_key: int = 20260223
        self.ensure_schema()

    @classmethod
    def from_env(cls, logger: Optional[logging.Logger] = None) -> "PgRuntimeStore":
        dsn = get_report_pg_dsn()
        if not dsn:
            raise RuntimeError("PG_DSN/REPORT_PG_DSN es obligatorio. SQLite no esta soportado.")
        return cls(dsn=dsn, logger=logger)

    def _conn(self):
        return psycopg.connect(self.dsn)

    @staticmethod
    def _job_site_expr() -> str:
        return "COALESCE(payload_json->>'site_id', NULLIF(split_part(dedup_key, ':', 1), ''), '')"

    @staticmethod
    def _job_resource_expr() -> str:
        return (
            "COALESCE("
            "CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$' THEN (payload_json->>'idRecurso')::bigint END,"
            "CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$' THEN ((payload_json->>'idRecurso')::numeric)::bigint END,"
            "CASE WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$' THEN split_part(dedup_key, ':', 2)::bigint END,"
            "CASE WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\\.0+$' THEN (split_part(dedup_key, ':', 2)::numeric)::bigint END"
            ")"
        )

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
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS process_runtime_controls (
                        process_name TEXT PRIMARY KEY,
                        desired_state TEXT NOT NULL DEFAULT 'running',
                        reason TEXT,
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

    def has_active_job_for_resource(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM jobs
                    WHERE status IN ('queued', 'processing')
                      AND COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') = %s
                      AND COALESCE(
                            CASE
                                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$'
                                    THEN (payload_json->>'idRecurso')::bigint
                                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$'
                                    THEN ((payload_json->>'idRecurso')::numeric)::bigint
                                ELSE NULL
                            END,
                            CASE
                                WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$'
                                    THEN split_part(dedup_key, ':', 2)::bigint
                                WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\\.0+$'
                                    THEN (split_part(dedup_key, ':', 2)::numeric)::bigint
                                ELSE NULL
                            END
                      ) = %s
                    LIMIT 1
                    """,
                    (str(site_id), int(resource_id)),
                )
                return cur.fetchone() is not None

    def get_active_job_resource_ids(self, *, site_id: str, resource_ids: list[int]) -> set[int]:
        ids = sorted({int(x) for x in (resource_ids or [])})
        if not ids:
            return set()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT COALESCE(
                        CASE
                            WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$'
                                THEN (payload_json->>'idRecurso')::bigint
                            WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$'
                                THEN ((payload_json->>'idRecurso')::numeric)::bigint
                            ELSE NULL
                        END,
                        CASE
                            WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$'
                                THEN split_part(dedup_key, ':', 2)::bigint
                            WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\\.0+$'
                                THEN (split_part(dedup_key, ':', 2)::numeric)::bigint
                            ELSE NULL
                        END
                    ) AS rid
                    FROM jobs
                    WHERE status IN ('queued', 'processing')
                      AND COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') = %s
                      AND COALESCE(
                            CASE
                                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$'
                                    THEN (payload_json->>'idRecurso')::bigint
                                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$'
                                    THEN ((payload_json->>'idRecurso')::numeric)::bigint
                                ELSE NULL
                            END,
                            CASE
                                WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$'
                                    THEN split_part(dedup_key, ':', 2)::bigint
                                WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\\.0+$'
                                    THEN (split_part(dedup_key, ':', 2)::numeric)::bigint
                                ELSE NULL
                            END
                      ) = ANY(%s)
                    """,
                    (str(site_id), ids),
                )
                rows = cur.fetchall()
        return {int(row[0]) for row in rows if row and row[0] is not None}

    def recover_stale_queued_job_for_resource(
        self,
        *,
        site_id: str,
        resource_id: int,
        stale_seconds: int,
        reason_prefix: str = "auto_recovered_stale_queued",
    ) -> dict[str, Any]:
        """
        Cancela un job en estado queued si lleva demasiado tiempo sin arrancar.
        Devuelve metadata de recuperacion para logging.
        """
        threshold = max(60, int(stale_seconds))
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, job_id, status, COALESCE(queued_at, updated_at, created_at) AS anchor_ts
                    FROM jobs
                    WHERE status IN ('queued', 'processing')
                      AND COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') = %s
                      AND COALESCE(
                            CASE
                                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$'
                                    THEN (payload_json->>'idRecurso')::bigint
                                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$'
                                    THEN ((payload_json->>'idRecurso')::numeric)::bigint
                                ELSE NULL
                            END,
                            CASE
                                WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$'
                                    THEN split_part(dedup_key, ':', 2)::bigint
                                WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\\.0+$'
                                    THEN (split_part(dedup_key, ':', 2)::numeric)::bigint
                                ELSE NULL
                            END
                      ) = %s
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (str(site_id), int(resource_id)),
                )
                row = cur.fetchone()
                if not row:
                    return {"recovered": False, "reason": "no_active_job"}

                job_row_id = int(row[0])
                job_id = str(row[1] or "").strip()
                status = str(row[2] or "").strip().lower()
                anchor_ts = row[3]
                if status != "queued":
                    return {
                        "recovered": False,
                        "reason": "active_processing_job",
                        "job_id": job_id,
                        "status": status,
                    }
                if not anchor_ts:
                    return {"recovered": False, "reason": "missing_anchor_ts", "job_id": job_id, "status": status}

                age_seconds = int((datetime.now(timezone.utc) - anchor_ts).total_seconds())
                if age_seconds < threshold:
                    return {
                        "recovered": False,
                        "reason": "not_stale_yet",
                        "job_id": job_id,
                        "status": status,
                        "age_seconds": age_seconds,
                        "threshold_seconds": threshold,
                    }

                recovery_msg = (
                    f"{reason_prefix}: queued_age={age_seconds}s threshold={threshold}s"
                )
                cur.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled',
                        finished_at = COALESCE(finished_at, NOW()),
                        updated_at = NOW(),
                        error_message = CASE
                            WHEN COALESCE(error_message, '') = '' THEN %s
                            ELSE error_message || ' | ' || %s
                        END
                    WHERE id = %s
                      AND status = 'queued'
                    """,
                    (recovery_msg, recovery_msg, job_row_id),
                )
                updated = cur.rowcount > 0
            conn.commit()

        return {
            "recovered": bool(updated),
            "reason": "stale_queued_cancelled" if updated else "lost_race",
            "job_id": job_id,
            "status": status,
            "age_seconds": age_seconds,
            "threshold_seconds": threshold,
        }

    def has_successful_job_for_resource(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM jobs
                    WHERE status IN ('completed', 'succeeded')
                      AND COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') = %s
                      AND COALESCE(
                            CASE
                                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$'
                                    THEN (payload_json->>'idRecurso')::bigint
                                WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$'
                                    THEN ((payload_json->>'idRecurso')::numeric)::bigint
                                ELSE NULL
                            END,
                            CASE
                                WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$'
                                    THEN split_part(dedup_key, ':', 2)::bigint
                                WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\\.0+$'
                                    THEN (split_part(dedup_key, ':', 2)::numeric)::bigint
                                ELSE NULL
                            END
                      ) = %s
                    LIMIT 1
                    """,
                    (str(site_id), int(resource_id)),
                )
                return cur.fetchone() is not None

    def purge_completed_resources_from_operational_tables(
        self,
        *,
        site_id: str | None = None,
    ) -> dict[str, int]:
        site_filter = (site_id or "").strip() or None
        site_expr = self._job_site_expr()
        resource_expr = self._job_resource_expr()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    WITH successful_resources AS (
                        SELECT DISTINCT
                            {site_expr} AS site_id,
                            {resource_expr} AS resource_id
                        FROM jobs
                        WHERE status IN ('completed', 'succeeded')
                          AND {site_expr} <> ''
                          AND {resource_expr} IS NOT NULL
                          AND (%s::text IS NULL OR {site_expr} = %s::text)
                        UNION
                        SELECT DISTINCT
                            btrim(site_id) AS site_id,
                            resource_id::bigint AS resource_id
                        FROM realtime_task_results
                        WHERE status = 'success'
                          AND resource_id IS NOT NULL
                          AND btrim(site_id) <> ''
                          AND (%s::text IS NULL OR btrim(site_id) = %s::text)
                    ),
                    deleted_queue AS (
                        DELETE FROM jobs q
                        USING successful_resources s
                        WHERE q.status IN ('queued', 'processing')
                          AND {site_expr.replace('payload_json', 'q.payload_json').replace('dedup_key', 'q.dedup_key')} = s.site_id
                          AND {resource_expr.replace('payload_json', 'q.payload_json').replace('dedup_key', 'q.dedup_key')} = s.resource_id
                        RETURNING 1
                    ),
                    deleted_blacklist AS (
                        DELETE FROM blocked_resources br
                        USING successful_resources s
                        WHERE br.site_id = s.site_id
                          AND br.resource_id = s.resource_id
                        RETURNING 1
                    ),
                    deleted_pending_auth AS (
                        DELETE FROM pending_authorization_queue pa
                        USING successful_resources s
                        WHERE pa.status = 'pending'
                          AND pa.site_id = s.site_id
                          AND pa.resource_id = s.resource_id
                        RETURNING 1
                    ),
                    deleted_incidents AS (
                        DELETE FROM realtime_incidents ri
                        USING successful_resources s
                        WHERE ri.resource_id IS NOT NULL
                          AND ri.site_id = s.site_id
                          AND ri.resource_id = s.resource_id
                        RETURNING 1
                    )
                    SELECT
                        (SELECT COUNT(*) FROM deleted_queue) AS deleted_queue,
                        (SELECT COUNT(*) FROM deleted_blacklist) AS deleted_blacklist,
                        (SELECT COUNT(*) FROM deleted_pending_auth) AS deleted_pending_auth,
                        (SELECT COUNT(*) FROM deleted_incidents) AS deleted_incidents
                    """,
                    (
                        site_filter,
                        site_filter,
                        site_filter,
                        site_filter,
                    ),
                )
                row = cur.fetchone()
            conn.commit()

        deleted_queue = int(row[0] if row and row[0] is not None else 0)
        deleted_blacklist = int(row[1] if row and row[1] is not None else 0)
        deleted_pending_auth = int(row[2] if row and row[2] is not None else 0)
        deleted_incidents = int(row[3] if row and row[3] is not None else 0)
        return {
            "deleted_queue": deleted_queue,
            "deleted_blacklist": deleted_blacklist,
            "deleted_pending_auth": deleted_pending_auth,
            "deleted_incidents": deleted_incidents,
            "deleted_total": deleted_queue + deleted_blacklist + deleted_pending_auth + deleted_incidents,
        }

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

    def try_acquire_worker_singleton_lock(self) -> bool:
        """Acquire a global DB-level lock so only one worker can run at a time."""
        if self._worker_singleton_lock_conn is not None:
            try:
                with self._worker_singleton_lock_conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return True
            except Exception:
                try:
                    self._worker_singleton_lock_conn.close()
                except Exception:
                    pass
                self._worker_singleton_lock_conn = None

        conn = None
        try:
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (self._worker_singleton_lock_key,))
                row = cur.fetchone()
                acquired = bool(row and row[0])
            if acquired:
                self._worker_singleton_lock_conn = conn
                return True
            conn.close()
            return False
        except Exception as exc:
            self.logger.warning("No se pudo adquirir lock singleton de worker: %s", exc)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            return False

    def release_worker_singleton_lock(self) -> None:
        conn = self._worker_singleton_lock_conn
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (self._worker_singleton_lock_key,))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
            self._worker_singleton_lock_conn = None

    def reconcile_processing_with_worker_runtime(
        self,
        *,
        heartbeat_timeout_seconds: int,
        limit: int,
        site_id: str | None = None,
        resource_id: int | None = None,
    ) -> dict[str, Any]:
        timeout = max(1, int(heartbeat_timeout_seconds))
        scan_limit = max(1, int(limit))
        site_filter = (site_id or "").strip() or None
        rid_filter = int(resource_id) if resource_id is not None else None

        site_expr = "COALESCE(payload_json->>'site_id', NULLIF(split_part(dedup_key, ':', 1), ''), 'unknown')"
        resource_expr = (
            "COALESCE("
            "CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$' THEN (payload_json->>'idRecurso')::bigint END,"
            "CASE WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\\.0+$' THEN ((payload_json->>'idRecurso')::numeric)::bigint END,"
            "CASE WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$' THEN split_part(dedup_key, ':', 2)::bigint END,"
            "CASE WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\\.0+$' THEN (split_part(dedup_key, ':', 2)::numeric)::bigint END"
            ")"
        )

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT worker_id, current_job_id
                    FROM worker_runtime
                    WHERE status = 'online'
                      AND last_heartbeat_at >= NOW() - (%s * INTERVAL '1 second')
                    """,
                    (timeout,),
                )
                alive_worker_ids: set[str] = set()
                alive_current_job_ids: set[str] = set()
                for row in cur.fetchall():
                    if not row:
                        continue
                    worker_value = str(row[0] or "").strip()
                    if worker_value:
                        alive_worker_ids.add(worker_value)
                    current_job_value = str(row[1] or "").strip()
                    if current_job_value:
                        alive_current_job_ids.add(current_job_value)

                clauses = ["status = 'processing'"]
                params: list[Any] = []
                if site_filter:
                    clauses.append(f"{site_expr} = %s")
                    params.append(site_filter)
                if rid_filter is not None:
                    clauses.append(f"{resource_expr} = %s")
                    params.append(rid_filter)
                where_sql = " AND ".join(clauses)

                cur.execute(
                    f"""
                    SELECT
                        id,
                        job_id,
                        {site_expr} AS site_id,
                        {resource_expr} AS resource_id
                    FROM jobs
                    WHERE {where_sql}
                    ORDER BY COALESCE(started_at, queued_at, created_at) ASC, id ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (*params, scan_limit),
                )
                rows = cur.fetchall()
                recovered_items: list[dict[str, Any]] = []

                for row in rows:
                    job_row_id = int(row[0])
                    job_id_value = str(row[1] or "").strip()
                    site_value = str(row[2] or "").strip() or "unknown"
                    resource_value = int(row[3]) if row[3] is not None else None

                    cur.execute(
                        """
                        SELECT worker_id
                        FROM job_attempts
                        WHERE job_id = %s
                        ORDER BY attempt_no DESC, id DESC
                        LIMIT 1
                        """,
                        (job_row_id,),
                    )
                    attempt_row = cur.fetchone()
                    owner_worker_id = str(attempt_row[0]).strip() if (attempt_row and attempt_row[0]) else None

                    keep_processing = bool(owner_worker_id and owner_worker_id in alive_worker_ids)
                    if not keep_processing and job_id_value and job_id_value in alive_current_job_ids:
                        keep_processing = True
                    if keep_processing:
                        continue

                    reason = "missing_job_attempt_or_owner"
                    if owner_worker_id and owner_worker_id not in alive_worker_ids:
                        reason = "owner_worker_offline_or_stale_heartbeat"
                    elif job_id_value and job_id_value not in alive_current_job_ids:
                        reason = "job_not_held_by_alive_worker_runtime"
                    recovery_msg = f"Recovered by UUID-runtime reconciliation: {reason}."

                    cur.execute(
                        """
                        UPDATE jobs
                        SET status = 'queued',
                            queued_at = NOW(),
                            started_at = NULL,
                            finished_at = NULL,
                            updated_at = NOW(),
                            error_message = %s
                        WHERE id = %s
                          AND status = 'processing'
                        """,
                        (recovery_msg, job_row_id),
                    )
                    if cur.rowcount <= 0:
                        continue

                    cur.execute(
                        """
                        UPDATE job_attempts
                        SET status = 'queued',
                            error_message = %s,
                            ended_at = COALESCE(ended_at, NOW())
                        WHERE id = (
                            SELECT id
                            FROM job_attempts
                            WHERE job_id = %s
                            ORDER BY attempt_no DESC, id DESC
                            LIMIT 1
                        )
                        """,
                        (recovery_msg, job_row_id),
                    )
                    recovered_items.append(
                        {
                            "queue_ref": job_row_id,
                            "job_id": job_id_value or None,
                            "site_id": site_value,
                            "resource_id": resource_value,
                            "owner_worker_id": owner_worker_id,
                            "reason": reason,
                        }
                    )
            conn.commit()

        return {
            "alive_workers": len(alive_worker_ids),
            "scanned": len(rows),
            "recovered": len(recovered_items),
            "items": recovered_items,
        }

    # Process runtime control API
    def _normalize_process_name(self, process_name: str) -> str:
        value = str(process_name or "").strip().lower()
        if value not in {"worker", "brain"}:
            raise ValueError("process_name invalido. Usa 'worker' o 'brain'.")
        return value

    def _normalize_desired_state(self, desired_state: str) -> str:
        value = str(desired_state or "").strip().lower()
        if value not in {"running", "stopped"}:
            raise ValueError("desired_state invalido. Usa 'running' o 'stopped'.")
        return value

    def set_process_desired_state(
        self,
        *,
        process_name: str,
        desired_state: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        name = self._normalize_process_name(process_name)
        state = self._normalize_desired_state(desired_state)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO process_runtime_controls (process_name, desired_state, reason, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (process_name) DO UPDATE SET
                        desired_state = EXCLUDED.desired_state,
                        reason = EXCLUDED.reason,
                        updated_at = NOW()
                    """,
                    (name, state, (str(reason).strip() if reason else None)),
                )
            conn.commit()
        return self.get_process_desired_state(process_name=name)

    def get_process_desired_state(self, *, process_name: str) -> dict[str, Any]:
        name = self._normalize_process_name(process_name)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT desired_state, reason, updated_at
                    FROM process_runtime_controls
                    WHERE process_name = %s
                    LIMIT 1
                    """,
                    (name,),
                )
                row = cur.fetchone()
        if not row:
            return {"process_name": name, "desired_state": "running", "reason": None, "updated_at": None}
        return {
            "process_name": name,
            "desired_state": str(row[0] or "running").strip().lower() or "running",
            "reason": row[1],
            "updated_at": row[2].isoformat() if row[2] else None,
        }

    def is_process_enabled(self, *, process_name: str) -> bool:
        state = self.get_process_desired_state(process_name=process_name)
        return str(state.get("desired_state") or "running").strip().lower() != "stopped"

    def list_process_desired_states(self) -> dict[str, dict[str, Any]]:
        base = {
            "worker": {"process_name": "worker", "desired_state": "running", "reason": None, "updated_at": None},
            "brain": {"process_name": "brain", "desired_state": "running", "reason": None, "updated_at": None},
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT process_name, desired_state, reason, updated_at
                    FROM process_runtime_controls
                    """
                )
                rows = cur.fetchall()
        for row in rows:
            name = str(row[0] or "").strip().lower()
            if name not in base:
                continue
            base[name] = {
                "process_name": name,
                "desired_state": str(row[1] or "running").strip().lower() or "running",
                "reason": row[2],
                "updated_at": row[3].isoformat() if row[3] else None,
            }
        return base

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

    def is_site_active(self, *, site_id: str) -> bool:
        site = str(site_id or "").strip()
        if not site:
            return True
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT active
                    FROM organismo_config
                    WHERE site_id = %s
                    LIMIT 1
                    """,
                    (site,),
                )
                row = cur.fetchone()
        if row is None:
            # Si no existe config, no bloqueamos por defecto para no romper sites legacy.
            return True
        return bool(row[0])

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

    def get_paused_resource_ids(self, *, site_id: str, resource_ids: list[int]) -> set[int]:
        ids = sorted({int(x) for x in (resource_ids or [])})
        if not ids:
            return set()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT resource_id
                    FROM resource_processing_pauses
                    WHERE site_id = %s
                      AND resource_id = ANY(%s)
                      AND (expires_at IS NULL OR expires_at > NOW())
                    """,
                    (str(site_id), ids),
                )
                rows = cur.fetchall()
        return {int(row[0]) for row in rows if row and row[0] is not None}

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
