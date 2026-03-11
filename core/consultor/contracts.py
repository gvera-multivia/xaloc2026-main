from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CanonicalResourceV1:
    site_id: str
    resource: dict[str, Any]
    client: dict[str, Any]
    vehicle: dict[str, Any]
    attachments: list[dict[str, Any]]
    meta: dict[str, Any]

