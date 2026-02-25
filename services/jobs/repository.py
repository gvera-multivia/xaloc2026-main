from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import psycopg

from core.runtime_flags import get_report_pg_dsn


@dataclass
class JobsRepository:
    dsn: str

    @classmethod
    def from_env(cls) -> "JobsRepository":
        dsn = get_report_pg_dsn()
        if not dsn:
            raise RuntimeError("REPORT_PG_DSN/PG_DSN no configurado para jobs-service.")
        return cls(dsn=dsn)

    def _conn(self):
        return psycopg.connect(self.dsn)

    @staticmethod
    def _dedup_key(job_id: str, dedup_key: Optional[str]) -> str:
        return (dedup_key or "").strip() or f"job:{job_id}"

    def create_or_update_job(
        self,
        *,
        job_id: str,
        status: str,
        payload: dict[str, Any],
        dedup_key: Optional[str] = None,
        priority: int = 100,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        dedup = self._dedup_key(job_id, dedup_key)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO jobs (
                        job_id, organism_id, dedup_key, status, priority,
                        payload_json, created_at, updated_at
                    )
                    VALUES (%s, NULL, %s, %s, %s, %s::jsonb, %s::timestamptz, %s::timestamptz)
                    ON CONFLICT (job_id) DO UPDATE SET
                        dedup_key = EXCLUDED.dedup_key,
                        status = EXCLUDED.status,
                        priority = EXCLUDED.priority,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING id, job_id, dedup_key, status, priority, payload_json, queued_at, started_at, finished_at, created_at, updated_at
                    """,
                    (
                        str(job_id),
                        dedup,
                        str(status),
                        int(priority),
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return self._row_to_dict(row)

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, job_id, dedup_key, status, priority, payload_json, result_json,
                           error_message, queued_at, started_at, finished_at, created_at, updated_at
                    FROM jobs
                    WHERE job_id = %s
                    LIMIT 1
                    """,
                    (str(job_id),),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def transition_job(
        self,
        *,
        job_id: str,
        status: str,
        error_message: Optional[str] = None,
        result: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE jobs
                    SET status = %s,
                        error_message = CASE WHEN %s IS NOT NULL THEN %s ELSE error_message END,
                        result_json = CASE WHEN %s::jsonb IS NOT NULL THEN %s::jsonb ELSE result_json END,
                        queued_at = CASE WHEN %s = 'queued' THEN %s::timestamptz ELSE queued_at END,
                        started_at = CASE WHEN %s = 'in_progress' THEN %s::timestamptz ELSE started_at END,
                        finished_at = CASE WHEN %s IN ('succeeded','failed','dead_letter','cancelled') THEN %s::timestamptz ELSE finished_at END,
                        updated_at = %s::timestamptz
                    WHERE job_id = %s
                    RETURNING id, job_id, dedup_key, status, priority, payload_json, result_json,
                              error_message, queued_at, started_at, finished_at, created_at, updated_at
                    """,
                    (
                        str(status),
                        error_message,
                        error_message,
                        json.dumps(result, ensure_ascii=False) if result is not None else None,
                        json.dumps(result, ensure_ascii=False) if result is not None else None,
                        str(status),
                        now,
                        str(status),
                        now,
                        str(status),
                        now,
                        now,
                        str(job_id),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            return None
        return self._row_to_dict(row)

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0],
            "job_id": row[1],
            "dedup_key": row[2],
            "status": row[3],
            "priority": row[4],
            "payload_json": row[5],
            "result_json": row[6] if len(row) > 6 else None,
            "error_message": row[7] if len(row) > 7 else None,
            "queued_at": row[8] if len(row) > 8 else None,
            "started_at": row[9] if len(row) > 9 else None,
            "finished_at": row[10] if len(row) > 10 else None,
            "created_at": row[11] if len(row) > 11 else None,
            "updated_at": row[12] if len(row) > 12 else None,
        }

