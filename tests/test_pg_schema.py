from __future__ import annotations

from core.pg_schema import PRIORITY_QUEUE_SCHEMA_LOCK_ID, acquire_priority_queue_schema_lock


class _Cursor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, query, params) -> None:
        self.calls.append((query, params))


def test_priority_queue_schema_lock_is_parameterized_and_stable() -> None:
    cursor = _Cursor()

    acquire_priority_queue_schema_lock(cursor)

    assert cursor.calls == [
        ("SELECT pg_advisory_xact_lock(%s)", (PRIORITY_QUEUE_SCHEMA_LOCK_ID,)),
    ]
