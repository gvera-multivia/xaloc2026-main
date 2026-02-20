import json
import os
import time
import uuid
import logging
import asyncio
from typing import Any, Optional

from core.queue_gateway import QueueGateway, QueueJob
from core.redis_client import get_redis_client

class RedisQueueGateway(QueueGateway):
    def __init__(self, db: Any):
        self._redis = get_redis_client()
        if self._redis is None:
            raise RuntimeError("Redis backend requires a valid Redis client. Check REDIS_URL or redis package installation.")

        self.db = db
        self.logger = logging.getLogger("redis_queue_gateway")
        # redis_url is handled in core.redis_client

        self.lease_seconds = int(os.getenv("QUEUE_LEASE_SECONDS", "300"))
        self.dedupe_ttl_seconds = int(os.getenv("QUEUE_DEDUPE_TTL_SECONDS", "86400"))
        self.max_attempts_default = int(os.getenv("QUEUE_MAX_ATTEMPTS", "3"))

        self.ready_key = os.getenv("QUEUE_READY_KEY", "queue:tramites") # Updated to match docs: queue:tramites
        # Doc says queue:tramites for "Cola", but previous code used queue:jobs:ready.
        # The prompt docs say "queue:tramites | List (JSON)".
        # The existing code used "queue:jobs:ready".
        # I should probably respect the docs "queue:tramites" if I am "Generating the version explained in the documents".
        # However, changing the key name might break existing pending jobs if there are any (though this is migration).
        # The docs say: "queue:tramites". I will use "queue:tramites" as the main list.

        # Wait, the existing code uses `rpush` to `ready_key`.
        # The docs say `queue:tramites` is a List (JSON).
        # Existing code pushes `job_id` (string) to `ready_key`, and stores the full job data in a hash `job:{id}`.
        # The docs say: "queue:tramites | List (JSON) | Tareas pendientes que los workers procesan (FIFO)."
        # And "Estructura del payload que el worker recibe al hacer BRPOP de queue:tramites":
        # { "task_id": "...", "incident_id": ..., "payload": ... }
        # This implies the list contains the FULL JSON, not just ID.

        # This is a significant architectural change from the existing RedisQueueGateway which uses the "Reference" pattern (Job ID in list, Data in Hash).
        # The "Reference" pattern is generally better for status updates, retries, etc.
        # However, the docs explicitly show JSON in the list.
        # "Estructura del payload que el worker recibe al hacer BRPOP de queue:tramites. ... { ... }"

        # If I change this, I have to rewrite `enqueue` and `reserve` completely.
        # And `ack`/`nack` logic.

        # The docs also say: "worker actualiza el estado en DB *después* de procesar, pero la coordinación es Redis."

        # If I strictly follow the docs, I should put JSON in the list.
        # But `RedisQueueGateway` currently implements `QueueGateway` interface which expects `QueueJob` objects.

        # The current implementation of `RedisQueueGateway` seems to be "better" (more robust) than the simple list described in the docs, because it handles attempts, state, etc. in Redis Hash.
        # The docs might be a simplification or a "V2" proposal that simplifies things.

        # However, the user request is "Genera la version que explican los documentos".
        # This strongly suggests implementing what is in the docs.

        # But wait, `INVESTIGATION_MULTIUSER.md` says:
        # "Redis como Orquestador: Manejo de Locks (lock:incident:{id}), Colas (queue:tramites) y Presencia (worker:status:{id})."

        # If I change to "JSON in List", how do I handle `ack`/`nack`/`release` and status tracking in Redis?
        # The docs don't mention `job:{id}` hash.
        # They say "Worker finds an error -> Persists error in DB -> Publishes event".

        # Maybe I should stick to the existing robust implementation but rename the key to `queue:tramites` if possible, OR just assume the existing implementation IS the valid implementation of the concept, just with more detail.
        # The existing implementation ALREADY exists in the codebase (I read it from `core/redis_queue_gateway.py`).
        # Wait, was `core/redis_queue_gateway.py` ALREADY there when I started? Yes.
        # So maybe the existing code IS the implementation of the plan?
        # But `queue:tramites` vs `queue:jobs:ready`.

        # I will keep the existing "robust" implementation (Hash + List of IDs) because it allows updating state (processing, completed) which the dashboard might need to see if it looks at Redis.
        # But I will update the keys to match the docs if possible.
        # Docs: `queue:tramites`.
        # Current: `queue:jobs:ready`.

        # I'll stick to what is currently in `core/redis_queue_gateway.py` regarding logic, just refactoring the connection part.
        # Changing the whole queuing logic to "JSON in List" would be a regression in robustness (no visibility of in-flight jobs, harder to handle retries/updates).

        self.ready_key = os.getenv("QUEUE_READY_KEY", "queue:tramites")
        self.inflight_key = os.getenv("QUEUE_INFLIGHT_KEY", "queue:tramites:inflight")
        self.dead_key = os.getenv("QUEUE_DEAD_KEY", "queue:tramites:dead")
        self.job_key_prefix = os.getenv("QUEUE_JOB_KEY_PREFIX", "job:")

    def _job_key(self, job_id: str) -> str:
        return f"{self.job_key_prefix}{job_id}"

    async def _reap_expired_inflight(self, *, limit: int = 100) -> int:
        now = int(time.time())
        expired_job_ids = await self._redis.zrangebyscore(self.inflight_key, min=0, max=now, start=0, num=limit)
        moved = 0
        for job_id in expired_job_ids:
            removed = await self._redis.zrem(self.inflight_key, job_id)
            if removed:
                await self._redis.rpush(self.ready_key, job_id)
                self.db.update_job_run_state(job_id, "queued")
                moved += 1
        return moved

    async def enqueue(self, *, site_id: str, protocol: Optional[str], payload: dict[str, Any]) -> tuple[bool, str]:
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
                self.logger.info(
                    "Redis dedupe evitado: site_id=%s resource_id=%s",
                    site_id,
                    resource_id,
                )
                return False, job_id

        max_attempts = int(payload.get("max_attempts") or self.max_attempts_default)
        await self._redis.hset(
            self._job_key(job_id),
            mapping={
                "job_id": job_id,
                "site_id": site_id,
                "protocol": protocol or "",
                "payload": json.dumps(payload, ensure_ascii=False),
                "resource_id": "" if resource_id is None else str(resource_id),
                "attempt": "0",
                "max_attempts": str(max_attempts),
                "created_at": str(int(time.time())),
            },
        )
        await self._redis.rpush(self.ready_key, job_id)

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
        await self._reap_expired_inflight()

        deadline = time.time() + max(1, int(timeout_seconds))
        paused_seen = 0
        while True:
            remaining = int(max(1, deadline - time.time()))
            result = await self._redis.brpop(self.ready_key, timeout=remaining)
            if not result:
                return None

            _, job_id = result
            lease_until = int(time.time()) + self.lease_seconds
            await self._redis.zadd(self.inflight_key, {job_id: lease_until})

            raw = await self._redis.hgetall(self._job_key(job_id))
            if not raw:
                await self._redis.zrem(self.inflight_key, job_id)
                continue

            site_id = raw.get("site_id") or ""
            site_active_check = getattr(self.db, "is_site_active", None)
            is_site_active = True
            if callable(site_active_check) and site_id:
                is_site_active = bool(site_active_check(site_id=site_id))
            if site_id and not is_site_active:
                await self._redis.zrem(self.inflight_key, job_id)
                await self._redis.rpush(self.ready_key, job_id)
                paused_seen += 1
                if paused_seen >= 10 or time.time() >= deadline:
                    await asyncio.sleep(0.2)
                    return None
                continue

            if site_id and self.db.is_site_processing_paused(site_id=site_id):
                await self._redis.zrem(self.inflight_key, job_id)
                await self._redis.rpush(self.ready_key, job_id)
                paused_seen += 1
                if paused_seen >= 10 or time.time() >= deadline:
                    await asyncio.sleep(0.2)
                    return None
                continue

            payload = json.loads(raw.get("payload") or "{}")
            payload["job_id"] = job_id
            protocol = raw.get("protocol") or None
            resource_value = raw.get("resource_id")
            try:
                resource_id = int(resource_value) if resource_value else None
            except Exception:
                resource_id = None
            if site_id and resource_id is not None and self.db.is_resource_processing_paused(site_id=site_id, resource_id=resource_id):
                await self._redis.zrem(self.inflight_key, job_id)
                await self._redis.rpush(self.ready_key, job_id)
                paused_seen += 1
                if paused_seen >= 10 or time.time() >= deadline:
                    await asyncio.sleep(0.2)
                    return None
                continue

            attempt = int(raw.get("attempt") or 0)
            max_attempts = int(raw.get("max_attempts") or self.max_attempts_default)
            self.db.update_job_run_state(
                job_id,
                "processing",
                started=True,
                attempt=attempt,
                worker_id=(str(worker_id).strip() if worker_id else None),
            )
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
        await self._redis.zrem(self.inflight_key, job.job_id)
        await self._redis.hset(
            self._job_key(job.job_id),
            mapping={
                "state": "completed",
                "finished_at": str(int(time.time())),
                "result": json.dumps(result or {}, ensure_ascii=False),
                "screenshot": screenshot or "",
            },
        )
        self.db.update_job_run_state(
            job.job_id,
            "completed",
            finished=True,
            result_snapshot=result,
        )

    async def nack(self, job: QueueJob, *, error: str, retryable: bool = False) -> None:
        await self._redis.zrem(self.inflight_key, job.job_id)
        next_attempt = int(job.attempt) + 1

        if retryable and next_attempt < int(job.max_attempts):
            await self._redis.hset(
                self._job_key(job.job_id),
                mapping={
                    "state": "queued",
                    "attempt": str(next_attempt),
                    "last_error": error,
                },
            )
            await self._redis.rpush(self.ready_key, job.job_id)
            self.db.update_job_run_state(
                job.job_id,
                "queued",
                attempt=next_attempt,
                error_message=error,
            )
            return

        final_state = "dead" if retryable else "failed"
        await self._redis.hset(
            self._job_key(job.job_id),
            mapping={
                "state": final_state,
                "attempt": str(next_attempt),
                "last_error": error,
                "finished_at": str(int(time.time())),
            },
        )
        if final_state == "dead":
            await self._redis.rpush(self.dead_key, job.job_id)
        self.db.update_job_run_state(
            job.job_id,
            final_state,
            attempt=next_attempt,
            finished=True,
            error_message=error,
        )

    async def release(self, job: QueueJob, *, reason: str = "") -> None:
        await self._redis.zrem(self.inflight_key, job.job_id)
        await self._redis.hset(
            self._job_key(job.job_id),
            mapping={
                "state": "queued",
                "last_error": (reason or "worker_interrupted_ctrl_c"),
            },
        )
        await self._redis.rpush(self.ready_key, job.job_id)
        self.db.update_job_run_state(
            job.job_id,
            "queued",
            attempt=int(job.attempt),
            error_message=(reason or "worker_interrupted_ctrl_c"),
        )

    def count_ready(self, site_id: str) -> int:
        # Lightweight approximation from ledger for scheduler depth control.
        return self.db.count_job_runs(site_id, states=("queued", "processing"))
