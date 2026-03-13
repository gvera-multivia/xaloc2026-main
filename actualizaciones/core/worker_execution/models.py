from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessOutcome:
    success: bool
    error: Optional[str] = None
    screenshot: Optional[str] = None
    release_without_attempt: bool = False
    payload_updates: dict = field(default_factory=dict)
