from __future__ import annotations

import fnmatch
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


def _url_matches(current_url: str, pattern: str | re.Pattern[str]) -> bool:
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(current_url))
    return fnmatch.fnmatch(current_url, pattern)


async def click_and_wait(
    page: "Page",
    locator: "Locator",
    *,
    url_patterns: list[str | re.Pattern[str]] | None = None,
    visible_selectors: list[str] | None = None,
    timeout_ms: int = 30000,
    click_timeout_ms: int = 10000,
    poll_ms: int = 250,
) -> None:
    await locator.wait_for(state="visible", timeout=timeout_ms)
    try:
        await locator.scroll_into_view_if_needed()
    except Exception:
        pass

    await locator.click(timeout=click_timeout_ms)

    if not url_patterns and not visible_selectors:
        try:
            await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 5000))
        except Exception:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 2000))
            except Exception:
                pass
        return

    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_url = str(page.url)
    while time.monotonic() < deadline:
        last_url = str(page.url)
        if url_patterns and any(_url_matches(last_url, pattern) for pattern in url_patterns):
            return

        if visible_selectors:
            for selector in visible_selectors:
                try:
                    candidate = page.locator(selector).first
                    if await candidate.count() > 0 and await candidate.is_visible():
                        return
                except Exception:
                    continue

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=500)
        except Exception:
            pass
        await page.wait_for_timeout(poll_ms)

    raise RuntimeError(
        "Diputacio BCN: la accion no alcanzo el siguiente estado esperado tras el click. "
        f"url={last_url!r} url_patterns={url_patterns!r} visible_selectors={visible_selectors!r}"
    )
