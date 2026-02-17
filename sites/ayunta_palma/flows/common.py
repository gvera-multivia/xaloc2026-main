"""
Helpers comunes para robustez de clicks en Ayunta Palma.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


async def robust_click(
    page: Page,
    *,
    description: str,
    primary: Locator | None = None,
    secondary: Locator | None = None,
    fallback_selector: str | None = None,
    same_screen_check: Callable[[], Awaitable[bool]] | None = None,
    max_attempts: int = 3,
    retry_wait_ms: int = 5000,
) -> None:
    """
    Click robusto:
    - valida existencia/visibilidad antes de click normal,
    - usa force como fallback,
    - opcionalmente intenta JS click por selector,
    - si tras 5s seguimos en la misma pantalla, reintenta.
    """

    async def _try_click_locator(locator: Locator | None) -> bool:
        if locator is None:
            return False
        try:
            if await locator.count() == 0 or not await locator.is_visible():
                return False
            await locator.scroll_into_view_if_needed()
            try:
                await locator.click(timeout=4000)
            except Exception:
                await locator.click(force=True, timeout=4000)
            return True
        except Exception:
            return False

    async def _try_click_js(selector: str | None) -> bool:
        if not selector:
            return False
        try:
            return bool(
                await page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    selector,
                )
            )
        except Exception:
            return False

    for attempt in range(1, max_attempts + 1):
        clicked = await _try_click_locator(primary)
        if not clicked:
            clicked = await _try_click_locator(secondary)
        if not clicked:
            clicked = await _try_click_js(fallback_selector)

        if not clicked:
            logger.warning(
                "[AP-DIAG] %s intento %s/%s: boton no visible/no clicable.",
                description,
                attempt,
                max_attempts,
            )
        else:
            logger.info("[AP-DIAG] %s intento %s/%s: click lanzado.", description, attempt, max_attempts)

        if same_screen_check is None:
            if clicked:
                return
            await page.wait_for_timeout(350)
            continue

        await page.wait_for_timeout(retry_wait_ms)
        still_same = False
        try:
            still_same = bool(await same_screen_check())
        except Exception:
            still_same = False

        if not still_same:
            return

        logger.warning(
            "[AP-DIAG] %s: seguimos en la misma pantalla tras %sms (intento %s/%s).",
            description,
            retry_wait_ms,
            attempt,
            max_attempts,
        )

    raise PlaywrightTimeoutError(f"{description}: agotados reintentos de click sin salir de la pantalla esperada.")
