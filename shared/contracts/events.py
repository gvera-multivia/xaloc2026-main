from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class EventEnvelope:
    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: str = ""
    source: str = ""
    trace_id: Optional[str] = None
    job_id: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

