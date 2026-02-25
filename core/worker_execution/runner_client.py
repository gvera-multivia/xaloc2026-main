from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .models import ProcessOutcome

logger = logging.getLogger("worker.runner_client")


def use_remote_playwright_runner() -> bool:
    return (os.getenv("USE_PLAYWRIGHT_RUNNER_SERVICE") or "0").strip().lower() in {"1", "true", "yes", "on"}


def get_playwright_runner_url() -> str:
    return (os.getenv("PLAYWRIGHT_RUNNER_URL") or "http://playwright-runner-service:8111").strip()


def _build_runner_url_candidates() -> list[str]:
    primary = get_playwright_runner_url().strip().rstrip("/")
    candidates: list[str] = []

    def _add(url: str) -> None:
        u = (url or "").strip().rstrip("/")
        if u and u not in candidates:
            candidates.append(u)

    _add(primary)

    fallback_raw = (os.getenv("PLAYWRIGHT_RUNNER_URL_FALLBACKS") or "").strip()
    if fallback_raw:
        for item in fallback_raw.split(","):
            _add(item)

    try:
        parsed = urlsplit(primary)
        host = (parsed.hostname or "").strip().lower()
        if host in {"playwright-runner-service", "playwright-runner"}:
            alt_host = "localhost"
        elif host in {"localhost", "127.0.0.1"}:
            alt_host = "playwright-runner-service"
        else:
            alt_host = ""
        if alt_host:
            netloc = alt_host
            if parsed.port:
                netloc = f"{alt_host}:{parsed.port}"
            elif parsed.scheme == "https":
                netloc = f"{alt_host}:443"
            elif parsed.scheme == "http":
                netloc = f"{alt_host}:80"
            _add(urlunsplit((parsed.scheme or "http", netloc, parsed.path or "", "", "")))
    except Exception:
        pass

    return candidates


async def execute_via_runner_service(
    *,
    site_id: str,
    protocol: Optional[str],
    payload: dict,
    archivos_para_subir: list[Path],
) -> ProcessOutcome:
    base_urls = _build_runner_url_candidates()
    request_payload = {
        "site_id": site_id,
        "protocol": protocol,
        "payload": payload,
        "archivos": [str(p) for p in archivos_para_subir],
    }
    timeout_seconds = int((os.getenv("PLAYWRIGHT_RUNNER_TIMEOUT_SECONDS") or "900").strip() or "900")
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        last_connection_error: Exception | None = None
        for idx, base_url in enumerate(base_urls, start=1):
            try:
                async with session.post(f"{base_url}/execute", json=request_payload) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        raise RuntimeError(f"Runner respondio {resp.status}: {body[:400]}")
                    data = json.loads(body)
                    if not isinstance(data, dict):
                        raise RuntimeError("Respuesta invalida del runner.")
                    if idx > 1:
                        logger.warning("Runner conectado via fallback: %s", base_url)
                    return ProcessOutcome(
                        success=bool(data.get("success")),
                        error=data.get("error"),
                        screenshot=data.get("screenshot"),
                        release_without_attempt=bool(data.get("release_without_attempt")),
                        payload_updates=data.get("payload_updates") or {},
                    )
            except (aiohttp.ClientConnectorDNSError, aiohttp.ClientConnectorError, aiohttp.ClientOSError) as exc:
                last_connection_error = exc
                logger.warning(
                    "Runner URL no alcanzable (%s/%s): %s (%s)",
                    idx,
                    len(base_urls),
                    base_url,
                    exc,
                )
                continue

        if last_connection_error is not None:
            raise RuntimeError(
                "No se pudo conectar con playwright-runner en ninguna URL: "
                f"{', '.join(base_urls)}. Ultimo error: {last_connection_error}"
            ) from last_connection_error
        raise RuntimeError("No hay URLs configuradas para playwright-runner.")
