from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services.jobs.repository import JobsRepository


class CreateJobRequest(BaseModel):
    job_id: str
    status: str = "created"
    payload: dict[str, Any] = Field(default_factory=dict)
    dedup_key: Optional[str] = None
    priority: int = 100


class TransitionJobRequest(BaseModel):
    status: str
    error_message: Optional[str] = None
    result: Optional[dict[str, Any]] = None


app = FastAPI(title="Jobs Service", version="0.1.0")
repo = JobsRepository.from_env()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "jobs"}


@app.post("/jobs")
def create_job(payload: CreateJobRequest) -> dict[str, Any]:
    item = repo.create_or_update_job(
        job_id=payload.job_id,
        status=payload.status,
        payload=payload.payload,
        dedup_key=payload.dedup_key,
        priority=payload.priority,
    )
    return {"item": item}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    item = repo.get_job(job_id)
    if item is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"item": item}


@app.post("/jobs/{job_id}/transition")
def transition_job(job_id: str, payload: TransitionJobRequest) -> dict[str, Any]:
    item = repo.transition_job(
        job_id=job_id,
        status=payload.status,
        error_message=payload.error_message,
        result=payload.result,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"item": item}

