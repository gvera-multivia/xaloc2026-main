import os
import uuid
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from core.sqlite_db import SQLiteDatabase


@dataclass
class QueueJob:
    job_id: str
    site_id: str
    protocol: Optional[str]
    payload: dict[str, Any]
    resource_id: Optional[int] = None
    attempt: int = 0
    max_attempts: int = 3
    queue_ref: Optional[int] = None


class QueueGateway(ABC):
    @abstractmethod
    async def enqueue(self, *, site_id: str, protocol: Optional[str], payload: dict[str, Any]) -> tuple[bool, str]:
        raise NotImplementedError

    @abstractmethod
    async def reserve(self, *, timeout_seconds: int = 10) -> Optional[QueueJob]:
        raise NotImplementedError

    @abstractmethod
    async def ack(self, job: QueueJob, *, result: Optional[dict[str, Any]] = None, screenshot: Optional[str] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def nack(self, job: QueueJob, *, error: str, retryable: bool = False) -> None:
        raise NotImplementedError

    @abstractmethod
    def count_ready(self, site_id: str) -> int:
        raise NotImplementedError


class SQLiteQueueGateway(QueueGateway):
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    async def enqueue(self, *, site_id: str, protocol: Optional[str], payload: dict[str, Any]) -> tuple[bool, str]:
        job_id = str(payload.get("job_id") or uuid.uuid4())
        payload["job_id"] = job_id

        resource_id = payload.get("idRecurso")
        try:
            resource_id = int(resource_id) if resource_id is not None else None
        except Exception:
            resource_id = None

        queue_ref = self.db.insert_task(site_id, protocol, payload)
        # Dedupe path returns -1 when the existing row cannot be located.
        enqueued = queue_ref > 0
        self.db.upsert_job_run(
            job_id=job_id,
            site_id=site_id,
            resource_id=resource_id,
            protocol=protocol,
            payload_snapshot=payload,
            state="queued" if enqueued else "created",
            attempt=0,
            max_attempts=3,
        )
        return enqueued, job_id

    async def reserve(self, *, timeout_seconds: int = 10) -> Optional[QueueJob]:
        task = self.db.get_pending_task()
        if not task:
            return None

        task_id, site_id, protocol, payload = task
        job_id = str(payload.get("job_id") or f"sqlite-task-{task_id}")
        payload["job_id"] = job_id
        resource_id = payload.get("idRecurso")
        try:
            resource_id = int(resource_id) if resource_id is not None else None
        except Exception:
            resource_id = None

        run = self.db.get_job_run(job_id)
        attempt = int((run or {}).get("attempt", 0))
        max_attempts = int((run or {}).get("max_attempts", 3))
        self.db.update_job_run_state(job_id, "processing", started=True, attempt=attempt)
        return QueueJob(
            job_id=job_id,
            site_id=site_id,
            protocol=protocol,
            payload=payload,
            resource_id=resource_id,
            attempt=attempt,
            max_attempts=max_attempts,
            queue_ref=task_id,
        )

    async def ack(self, job: QueueJob, *, result: Optional[dict[str, Any]] = None, screenshot: Optional[str] = None) -> None:
        if job.queue_ref is not None:
            self.db.update_task_status(job.queue_ref, "completed", result=result, screenshot=screenshot)
        self.db.update_job_run_state(job.job_id, "completed", finished=True, result_snapshot=result)

    async def nack(self, job: QueueJob, *, error: str, retryable: bool = False) -> None:
        next_attempt = int(job.attempt) + 1
        if retryable and next_attempt < int(job.max_attempts):
            if job.queue_ref is not None:
                self.db.requeue_task(job.queue_ref, error=error)
            self.db.update_job_run_state(
                job.job_id,
                "queued",
                attempt=next_attempt,
                error_message=error,
            )
            return

        if job.queue_ref is not None:
            self.db.update_task_status(job.queue_ref, "failed", error=error)

        final_state = "dead" if retryable else "failed"
        self.db.update_job_run_state(
            job.job_id,
            final_state,
            attempt=next_attempt,
            finished=True,
            error_message=error,
        )

    def count_ready(self, site_id: str) -> int:
        return self.db.count_tasks(site_id)


def build_queue_gateway(*, backend: Optional[str], db: SQLiteDatabase):
    backend_norm = (backend or os.getenv("QUEUE_BACKEND", "sqlite")).strip().lower()
    if backend_norm == "redis":
        from core.redis_queue_gateway import RedisQueueGateway

        return RedisQueueGateway(db=db)
    return SQLiteQueueGateway(db=db)
