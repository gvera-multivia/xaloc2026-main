"""Serializacion de las operaciones dinamicas del portal legacy de Madrid."""

from __future__ import annotations

import logging
import time
from weakref import WeakKeyDictionary

from playwright.async_api import Page

logger = logging.getLogger(__name__)

_TRACKERS: WeakKeyDictionary = WeakKeyDictionary()


class MadridRequestSyncTimeout(RuntimeError):
    """WFORS mantiene una operacion dinamica pendiente mas alla del timeout."""


class MadridRequestSynchronizer:
    def __init__(self, page: Page) -> None:
        self._pending: set[int] = set()
        self._last_activity = time.monotonic()
        page.on("request", self._on_request)
        page.on("requestfinished", self._on_request_done)
        page.on("requestfailed", self._on_request_done)

    @staticmethod
    def _is_relevant(request) -> bool:
        url = (request.url or "").lower()
        return (
            request.method.upper() == "POST"
            and "madrid.es/wfors_wbfors/" in url
            and request.resource_type in {"document", "xhr", "fetch"}
        )

    def _on_request(self, request) -> None:
        if self._is_relevant(request):
            self._pending.add(id(request))
            self._last_activity = time.monotonic()

    def _on_request_done(self, request) -> None:
        request_id = id(request)
        if request_id in self._pending:
            self._pending.discard(request_id)
            self._last_activity = time.monotonic()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def wait_until_idle(
        self,
        page: Page,
        *,
        label: str,
        timeout_ms: int = 15_000,
        quiet_ms: int = 500,
    ) -> None:
        deadline = time.monotonic() + (timeout_ms / 1000)
        quiet_seconds = quiet_ms / 1000
        while time.monotonic() < deadline:
            if not self._pending and time.monotonic() - self._last_activity >= quiet_seconds:
                return
            await page.wait_for_timeout(50)
        raise MadridRequestSyncTimeout(
            f"Madrid: timeout esperando operaciones WFORS en {label}; pending={self.pending_count}"
        )


def install_madrid_request_sync(page: Page) -> MadridRequestSynchronizer:
    tracker = _TRACKERS.get(page)
    if tracker is None:
        tracker = MadridRequestSynchronizer(page)
        _TRACKERS[page] = tracker
        logger.info("Madrid: sincronizacion secuencial WFORS activada")
    return tracker


async def wait_madrid_requests(
    page: Page,
    *,
    label: str,
    timeout_ms: int = 15_000,
    quiet_ms: int = 500,
) -> None:
    tracker = install_madrid_request_sync(page)
    await tracker.wait_until_idle(
        page,
        label=label,
        timeout_ms=timeout_ms,
        quiet_ms=quiet_ms,
    )


def pending_madrid_requests(page: Page) -> int:
    tracker = _TRACKERS.get(page)
    return tracker.pending_count if tracker else 0
