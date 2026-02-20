from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

import psycopg

from core.runtime_flags import get_report_pg_dsn


class PgControlPlaneStore:
    def __init__(self, dsn: str, logger: Optional[logging.Logger] = None):
        self.dsn = dsn
        self.logger = logger or logging.getLogger("pg_control_plane_store")

    @classmethod
    def from_env(cls, logger: Optional[logging.Logger] = None) -> "PgControlPlaneStore":
        dsn = get_report_pg_dsn()
        if not dsn:
            raise RuntimeError("REPORT_PG_DSN/PG_DSN es obligatorio para control plane.")
        return cls(dsn=dsn, logger=logger)

    def _conn(self):
        return psycopg.connect(self.dsn)

    @staticmethod
    def build_dedup_key(*, organism_id: str, external_resource_id: Optional[str], job_type: str) -> str:
        return f"{(organism_id or '').strip()}:{(external_resource_id or '').strip() or 'none'}:{(job_type or '').strip()}"

    @staticmethod
    def build_batch_group_key(*, organism_id: str, job_type: str, cert_profile: str, priority: int) -> str:
        return f"{organism_id}:{job_type}:{cert_profile}:{int(priority)}"

    def save_job_draft(
        self,
        *,
        organism_id: str,
        external_resource_id: Optional[str],
        job_type: str,
        cert_profile: str,
        priority: int,
        dedup_key: str,
        normalized_payload: dict[str, Any],
        trace_id: Optional[str],
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        draft_id = str(uuid.uuid4())
        batch_group_key = self.build_batch_group_key(
            organism_id=organism_id,
            job_type=job_type,
            cert_profile=cert_profile,
            priority=priority,
        )
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO job_drafts (
                        draft_id, organism_id, external_resource_id, job_type, cert_profile, priority,
                        dedup_key, status, normalized_payload_json, trace_id, batch_group_key, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, 'validated_pending_batch', %s::jsonb, %s, %s, %s::timestamptz, %s::timestamptz
                    )
                    ON CONFLICT (dedup_key) DO UPDATE SET
                        organism_id = EXCLUDED.organism_id,
                        external_resource_id = EXCLUDED.external_resource_id,
                        job_type = EXCLUDED.job_type,
                        cert_profile = EXCLUDED.cert_profile,
                        priority = EXCLUDED.priority,
                        status = 'validated_pending_batch',
                        normalized_payload_json = EXCLUDED.normalized_payload_json,
                        trace_id = COALESCE(EXCLUDED.trace_id, job_drafts.trace_id),
                        batch_group_key = EXCLUDED.batch_group_key,
                        last_error = NULL,
                        updated_at = EXCLUDED.updated_at
                    RETURNING draft_id, dedup_key, status, batch_group_key
                    """,
                    (
                        draft_id,
                        organism_id,
                        external_resource_id,
                        job_type,
                        cert_profile,
                        int(priority),
                        dedup_key,
                        json.dumps(normalized_payload, ensure_ascii=False),
                        trace_id,
                        batch_group_key,
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return {
            "draft_id": row[0],
            "dedup_key": row[1],
            "status": row[2],
            "batch_group_key": row[3],
        }

    def upsert_job_from_draft(
        self,
        *,
        draft_id: str,
        dedup_key: str,
        priority: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT job_id, status FROM jobs WHERE dedup_key = %s LIMIT 1", (dedup_key,))
                existing = cur.fetchone()
                existing_status = str(existing[1] or "").strip().lower() if existing and existing[1] is not None else None
                if existing and existing[0]:
                    job_id = str(existing[0])
                    if existing_status in {"queued", "processing"}:
                        cur.execute(
                            """
                            UPDATE job_drafts
                            SET status = 'dedup_active',
                                job_id = %s,
                                updated_at = %s::timestamptz
                            WHERE draft_id = %s
                            """,
                            (job_id, now, draft_id),
                        )
                        conn.commit()
                        return {
                            "job_id": job_id,
                            "dispatch": False,
                            "job_status": existing_status,
                        }
                else:
                    cur.execute("SELECT job_id FROM job_drafts WHERE draft_id = %s LIMIT 1", (draft_id,))
                    draft_row = cur.fetchone()
                    if draft_row and draft_row[0]:
                        job_id = str(draft_row[0])
                    else:
                        job_id = str(uuid.uuid4())

                cur.execute(
                    """
                    INSERT INTO jobs (
                        job_id, organism_id, dedup_key, status, priority, payload_json,
                        queued_at, created_at, updated_at
                    )
                    VALUES (%s, NULL, %s, 'queued', %s, %s::jsonb, %s::timestamptz, %s::timestamptz, %s::timestamptz)
                    ON CONFLICT (job_id) DO UPDATE SET
                        dedup_key = EXCLUDED.dedup_key,
                        status = 'queued',
                        priority = EXCLUDED.priority,
                        payload_json = EXCLUDED.payload_json,
                        queued_at = EXCLUDED.queued_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        job_id,
                        dedup_key,
                        int(priority),
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    """
                    UPDATE job_drafts
                    SET status = 'dispatched',
                        job_id = %s,
                        dispatched_at = %s::timestamptz,
                        updated_at = %s::timestamptz
                    WHERE draft_id = %s
                    """,
                    (job_id, now, now, draft_id),
                )
            conn.commit()
        return {
            "job_id": job_id,
            "dispatch": True,
            "job_status": "queued",
        }

    def mark_draft_error(self, *, draft_id: str, error: str) -> None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE job_drafts
                    SET status = 'error',
                        last_error = %s,
                        updated_at = %s::timestamptz
                    WHERE draft_id = %s
                    """,
                    (error, now, draft_id),
                )
            conn.commit()
