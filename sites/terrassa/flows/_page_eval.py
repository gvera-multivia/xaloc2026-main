from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from playwright.async_api import Error as PlaywrightError

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger("xaloc_automation.terrassa")

_MISSING: Final[object] = object()


def _is_context_destroyed_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return (
        "execution context was destroyed" in message
        or "cannot find context with specified id" in message
    )


async def evaluate_with_nav_retry(
    page: "Page",
    script: str,
    arg: object = _MISSING,
    *,
    attempts: int = 3,
    wait_timeout_ms: int = 5000,
    settle_ms: int = 250,
):
    last_error: Exception | None = None

    for attempt in range(1, max(1, attempts) + 1):
        try:
            if arg is _MISSING:
                return await page.evaluate(script)
            return await page.evaluate(script, arg)
        except PlaywrightError as exc:
            if not _is_context_destroyed_error(exc) or attempt >= attempts:
                raise
            last_error = exc
            logger.warning(
                "terrassa: page.evaluate interrumpido por navegacion; reintento %s/%s",
                attempt,
                attempts,
            )
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=wait_timeout_ms)
            except Exception:
                pass
            await page.wait_for_timeout(settle_ms)

    if last_error is not None:
        raise last_error
    raise RuntimeError("terrassa: evaluate_with_nav_retry agotado sin resultado")
