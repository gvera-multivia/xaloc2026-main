from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import aiohttp

from .models import ProcessOutcome

logger = logging.getLogger("worker.runner_client")


def use_remote_playwright_runner() -> bool:
    return (os.getenv("USE_PLAYWRIGHT_RUNNER_SERVICE") or "0").strip().lower() in {"1", "true", "yes", "on"}


def get_playwright_runner_url() -> str:
    return (os.getenv("PLAYWRIGHT_RUNNER_URL") or "http://playwright-runner-service:8111").strip()


async def execute_via_runner_service(
    *,
    site_id: str,
    protocol: Optional[str],
    payload: dict,
    archivos_para_subir: list[Path],
) -> ProcessOutcome:
    base_url = get_playwright_runner_url().rstrip("/")
    request_payload = {
        "site_id": site_id,
        "protocol": protocol,
        "payload": payload,
        "archivos": [str(p) for p in archivos_para_subir],
    }
    timeout_seconds = int((os.getenv("PLAYWRIGHT_RUNNER_TIMEOUT_SECONDS") or "900").strip() or "900")
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{base_url}/execute", json=request_payload) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Runner respondio {resp.status}: {body[:400]}")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise RuntimeError("Respuesta invalida del runner.")
            return ProcessOutcome(
                success=bool(data.get("success")),
                error=data.get("error"),
                screenshot=data.get("screenshot"),
                release_without_attempt=bool(data.get("release_without_attempt")),
                payload_updates=data.get("payload_updates") or {},
            )
