from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AjuntamentBarcelonaConfig
    from ..data_models import AjuntamentBarcelonaTarget


logger = logging.getLogger("xaloc_automation.ajuntament_barcelona")


async def _get_alive_page(page: "Page") -> "Page":
    if not page.is_closed():
        return page
    alive_pages = [p for p in page.context.pages if not p.is_closed()]
    if not alive_pages:
        raise RuntimeError("login: no hay paginas activas en el contexto")
    return alive_pages[-1]


async def _wait_page_ready(page: "Page", timeout_ms: int) -> None:
    page = await _get_alive_page(page)
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # Fallback para portales con llamadas largas o cierres/reaperturas de target.
        page = await _get_alive_page(page)
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)


async def run_login(page: "Page", config: "AjuntamentBarcelonaConfig", datos: "AjuntamentBarcelonaTarget") -> "Page":
    _ = datos
    logger.info("ajuntament_barcelona.login goto=%s", config.url_base)
    page.set_default_timeout(config.default_timeout)
    page.set_default_navigation_timeout(config.navigation_timeout)

    await page.goto(config.url_base, wait_until="domcontentloaded")
    await _wait_page_ready(page, timeout_ms=config.navigation_timeout)

    page = await _get_alive_page(page)
    logger.info("ajuntament_barcelona.login done url=%s", page.url)
    return page
