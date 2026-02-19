from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.worker_execution.browser_executor import execute_browser_flow

app = FastAPI(title="playwright-runner-service", version="0.1.0")


class ExecuteRequest(BaseModel):
    site_id: str
    protocol: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    archivos: list[str] = Field(default_factory=list)


class ExecuteResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    screenshot: Optional[str] = None
    release_without_attempt: bool = False
    payload_updates: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/execute", response_model=ExecuteResponse)
async def execute(payload: ExecuteRequest) -> ExecuteResponse:
    try:
        outcome = await execute_browser_flow(
            site_id=payload.site_id,
            protocol=payload.protocol,
            payload=payload.payload,
            archivos_para_subir=[Path(p) for p in payload.archivos],
        )
        return ExecuteResponse(
            success=outcome.success,
            error=outcome.error,
            screenshot=outcome.screenshot,
            release_without_attempt=outcome.release_without_attempt,
            payload_updates=outcome.payload_updates,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
