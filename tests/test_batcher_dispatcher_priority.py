from services.batcher_dispatcher.app import BatcherDispatcherService, PendingValidated
from shared.queue.redis_streams import RedisStreamMessage


def _pending(*, fecpres, arrived_at: float, priority: int = 100, rid: str = "1") -> PendingValidated:
    return PendingValidated(
        message=RedisStreamMessage(stream="validated", message_id=f"{rid}-0", fields={}),
        payload={
            "job_draft_id": f"draft-{rid}",
            "organism_id": "atc",
            "job_type": "REPOSICIO",
            "cert_profile": "default",
            "priority": priority,
            "dedup_key": f"dedup-{rid}",
            "trace_id": f"trace-{rid}",
            "normalized_payload": {"idRecurso": rid, "fecpres": fecpres},
        },
        arrived_at=arrived_at,
    )


def test_pending_priority_key_orders_by_fecpres_soonest_first():
    items = [
        _pending(fecpres="2026-03-20", arrived_at=3.0, rid="20"),
        _pending(fecpres="2026-03-17", arrived_at=2.0, rid="17"),
        _pending(fecpres="2026-03-18", arrived_at=1.0, rid="18"),
    ]
    ordered = sorted(items, key=BatcherDispatcherService._pending_priority_key)
    assert [it.payload["normalized_payload"]["idRecurso"] for it in ordered] == ["17", "18", "20"]


def test_pending_priority_key_places_missing_or_invalid_fecpres_last():
    items = [
        _pending(fecpres="", arrived_at=1.0, rid="no-date"),
        _pending(fecpres="2026-03-17", arrived_at=2.0, rid="valid-date"),
        _pending(fecpres="17/03/2026", arrived_at=3.0, rid="invalid-date"),
    ]
    ordered = sorted(items, key=BatcherDispatcherService._pending_priority_key)
    assert [it.payload["normalized_payload"]["idRecurso"] for it in ordered] == [
        "valid-date",
        "no-date",
        "invalid-date",
    ]
