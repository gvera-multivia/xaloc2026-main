import asyncio
from datetime import date

from core.pg_priority_queue_gateway import PgPriorityQueueGateway
from core.queue_gateway import build_queue_gateway


class FakeRuntimeStore:
    def __init__(self):
        self.reservations = []
        self.state_updates = []
        self.enqueue_calls = []
        self.next_job = None
        self.active = False
        self.statuses = {}

    def reserve_next_job(self, *, business_today, worker_id):
        self.reservations.append((business_today, worker_id))
        job, self.next_job = self.next_job, None
        return job

    def update_job_run_state(self, job_id, state, **kwargs):
        self.state_updates.append((job_id, state, kwargs))
        self.statuses[job_id] = state

    def upsert_job_run(self, **kwargs):
        self.enqueue_calls.append(kwargs)
        self.statuses[kwargs["job_id"]] = kwargs["state"]

    def get_job_status(self, *, job_id):
        return self.statuses.get(job_id)

    def has_successful_job_for_resource(self, **kwargs):
        return False

    def has_active_job_for_resource(self, **kwargs):
        return self.active

    def count_job_runs(self, site_id, states):
        return 4


def test_build_queue_gateway_selects_postgres_priority():
    gateway = build_queue_gateway(backend="postgres_priority", db=FakeRuntimeStore())

    assert isinstance(gateway, PgPriorityQueueGateway)


def test_reserve_uses_business_date_and_maps_payload():
    db = FakeRuntimeStore()
    db.next_job = {
        "job_id": "job-1",
        "site_id": "madrid",
        "resource_id": 123,
        "payload": {"job_type": "P2", "max_attempts": 5},
        "attempt": 2,
    }
    gateway = PgPriorityQueueGateway(db)
    gateway._business_today = lambda: date(2026, 9, 22)

    job = asyncio.run(gateway.reserve(timeout_seconds=1, worker_id="worker-a"))

    assert db.reservations == [(date(2026, 9, 22), "worker-a")]
    assert job is not None
    assert job.job_id == "job-1"
    assert job.site_id == "madrid"
    assert job.resource_id == 123
    assert job.protocol == "P2"
    assert job.attempt == 2
    assert job.max_attempts == 5
    assert job.payload["idRecurso"] == 123


def test_retry_and_release_return_job_to_postgres_queue():
    db = FakeRuntimeStore()
    gateway = PgPriorityQueueGateway(db)
    job = asyncio.run(_reserve_fixture(gateway, db))

    asyncio.run(gateway.nack(job, error="temporal", retryable=True))
    asyncio.run(gateway.release(job, reason="shutdown"))

    assert db.state_updates[0] == (
        "job-2",
        "queued",
        {"attempt": 1, "error_message": "temporal"},
    )
    assert db.state_updates[1] == (
        "job-2",
        "queued",
        {"attempt": 0, "error_message": "shutdown"},
    )


def test_enqueue_skips_resource_with_active_job():
    db = FakeRuntimeStore()
    db.active = True
    gateway = PgPriorityQueueGateway(db)

    enqueued, job_id = asyncio.run(
        gateway.enqueue(
            site_id="madrid",
            protocol="P1",
            payload={"idRecurso": 123, "fecpres": "2026-09-22"},
        )
    )

    assert enqueued is False
    assert job_id
    assert db.enqueue_calls == []


def test_enqueue_rejects_resource_with_active_postgres_job():
    db = FakeRuntimeStore()
    db.active = True
    gateway = PgPriorityQueueGateway(db)

    enqueued, _ = asyncio.run(
        gateway.enqueue(
            site_id="madrid",
            protocol="P1",
            payload={"idRecurso": 99},
        )
    )

    assert enqueued is False
    assert db.enqueue_calls == []


def test_enqueue_raises_when_postgres_write_did_not_persist():
    db = FakeRuntimeStore()
    gateway = PgPriorityQueueGateway(db)
    db.upsert_job_run = lambda **kwargs: None

    try:
        asyncio.run(
            gateway.enqueue(
                site_id="madrid",
                protocol="P1",
                payload={"job_id": "job-lost", "idRecurso": 100},
            )
        )
    except RuntimeError as exc:
        assert "estado esperado=queued" in str(exc)
    else:
        raise AssertionError("La cola no debe confirmar una escritura PostgreSQL perdida")


async def _reserve_fixture(gateway, db):
    db.next_job = {
        "job_id": "job-2",
        "site_id": "xaloc_girona",
        "resource_id": 456,
        "payload": {"protocol": "P1", "max_attempts": 3},
        "attempt": 0,
    }
    return await gateway.reserve(timeout_seconds=1, worker_id="worker-b")
