from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

from core.runtime_flags import get_report_pg_dsn


@dataclass
class PgJobStoreConfig:
    dsn: str
    enabled: bool

    @classmethod
    def from_env(cls) -> "PgJobStoreConfig":
        dsn = get_report_pg_dsn() or ""
        enabled = (os.getenv("JOBS_DUAL_WRITE_ENABLED") or "1").strip().lower() in {"1", "true", "yes", "on"}
        return cls(dsn=dsn, enabled=enabled and bool(dsn))


class PgJobStore:
    def __init__(self, config: PgJobStoreConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger("pg_job_store")

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled and self.config.dsn and psycopg is not None)

    def _conn(self):
        if not self.enabled:
            return None
        return psycopg.connect(self.config.dsn)

    def _dedup_key(
        self,
        *,
        job_id: str,
        site_id: Optional[str] = None,
        resource_id: Optional[int] = None,
        protocol: Optional[str] = None,
    ) -> str:
        s = (site_id or "").strip() or "unknown"
        p = (protocol or "").strip() or "none"
        r = str(resource_id) if resource_id is not None else "none"
        return f"{s}:{r}:{p}:{job_id}"

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
        trace_id: Optional[str] = None,
    ) -> None:
        conn = self._conn()
        if conn is None:
            return
        now = datetime.now().isoformat()
        dedup_key = self._dedup_key(
            job_id=job_id,
            site_id=site_id,
            resource_id=resource_id,
            protocol=protocol,
        )
        payload = dict(payload_snapshot or {})
        payload.setdefault("site_id", site_id)
        if protocol is not None:
            payload.setdefault("protocol", protocol)
        if resource_id is not None and "idRecurso" not in payload:
            payload["idRecurso"] = resource_id
        error_message = None
        if state in {"failed", "dead", "cancelled"}:
            error_message = f"state={state}"

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jobs (
                            job_id, organism_id, dedup_key, status, priority,
                            payload_json, result_json, error_message,
                            queued_at, started_at, finished_at, created_at, updated_at
                        )
                        VALUES (
                            %s, NULL, %s, %s, 100,
                            %s::jsonb, NULL, %s,
                            CASE WHEN %s = 'queued' THEN %s::timestamptz ELSE NULL END,
                            CASE WHEN %s = 'processing' THEN %s::timestamptz ELSE NULL END,
                            CASE WHEN %s IN ('completed','failed','dead','cancelled') THEN %s::timestamptz ELSE NULL END,
                            %s::timestamptz, %s::timestamptz
                        )
                        ON CONFLICT (job_id) DO UPDATE SET
                            dedup_key = EXCLUDED.dedup_key,
                            status = EXCLUDED.status,
                            payload_json = COALESCE(EXCLUDED.payload_json, jobs.payload_json),
                            error_message = CASE
                                WHEN EXCLUDED.status IN ('queued', 'processing', 'completed') THEN NULL
                                ELSE COALESCE(EXCLUDED.error_message, jobs.error_message)
                            END,
                            queued_at = CASE
                                WHEN EXCLUDED.status = 'queued' THEN EXCLUDED.queued_at
                                ELSE jobs.queued_at
                            END,
                            started_at = CASE
                                WHEN EXCLUDED.status = 'queued' THEN NULL
                                WHEN EXCLUDED.status = 'processing' THEN COALESCE(EXCLUDED.started_at, jobs.started_at)
                                ELSE jobs.started_at
                            END,
                            finished_at = CASE
                                WHEN EXCLUDED.status IN ('queued', 'processing') THEN NULL
                                ELSE COALESCE(EXCLUDED.finished_at, jobs.finished_at)
                            END,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            str(job_id),
                            dedup_key,
                            str(state),
                            json.dumps(payload, ensure_ascii=False),
                            error_message,
                            str(state),
                            now,
                            str(state),
                            now,
                            str(state),
                            now,
                            now,
                            now,
                        ),
                    )
        except Exception as exc:
            self.logger.warning("Dual-write upsert_job_run a PG falló (job_id=%s): %s", job_id, exc)
        finally:
            conn.close()

    def update_job_run_state(
        self,
        *,
        job_id: str,
        state: str,
        attempt: Optional[int] = None,
        started: bool = False,
        finished: bool = False,
        error_message: Optional[str] = None,
        result_snapshot: Optional[dict[str, Any]] = None,
        worker_id: Optional[str] = None,
    ) -> None:
        conn = self._conn()
        if conn is None:
            return
        now = datetime.now().isoformat()

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jobs (
                            job_id, organism_id, dedup_key, status, priority,
                            payload_json, result_json, error_message, created_at, updated_at
                        )
                        VALUES (%s, NULL, %s, %s, 100, '{}'::jsonb, NULL, %s, %s::timestamptz, %s::timestamptz)
                        ON CONFLICT (job_id) DO NOTHING
                        """,
                        (
                            str(job_id),
                            self._dedup_key(job_id=str(job_id)),
                            str(state),
                            error_message,
                            now,
                            now,
                        ),
                    )
                    cur.execute(
                        """
                        UPDATE jobs
                        SET status = %s,
                            result_json = CASE WHEN %s::jsonb IS NOT NULL THEN %s::jsonb ELSE result_json END,
                            error_message = CASE
                                WHEN %s IN ('queued', 'processing', 'completed') THEN NULL
                                WHEN %s::text IS NOT NULL THEN %s::text
                                ELSE error_message
                            END,
                            queued_at = CASE WHEN %s = 'queued' THEN %s::timestamptz ELSE queued_at END,
                            started_at = CASE
                                WHEN %s = 'queued' THEN NULL
                                WHEN %s THEN %s::timestamptz
                                ELSE started_at
                            END,
                            finished_at = CASE
                                WHEN %s IN ('queued', 'processing') THEN NULL
                                WHEN %s THEN %s::timestamptz
                                ELSE finished_at
                            END,
                            updated_at = %s::timestamptz
                        WHERE job_id = %s
                        """,
                        (
                            str(state),
                            json.dumps(result_snapshot, ensure_ascii=False) if result_snapshot is not None else None,
                            json.dumps(result_snapshot, ensure_ascii=False) if result_snapshot is not None else None,
                            str(state),
                            error_message,
                            error_message,
                            str(state),
                            now,
                            str(state),
                            bool(started),
                            now,
                            str(state),
                            bool(finished),
                            now,
                            now,
                            str(job_id),
                        ),
                    )
                    if attempt is not None:
                        cur.execute("SELECT id FROM jobs WHERE job_id = %s", (str(job_id),))
                        row = cur.fetchone()
                        if row and row[0] is not None:
                            cur.execute(
                                """
                                INSERT INTO job_attempts (
                                    job_id, attempt_no, worker_id, status, error_message, started_at, ended_at
                                ) VALUES (
                                    %s, %s, %s, %s, %s,
                                    CASE WHEN %s THEN %s::timestamptz ELSE NULL END,
                                    CASE WHEN %s THEN %s::timestamptz ELSE NULL END
                                )
                                ON CONFLICT (job_id, attempt_no) DO UPDATE SET
                                    worker_id = COALESCE(EXCLUDED.worker_id, job_attempts.worker_id),
                                    status = EXCLUDED.status,
                                    error_message = COALESCE(EXCLUDED.error_message, job_attempts.error_message),
                                    started_at = COALESCE(EXCLUDED.started_at, job_attempts.started_at),
                                    ended_at = COALESCE(EXCLUDED.ended_at, job_attempts.ended_at)
                                """,
                                (
                                    int(row[0]),
                                    int(attempt),
                                    worker_id,
                                    str(state),
                                    error_message,
                                    bool(started),
                                    now,
                                    bool(finished),
                                    now,
                                ),
                            )
        except Exception as exc:
            self.logger.warning("Dual-write update_job_run_state a PG falló (job_id=%s): %s", job_id, exc)
        finally:
            conn.close()


def build_pg_job_store(logger: Optional[logging.Logger] = None) -> PgJobStore:
    return PgJobStore(PgJobStoreConfig.from_env(), logger=logger)
