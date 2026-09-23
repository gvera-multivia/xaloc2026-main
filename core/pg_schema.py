from __future__ import annotations

from typing import Any


PRIORITY_QUEUE_SCHEMA_LOCK_ID = 2026092301


def acquire_priority_queue_schema_lock(cursor: Any) -> None:
    """Serialize the idempotent priority-queue schema bootstrap across services."""

    cursor.execute(
        "SELECT pg_advisory_xact_lock(%s)",
        (PRIORITY_QUEUE_SCHEMA_LOCK_ID,),
    )
