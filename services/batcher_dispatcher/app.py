from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from dotenv import load_dotenv

from core.pg_control_plane_store import PgControlPlaneStore
from core.redis_client import get_redis_client
from shared.queue import RedisStreamsClient, RedisStreamMessage

load_dotenv()
logger = logging.getLogger("batcher_dispatcher_service")


@dataclass
class PendingValidated:
    message: RedisStreamMessage
    payload: dict[str, Any]
    arrived_at: float


class BatcherDispatcherService:
    def __init__(self):
        redis = get_redis_client()
        if redis is None:
            raise RuntimeError("Redis requerido para batcher-dispatcher-service.")
        self.streams = RedisStreamsClient(redis, logger=logger)
        self.store = PgControlPlaneStore.from_env(logger=logger)

        self.validated_stream = (os.getenv("VALIDATED_STREAM_KEY") or "validated").strip() or "validated"
        self.jobs_stream = (os.getenv("QUEUE_STREAM_JOBS_KEY") or "jobs").strip() or "jobs"
        self.dlq_validated = (os.getenv("DLQ_VALIDATED_STREAM_KEY") or "dlq:validated").strip() or "dlq:validated"
        self.group = (os.getenv("BATCHER_STREAM_GROUP") or "batcher_group").strip() or "batcher_group"
        self.consumer = (os.getenv("BATCHER_CONSUMER_NAME") or f"batcher-{uuid.uuid4().hex[:8]}").strip()

        self.window_seconds = int((os.getenv("BATCH_WINDOW_SECONDS") or "30").strip() or "30")
        self.max_batch_size = int((os.getenv("BATCH_MAX_SIZE") or "200").strip() or "200")
        self.trim_maxlen = int((os.getenv("QUEUE_STREAM_MAXLEN") or "200000").strip() or "200000")
        self.pending: list[PendingValidated] = []
        self.last_flush = time.monotonic()

    @staticmethod
    def _safe_json(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value))
        except Exception:
            return default

    @staticmethod
    def _normalize_id_recurso(normalized_payload: dict[str, Any]) -> Any:
        value = normalized_payload.get("idRecurso")
        if value is None or str(value).strip() == "":
            value = normalized_payload.get("external_resource_id")
        if value is None or str(value).strip() == "":
            value = normalized_payload.get("resource_id")
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return int(text)
        except Exception:
            return text

    @staticmethod
    def _parse_fecpres(value: Any) -> date | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except Exception:
            return None

    @classmethod
    def _pending_priority_key(cls, item: PendingValidated) -> tuple[int, date, int, float]:
        payload = item.payload.get("normalized_payload") or {}
        fecpres = cls._parse_fecpres(payload.get("fecpres"))
        # 1) con fecpres valido primero, 2) fecha mas proxima primero.
        # Si no hay fecpres, conserva prioridad declarada y orden de llegada.
        if fecpres is not None:
            return (0, fecpres, int(item.payload.get("priority") or 100), item.arrived_at)
        return (1, date.max, int(item.payload.get("priority") or 100), item.arrived_at)

    async def _consume_once(self) -> bool:
        await self.streams.ensure_group(stream=self.validated_stream, group=self.group)
        msg = await self.streams.read_group(
            stream=self.validated_stream,
            group=self.group,
            consumer=self.consumer,
            block_ms=int((os.getenv("BATCHER_BLOCK_MS") or "2000").strip() or "2000"),
            count=1,
        )
        if msg is None:
            return False
        payload = {
            "job_draft_id": str(msg.fields.get("job_draft_id") or "").strip(),
            "organism_id": str(msg.fields.get("organism_id") or "").strip(),
            "job_type": str(msg.fields.get("job_type") or "").strip(),
            "cert_profile": str(msg.fields.get("cert_profile") or "").strip() or "default",
            "priority": int(str(msg.fields.get("priority") or "100").strip() or "100"),
            "dedup_key": str(msg.fields.get("dedup_key") or "").strip(),
            "trace_id": str(msg.fields.get("trace_id") or "").strip() or str(uuid.uuid4()),
            "normalized_payload": self._safe_json(msg.fields.get("normalized_payload"), {}),
        }
        self.pending.append(PendingValidated(message=msg, payload=payload, arrived_at=time.monotonic()))
        return True

    def _should_flush(self) -> bool:
        if not self.pending:
            return False
        if len(self.pending) >= self.max_batch_size:
            return True
        return (time.monotonic() - self.last_flush) >= self.window_seconds

    async def _flush(self) -> None:
        if not self.pending:
            return
        batch = sorted(self.pending, key=self._pending_priority_key)
        self.pending = []
        self.last_flush = time.monotonic()
        for item in batch:
            msg = item.message
            p = item.payload
            draft_id = p["job_draft_id"]
            try:
                if not draft_id:
                    raise ValueError("validated sin job_draft_id")
                normalized_payload = p["normalized_payload"]
                dedup_key = p["dedup_key"] or self.store.build_dedup_key(
                    organism_id=p["organism_id"],
                    external_resource_id=str(normalized_payload.get("external_resource_id") or ""),
                    job_type=p["job_type"],
                )
                upsert_result = self.store.upsert_job_from_draft(
                    draft_id=draft_id,
                    dedup_key=dedup_key,
                    priority=int(p["priority"]),
                    payload=normalized_payload,
                )
                job_id = str(upsert_result.get("job_id") or "").strip()
                if not job_id:
                    raise ValueError("upsert_job_from_draft devolvio job_id vacio")
                if not bool(upsert_result.get("dispatch", True)):
                    logger.info(
                        "[batcher-dispatcher] skip dispatch dedup activo: job_id=%s dedup_key=%s status=%s",
                        job_id,
                        dedup_key,
                        str(upsert_result.get("job_status") or "").strip() or "unknown",
                    )
                    await self.streams.ack(stream=self.validated_stream, group=self.group, message_id=msg.message_id)
                    continue
                id_recurso = self._normalize_id_recurso(normalized_payload)
                if id_recurso is not None:
                    normalized_payload["idRecurso"] = id_recurso
                job_payload = {
                    "job_id": job_id,
                    "attempt": int(normalized_payload.get("attempt") or 0),
                    "max_attempts": int(normalized_payload.get("max_attempts") or 3),
                    "execution_plan": {
                        "organism_id": p["organism_id"],
                        "job_type": p["job_type"],
                        "cert_profile": p["cert_profile"],
                        "steps": normalized_payload.get("steps") or [],
                    },
                    "artifacts_base_path": f"/data/artifacts/{job_id}",
                    "trace_id": p["trace_id"],
                    "site_id": p["organism_id"],
                    "protocol": normalized_payload.get("protocol") or normalized_payload.get("job_type") or "",
                    "payload": normalized_payload,
                    "resource_id": id_recurso,
                }
                await self.streams.publish_json(
                    stream=self.jobs_stream,
                    payload=job_payload,
                    maxlen=self.trim_maxlen,
                )
                await self.streams.ack(stream=self.validated_stream, group=self.group, message_id=msg.message_id)
            except Exception as exc:
                logger.exception("Error despachando validated %s: %s", msg.message_id, exc)
                if draft_id:
                    try:
                        self.store.mark_draft_error(draft_id=draft_id, error=str(exc))
                    except Exception:
                        pass
                await self.streams.publish_json(
                    stream=self.dlq_validated,
                    payload={
                        "source_message_id": msg.message_id,
                        "error": str(exc),
                        "payload": p,
                    },
                    maxlen=int((os.getenv("DLQ_STREAM_MAXLEN") or "200000").strip() or "200000"),
                )
                await self.streams.ack(stream=self.validated_stream, group=self.group, message_id=msg.message_id)

    async def run_forever(self) -> None:
        shutdown = asyncio.Event()

        def _signal_handler():
            shutdown.set()

        loop = asyncio.get_running_loop()
        if os.name != "nt":
            try:
                loop.add_signal_handler(signal.SIGTERM, _signal_handler)
                loop.add_signal_handler(signal.SIGINT, _signal_handler)
            except NotImplementedError:
                pass

        while not shutdown.is_set():
            consumed = await self._consume_once()
            if self._should_flush():
                await self._flush()
            if not consumed:
                await asyncio.sleep(0.1)

        # flush final
        await self._flush()


async def _main_async() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [batcher-dispatcher] %(levelname)s %(message)s")
    svc = BatcherDispatcherService()
    await svc.run_forever()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
