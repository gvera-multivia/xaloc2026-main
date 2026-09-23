import asyncio

from services.batcher_dispatcher.app import BatcherDispatcherService, PendingValidated
from shared.queue.redis_streams import RedisStreamMessage


class FakeStreams:
    def __init__(self):
        self.published = []
        self.acked = []

    async def publish_json(self, **kwargs):
        self.published.append(kwargs)
        return "1-0"

    async def ack(self, **kwargs):
        self.acked.append(kwargs)
        return 1


class FakeStore:
    def upsert_job_from_draft(self, **kwargs):
        return {"job_id": "job-1", "dispatch": True, "job_status": "queued"}

    @staticmethod
    def build_dedup_key(**kwargs):
        return "madrid:123:P1"


def _service(queue_mode):
    service = object.__new__(BatcherDispatcherService)
    service.queue_mode = queue_mode
    service.pending = [
        PendingValidated(
            message=RedisStreamMessage(stream="validated", message_id="1-0", fields={}),
            payload={
                "job_draft_id": "draft-1",
                "organism_id": "madrid",
                "job_type": "P1",
                "cert_profile": "default",
                "priority": 100,
                "dedup_key": "madrid:123:P1",
                "trace_id": "trace-1",
                "normalized_payload": {
                    "idRecurso": 123,
                    "external_resource_id": "123",
                    "fecpres": "2026-09-22",
                },
            },
            arrived_at=1.0,
        )
    ]
    service.last_flush = 0.0
    service.streams = FakeStreams()
    service.store = FakeStore()
    service.jobs_stream = "jobs"
    service.validated_stream = "validated"
    service.dlq_validated = "dlq:validated"
    service.group = "batcher-group"
    service.trim_maxlen = 100
    return service


def test_postgres_priority_persists_and_acks_without_xadd_to_jobs():
    service = _service("postgres_priority")

    asyncio.run(service._flush())

    assert service.streams.published == []
    assert service.streams.acked == [
        {"stream": "validated", "group": "batcher-group", "message_id": "1-0"}
    ]


def test_redis_streams_rollback_still_publishes_to_jobs():
    service = _service("redis_streams")

    asyncio.run(service._flush())

    assert len(service.streams.published) == 1
    assert service.streams.published[0]["stream"] == "jobs"
