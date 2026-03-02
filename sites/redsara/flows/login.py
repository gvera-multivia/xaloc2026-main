from __future__ import annotations

import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.redsara.config import RedsaraConfig


async def _click_nuevo_registro(page: Page, config: RedsaraConfig) -> None:
    link = page.locator(config.selectors.nuevo_registro_link).first
    try:
        await link.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        await page.goto(config.url_nuevo_registro, wait_until="domcontentloaded", timeout=config.flow_timeouts.navigation_timeout_ms)
        return

    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.flow_timeouts.navigation_timeout_ms):
            await link.click()
    except PlaywrightTimeoutError:
        # Some runs are already in /nuevo-registro and no navigation event is fired.
        await link.click()


async def _click_afirma_if_present(page: Page, config: RedsaraConfig) -> None:
    """
    If REDSARA shows the IdP gateway, force AFIRMA (DNIe/Certificado).
    """
    button = page.locator(config.selectors.afima_login_button).first
    try:
        await button.wait_for(state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        return

    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.flow_timeouts.navigation_timeout_ms):
            await button.click()
    except PlaywrightTimeoutError:
        # Some transitions are SPA-style or happen in-place.
        await button.click(force=True)


async def ejecutar_login_redsara(page: Page, config: RedsaraConfig) -> Page:
    # Certificate is assumed to be preloaded and auto-selected by browser policy.
    await page.goto(config.url_base, wait_until="domcontentloaded", timeout=config.flow_timeouts.navigation_timeout_ms)

    if "/nuevo-registro" not in (page.url or ""):
        await _click_nuevo_registro(page, config)

    # Explicit certificate access when IdP gateway is displayed.
    await _click_afirma_if_present(page, config)

    if "/nuevo-registro" not in (page.url or ""):
        await page.goto(config.url_nuevo_registro, wait_until="domcontentloaded", timeout=config.flow_timeouts.navigation_timeout_ms)

    await page.wait_for_url(re.compile(r".*/nuevo-registro.*", re.IGNORECASE), timeout=config.flow_timeouts.navigation_timeout_ms)
    await page.locator(config.selectors.step1_heading).first.wait_for(state="visible", timeout=config.flow_timeouts.auth_wait_ms)
    return page
