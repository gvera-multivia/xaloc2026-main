from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    CREATED = "created"
    VALIDATED = "validated"
    BATCHED = "batched"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class CandidateMessage:
    candidate_id: str = field(default_factory=lambda: str(uuid4()))
    organism_id: str = ""
    external_resource_id: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    claimed_at: str = field(default_factory=utc_now_iso)
    trace_id: Optional[str] = None


@dataclass(slots=True)
class ValidatedMessage:
    job_draft_id: str = field(default_factory=lambda: str(uuid4()))
    organism_id: str = ""
    job_type: str = ""
    cert_profile: str = "default"
    priority: int = 100
    normalized_payload: dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    validated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class JobArtifactDescriptor:
    artifact_type: str
    file_path: str
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None


@dataclass(slots=True)
class JobStreamMessage:
    job_id: str = field(default_factory=lambda: str(uuid4()))
    attempt: int = 0
    max_attempts: int = 3
    execution_plan: dict[str, Any] = field(default_factory=dict)
    artifacts_base_path: str = ""
    trace_id: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)

