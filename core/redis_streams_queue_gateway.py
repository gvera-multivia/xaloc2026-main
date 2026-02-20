from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from core.queue_gateway import QueueGateway, QueueJob
from core.redis_client import get_redis_client
from shared.queue import RedisStreamsClient


class RedisStreamsQueueGateway(QueueGateway):
    def __init__(self, db: Any):
        self._redis = get_redis_client()
        if self._redis is None:
            raise RuntimeError("Redis Streams requiere cliente Redis válido (REDIS_ENABLED=1 y REDIS_URL).")

        self.db = db
        self.logger = logging.getLogger("redis_streams_queue_gateway")
        self.stream_key = (os.getenv("QUEUE_STREAM_JOBS_KEY") or "jobs").strip() or "jobs"
        self.group = (os.getenv("QUEUE_STREAM_GROUP") or "worker_group").strip() or "worker_group"
        self.dlq_stream = (os.getenv("QUEUE_STREAM_DLQ_KEY") or "dlq:jobs").strip() or "dlq:jobs"
        self.max_attempts_default = int((os.getenv("QUEUE_MAX_ATTEMPTS") or "3").strip() or "3")
        self.dedupe_ttl_seconds = int((os.getenv("QUEUE_DEDUPE_TTL_SECONDS") or "86400").strip() or "86400")
        self.trim_maxlen = int((os.getenv("QUEUE_STREAM_MAXLEN") or "200000").strip() or "200000")
        self.delete_on_ack = (os.getenv("QUEUE_STREAM_DELETE_ON_ACK") or "1").strip().lower() in {"1", "true", "yes", "on"}
        self.streams = RedisStreamsClient(self._redis, logger=self.logger)

    async def _ensure_group(self) -> None:
        await self.streams.ensure_group(stream=self.stream_key, group=self.group)

    async def enqueue(self, *, site_id: str, protocol: Optional[str], payload: dict[str, Any]) -> tuple[bool, str]:
        await self._ensure_group()

        job_id = str(payload.get("job_id") or uuid.uuid4())
        payload["job_id"] = job_id

        resource_id = payload.get("idRecurso")
        try:
            resource_id = int(resource_id) if resource_id is not None else None
        except Exception:
            resource_id = None

        if resource_id is not None:
            dedupe_key = f"dedupe:resource:{site_id}:{resource_id}"
            was_set = await self._redis.set(dedupe_key, job_id, ex=self.dedupe_ttl_seconds, nx=True)
            if not was_set:
                self.logger.info("Redis Streams dedupe evitado: site_id=%s resource_id=%s", site_id, resource_id)
                return False, job_id

        max_attempts = int(payload.get("max_attempts") or self.max_attempts_default)
        message_payload: dict[str, Any] = {
            "job_id": job_id,
            "site_id": site_id,
            "protocol": protocol or "",
            "payload": payload,
            "resource_id": resource_id,
            "attempt": 0,
            "max_attempts": max_attempts,
            "created_at": int(time.time()),
        }
        await self.streams.publish_json(
            stream=self.stream_key,
            payload=message_payload,
            maxlen=self.trim_maxlen,
        )
        self.db.upsert_job_run(
            job_id=job_id,
            site_id=site_id,
            resource_id=resource_id,
            protocol=protocol,
            payload_snapshot=payload,
            state="queued",
            attempt=0,
            max_attempts=max_attempts,
        )
        return True, job_id

    async def reserve(self, *, timeout_seconds: int = 10, worker_id: Optional[str] = None) -> Optional[QueueJob]:
        await self._ensure_group()
        consumer = (worker_id or f"worker-{uuid.uuid4().hex[:12]}").strip()
        message = await self.streams.read_group(
            stream=self.stream_key,
            group=self.group,
            consumer=consumer,
            block_ms=max(1, int(timeout_seconds)) * 1000,
            count=1,
        )
        if message is None:
            return None

        fields = message.fields
        job_id = str(fields.get("job_id") or "").strip()
        site_id = str(fields.get("site_id") or "").strip()
        protocol = str(fields.get("protocol") or "").strip() or None

        payload_raw = fields.get("payload") or "{}"
        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {}
        payload["job_id"] = job_id

        resource_raw = fields.get("resource_id")
        try:
            resource_id = int(resource_raw) if resource_raw not in {None, "", "null"} else None
        except Exception:
            resource_id = None

        attempt = int(str(fields.get("attempt") or "0").strip() or "0")
        max_attempts = int(str(fields.get("max_attempts") or self.max_attempts_default).strip() or str(self.max_attempts_default))

        if job_id:
            status = None
            try:
                status = self.db.get_job_status(job_id=job_id)
            except Exception:
                status = None
            if status in {"cancelled", "completed", "failed", "dead", "succeeded"}:
                await self.streams.ack(stream=self.stream_key, group=self.group, message_id=message.message_id)
                if self.delete_on_ack:
                    await self.streams.delete(stream=self.stream_key, message_id=message.message_id)
                return None

        if site_id and self.db.is_site_processing_paused(site_id=site_id):
            await self.streams.ack(stream=self.stream_key, group=self.group, message_id=message.message_id)
            await self.streams.publish_json(
                stream=self.stream_key,
                payload={
                    "job_id": job_id,
                    "site_id": site_id,
                    "protocol": protocol or "",
                    "payload": payload,
                    "resource_id": resource_id,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "created_at": int(time.time()),
                },
                maxlen=self.trim_maxlen,
            )
            return None

        if site_id and resource_id is not None and self.db.is_resource_processing_paused(site_id=site_id, resource_id=resource_id):
            await self.streams.ack(stream=self.stream_key, group=self.group, message_id=message.message_id)
            await self.streams.publish_json(
                stream=self.stream_key,
                payload={
                    "job_id": job_id,
                    "site_id": site_id,
                    "protocol": protocol or "",
                    "payload": payload,
                    "resource_id": resource_id,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "created_at": int(time.time()),
                },
                maxlen=self.trim_maxlen,
            )
            return None

        self.db.update_job_run_state(
            job_id,
            "processing",
            started=True,
            attempt=attempt,
            worker_id=consumer,
        )
        # Guardar el mensaje id en payload interno para ACK/NACK.
        payload["_stream_message_id"] = message.message_id
        return QueueJob(
            job_id=job_id,
            site_id=site_id,
            protocol=protocol,
            payload=payload,
            resource_id=resource_id,
            attempt=attempt,
            max_attempts=max_attempts,
            queue_ref=None,
        )

    async def ack(self, job: QueueJob, *, result: Optional[dict[str, Any]] = None, screenshot: Optional[str] = None) -> None:
        message_id = str(job.payload.get("_stream_message_id") or "").strip()
        if message_id:
            await self.streams.ack(stream=self.stream_key, group=self.group, message_id=message_id)
            if self.delete_on_ack:
                await self.streams.delete(stream=self.stream_key, message_id=message_id)
        self.db.update_job_run_state(
            job.job_id,
            "completed",
            finished=True,
            result_snapshot=result,
        )

    async def nack(self, job: QueueJob, *, error: str, retryable: bool = False) -> None:
        message_id = str(job.payload.get("_stream_message_id") or "").strip()
        if message_id:
            await self.streams.ack(stream=self.stream_key, group=self.group, message_id=message_id)
            if self.delete_on_ack:
                await self.streams.delete(stream=self.stream_key, message_id=message_id)

        next_attempt = int(job.attempt) + 1
        if retryable and next_attempt < int(job.max_attempts):
            payload_retry = dict(job.payload)
            payload_retry.pop("_stream_message_id", None)
            await self.streams.publish_json(
                stream=self.stream_key,
                payload={
                    "job_id": job.job_id,
                    "site_id": job.site_id,
                    "protocol": job.protocol or "",
                    "payload": payload_retry,
                    "resource_id": job.resource_id,
                    "attempt": next_attempt,
                    "max_attempts": int(job.max_attempts),
                    "last_error": error,
                    "created_at": int(time.time()),
                },
                maxlen=self.trim_maxlen,
            )
            self.db.update_job_run_state(
                job.job_id,
                "queued",
                attempt=next_attempt,
                error_message=error,
            )
            return

        final_state = "dead" if retryable else "failed"
        payload_final = dict(job.payload)
        payload_final.pop("_stream_message_id", None)
        await self.streams.publish_json(
            stream=self.dlq_stream,
            payload={
                "job_id": job.job_id,
                "site_id": job.site_id,
                "protocol": job.protocol or "",
                "payload": payload_final,
                "resource_id": job.resource_id,
                "attempt": next_attempt,
                "max_attempts": int(job.max_attempts),
                "error": error,
                "final_state": final_state,
                "created_at": int(time.time()),
            },
            maxlen=self.trim_maxlen,
        )
        self.db.update_job_run_state(
            job.job_id,
            final_state,
            attempt=next_attempt,
            finished=True,
            error_message=error,
        )

    async def release(self, job: QueueJob, *, reason: str = "") -> None:
        message_id = str(job.payload.get("_stream_message_id") or "").strip()
        if message_id:
            await self.streams.ack(stream=self.stream_key, group=self.group, message_id=message_id)
            if self.delete_on_ack:
                await self.streams.delete(stream=self.stream_key, message_id=message_id)

        payload_release = dict(job.payload)
        payload_release.pop("_stream_message_id", None)
        await self.streams.publish_json(
            stream=self.stream_key,
            payload={
                "job_id": job.job_id,
                "site_id": job.site_id,
                "protocol": job.protocol or "",
                "payload": payload_release,
                "resource_id": job.resource_id,
                "attempt": int(job.attempt),
                "max_attempts": int(job.max_attempts),
                "last_error": (reason or "worker_interrupted_ctrl_c"),
                "created_at": int(time.time()),
            },
            maxlen=self.trim_maxlen,
        )
        self.db.update_job_run_state(
            job.job_id,
            "queued",
            attempt=int(job.attempt),
            error_message=(reason or "worker_interrupted_ctrl_c"),
        )

    def count_ready(self, site_id: str) -> int:
        # Aproximación: mantener criterio por ledger.
        return self.db.count_job_runs(site_id, states=("queued", "processing"))
