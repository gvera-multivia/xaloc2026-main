from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from core.date_normalization import business_today
from core.queue_gateway import QueueGateway, QueueJob


class PgPriorityQueueGateway(QueueGateway):
    """PostgreSQL-backed global priority queue for the worker."""

    def __init__(self, db: Any):
        self.db = db

    def _business_today(self):
        return business_today()

    def _ensure_job_state(self, *, job_id: str, expected: str) -> None:
        actual = str(self.db.get_job_status(job_id=job_id) or "").strip().lower()
        if actual != expected:
            raise RuntimeError(
                f"Persistencia de cola PostgreSQL fallida para job={job_id}: "
                f"estado esperado={expected}, actual={actual or 'missing'}"
            )

    @staticmethod
    def _to_int_like(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except Exception:
            pass
        try:
            converted = float(str(value).strip())
            return int(converted) if converted.is_integer() else None
        except Exception:
            return None

    async def enqueue(self, *, site_id: str, protocol: Optional[str], payload: dict[str, Any]) -> tuple[bool, str]:
        job_id = str(payload.get("job_id") or uuid.uuid4())
        queued_payload = dict(payload)
        queued_payload["job_id"] = job_id
        resource_id = self._to_int_like(queued_payload.get("idRecurso"))
        if resource_id is None:
            resource_id = self._to_int_like(queued_payload.get("external_resource_id"))

        if resource_id is not None and self.db.has_successful_job_for_resource(
            site_id=site_id,
            resource_id=resource_id,
        ):
            return False, job_id
        has_terminal_failed = getattr(self.db, "has_terminal_failed_job_for_resource", None)
        if resource_id is not None and callable(has_terminal_failed) and has_terminal_failed(
            site_id=site_id,
            resource_id=resource_id,
        ):
            return False, job_id
        if resource_id is not None and self.db.has_active_job_for_resource(
            site_id=site_id,
            resource_id=resource_id,
        ):
            return False, job_id

        self.db.upsert_job_run(
            job_id=job_id,
            site_id=site_id,
            resource_id=resource_id,
            protocol=protocol,
            payload_snapshot=queued_payload,
            state="queued",
            attempt=int(queued_payload.get("attempt") or 0),
            max_attempts=int(queued_payload.get("max_attempts") or 3),
        )
        self._ensure_job_state(job_id=job_id, expected="queued")
        return True, job_id

    async def reserve(self, *, timeout_seconds: int = 10, worker_id: Optional[str] = None) -> Optional[QueueJob]:
        consumer = str(worker_id or f"worker-{uuid.uuid4().hex[:12]}").strip()
        deadline = time.monotonic() + max(1, int(timeout_seconds))
        while True:
            reserved = self.db.reserve_next_job(
                business_today=self._business_today(),
                worker_id=consumer,
            )
            if reserved:
                payload = dict(reserved.get("payload") or {})
                job_id = str(reserved.get("job_id") or "").strip()
                payload["job_id"] = job_id
                resource_id = self._to_int_like(reserved.get("resource_id"))
                if resource_id is not None and payload.get("idRecurso") in (None, ""):
                    payload["idRecurso"] = resource_id
                return QueueJob(
                    job_id=job_id,
                    site_id=str(reserved.get("site_id") or payload.get("organism_id") or "").strip(),
                    protocol=str(payload.get("protocol") or payload.get("job_type") or "").strip() or None,
                    payload=payload,
                    resource_id=resource_id,
                    attempt=int(reserved.get("attempt") or 0),
                    max_attempts=int(payload.get("max_attempts") or 3),
                    queue_ref=None,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(0.25, remaining))

    async def ack(self, job: QueueJob, *, result: Optional[dict[str, Any]] = None, screenshot: Optional[str] = None) -> None:
        self.db.update_job_run_state(
            job.job_id,
            "completed",
            attempt=int(job.attempt),
            finished=True,
            result_snapshot=result,
        )
        self._ensure_job_state(job_id=job.job_id, expected="completed")

    async def nack(self, job: QueueJob, *, error: str, retryable: bool = False) -> None:
        next_attempt = int(job.attempt) + 1
        if retryable and next_attempt < int(job.max_attempts):
            self.db.update_job_run_state(
                job.job_id,
                "queued",
                attempt=next_attempt,
                error_message=error,
            )
            self._ensure_job_state(job_id=job.job_id, expected="queued")
            return
        final_state = "dead" if retryable else "failed"
        self.db.update_job_run_state(
            job.job_id,
            final_state,
            attempt=next_attempt,
            finished=True,
            error_message=error,
        )
        self._ensure_job_state(job_id=job.job_id, expected=final_state)

    async def release(self, job: QueueJob, *, reason: str = "") -> None:
        self.db.update_job_run_state(
            job.job_id,
            "queued",
            attempt=int(job.attempt),
            error_message=reason or "worker_interrupted_ctrl_c",
        )
        self._ensure_job_state(job_id=job.job_id, expected="queued")

    def count_ready(self, site_id: str) -> int:
        return self.db.count_job_runs(site_id, states=("queued", "processing", "in_progress"))
