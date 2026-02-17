"""
Helpers comunes para robustez de clicks en Ayunta Palma.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig

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
    pre_click_wait_ms: int = 5000,
    post_click_extra_wait_ms: int = 5000,
) -> None:
    """
    Click robusto:
    - valida existencia/visibilidad antes de click normal,
    - usa force como fallback,
    - opcionalmente intenta JS click por selector,
    - espera adicional antes de pulsar para estabilizar el DOM,
    - si tras la espera seguimos en la misma pantalla, reintenta.
    """

    async def _try_click_locator(locator: Locator | None) -> bool:
        if locator is None:
            return False
        try:
            if await locator.count() == 0 or not await locator.is_visible():
                return False
            if pre_click_wait_ms > 0:
                await page.wait_for_timeout(pre_click_wait_ms)
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
            if pre_click_wait_ms > 0:
                await page.wait_for_timeout(pre_click_wait_ms)
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

        wait_after_click_ms = retry_wait_ms + post_click_extra_wait_ms if clicked else retry_wait_ms
        await page.wait_for_timeout(wait_after_click_ms)
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
            wait_after_click_ms,
            attempt,
            max_attempts,
        )

    raise PlaywrightTimeoutError(f"{description}: agotados reintentos de click sin salir de la pantalla esperada.")


def _is_nueva_entrada_url(url: str) -> bool:
    return "/carpetaciudadana/nueva_entrada.aspx" in (url or "")


def _is_preguntar_entrada_url(url: str) -> bool:
    return "/carpetaciudadana/preguntar_entrada_anterior.aspx" in (url or "")


def _is_carpeta_ciudadana_url(url: str) -> bool:
    return "/carpetaciudadana/carpeta_ciudadana.aspx" in (url or "")


def _is_login_url(url: str) -> bool:
    return "/carpetaciudadana/login.aspx" in (url or "")


async def watchdog_recover_navigation(
    page: Page,
    config: AyuntaPalmaConfig,
    *,
    phase: str,
    expected_selector: str | None = None,
) -> None:
    """
    Watchdog de navegación para Palma:
    - detecta desvíos a carpeta/login,
    - reabre el flujo en url_base,
    - opcionalmente valida selector esperado de la fase.
    """
    if page.is_closed():
        raise PlaywrightTimeoutError(f"[{phase}] watchdog: la pestaña está cerrada.")

    if expected_selector:
        try:
            await page.locator(expected_selector).first.wait_for(state="visible", timeout=1200)
            return
        except Exception:
            pass

    current = page.url or ""
    in_expected_flow = _is_nueva_entrada_url(current) or _is_preguntar_entrada_url(current)
    must_recover = _is_carpeta_ciudadana_url(current) or _is_login_url(current) or (not in_expected_flow)

    if not must_recover:
        return

    logger.warning("[AP-WATCHDOG] %s: URL inesperada '%s'. Reenganchando flujo...", phase, current)
    await page.goto(config.url_base, wait_until="domcontentloaded")
    await page.wait_for_timeout(config.delay_ms)

    if expected_selector:
        try:
            await page.locator(expected_selector).first.wait_for(state="visible", timeout=15000)
        except Exception:
            logger.warning(
                "[AP-WATCHDOG] %s: selector esperado no visible tras recuperación: %s",
                phase,
                expected_selector,
            )
