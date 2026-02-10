from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Optional


class PaginatedResponse(BaseModel):
    items: list[Any]
    page: int
    page_size: int
    total: int


class IncidentItem(BaseModel):
    site_id: str
    resource_id: Optional[int] = None
    expediente: Optional[str] = None
    incident_type: str
    reason: Optional[str] = None
    day: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    payload: Any = None


class SuccessItem(BaseModel):
    site_id: str
    resource_id: Optional[int] = None
    job_id: Optional[str] = None
    protocol: Optional[str] = None
    day: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    payload: Any = None
    result: Any = None


class QueueItem(BaseModel):
    site_id: str
    resource_id: Optional[int] = None
    state: str
    protocol: Optional[str] = None
    day: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    payload: Any = None
    job_id: Optional[str] = None
    queue_ref: Optional[int] = None
