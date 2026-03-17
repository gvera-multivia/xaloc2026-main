from __future__ import annotations

import asyncio
import base64
import logging
import re
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.worker_execution.browser_executor import execute_browser_flow

app = FastAPI(title="playwright-runner-service", version="0.1.0")
_EXECUTE_LOCK = asyncio.Lock()
logger = logging.getLogger("playwright-runner")


def _configure_runner_logging() -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    stable_log_path = (logs_dir / "playwright_runner_out.log").resolve()

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler):
            try:
                if Path(handler.baseFilename).resolve() == stable_log_path:
                    return
            except Exception:
                continue

    file_handler = logging.FileHandler(stable_log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - [PLAYWRIGHT-RUNNER] - %(levelname)s - %(message)s")
    )
    root.addHandler(file_handler)


_configure_runner_logging()


class ExecuteRequest(BaseModel):
    site_id: str
    protocol: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    archivos: list[str] = Field(default_factory=list)
    archivo_blobs: list[dict[str, str]] = Field(default_factory=list)


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
    temp_input_dir: Path | None = None
    try:
        data = payload.payload or {}
        summary = {
            "keys": len(data),
            "idRecurso": data.get("idRecurso"),
            "external_resource_id": data.get("external_resource_id"),
            "expediente": data.get("expediente") or data.get("Expedient"),
            "tramite_code": data.get("tramite_code"),
            "has_nested_payload_dict": isinstance(data.get("payload"), dict),
            "nested_payload_keys": len(data.get("payload") or {}) if isinstance(data.get("payload"), dict) else 0,
        }
        logger.warning(
            "Runner execute request site=%s protocol=%s summary=%s archivos=%s",
            payload.site_id,
            payload.protocol,
            summary,
            len(payload.archivos or []),
        )
        input_paths: list[Path] = []
        if payload.archivo_blobs:
            temp_input_dir = Path(tempfile.mkdtemp(prefix="runner_inputs_"))
            for idx, blob in enumerate(payload.archivo_blobs, start=1):
                raw_name = str(blob.get("name") or f"input_{idx}.bin")
                safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(raw_name).name) or f"input_{idx}.bin"
                raw_b64 = str(blob.get("content_b64") or "")
                if not raw_b64:
                    raise ValueError(f"archivo_blobs[{idx}] sin content_b64")
                dst = temp_input_dir / safe_name
                dst.write_bytes(base64.b64decode(raw_b64))
                input_paths.append(dst)
        else:
            input_paths = [Path(p) for p in (payload.archivos or [])]

        missing = [str(p) for p in input_paths if not p.exists()]
        if missing:
            logger.critical(
                "CRITICAL_RUNNER_INPUT_MISSING: archivos inexistentes antes de ejecutar site=%s idRecurso=%s missing=%s",
                payload.site_id,
                data.get("idRecurso") or data.get("external_resource_id"),
                missing,
            )
            raise FileNotFoundError(", ".join(missing))

        async with _EXECUTE_LOCK:
            outcome = await execute_browser_flow(
                site_id=payload.site_id,
                protocol=payload.protocol,
                payload=payload.payload,
                archivos_para_subir=input_paths,
            )
        return ExecuteResponse(
            success=outcome.success,
            error=outcome.error,
            screenshot=outcome.screenshot,
            release_without_attempt=outcome.release_without_attempt,
            payload_updates=outcome.payload_updates,
        )
    except Exception as exc:
        logger.error("Error ejecutando flujo site=%s protocol=%s: %s", payload.site_id, payload.protocol, exc)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if temp_input_dir and temp_input_dir.exists():
            shutil.rmtree(temp_input_dir, ignore_errors=True)
