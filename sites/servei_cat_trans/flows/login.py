from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import ServeiCatTransConfig
    from ..data_models import ServeiCatTransTarget


async def _click_service_link(page: "Page", config: "ServeiCatTransConfig") -> "Page":
    link = page.locator(config.service_link_selector).first
    await link.wait_for(state="visible", timeout=config.navigation_timeout)
    try:
        async with page.context.expect_page(timeout=5000) as popup_info:
            await link.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded")
        return popup
    except PlaywrightTimeoutError:
        # El enlace puede navegar en la misma pestaña.
        return page
    except Exception:
        await link.click(force=True)
        return page


async def _click_access(page: "Page", config: "ServeiCatTransConfig") -> None:
    access_btn = page.locator(config.access_button_selector).first
    if await access_btn.count() <= 0:
        return
    await access_btn.click()


async def _click_certificate_button(page: "Page", config: "ServeiCatTransConfig") -> None:
    cert_btn = page.locator(config.cert_button_selector).first
    if await cert_btn.count() > 0:
        try:
            await cert_btn.click(timeout=8000, no_wait_after=True)
            return
        except Exception:
            await cert_btn.click(timeout=8000, force=True, no_wait_after=True)
            return

    role_btn = page.get_by_role("button", name=re.compile(r"certificado|certificat", re.IGNORECASE)).first
    await role_btn.click(timeout=8000, no_wait_after=True)


async def run_login(page: "Page", config: "ServeiCatTransConfig", datos: "ServeiCatTransTarget") -> "Page":
    _ = datos
    if "presentador=P" in page.url:
        return page

    await page.goto(config.url_base, wait_until="domcontentloaded", timeout=config.navigation_timeout)
    page = await _click_service_link(page, config)
    await page.wait_for_load_state("domcontentloaded")

    if "valid.aoc.cat" not in page.url and "renderitzaruploadSecure.do" not in page.url:
        await _click_access(page, config)

    if "valid.aoc.cat" in page.url:
        await _click_certificate_button(page, config)

    await page.wait_for_url(
        "**/renderitzaruploadSecure.do?reqCode=autenticarFormulariHtml**",
        timeout=config.auth_timeout_ms,
    )
    await page.wait_for_load_state("domcontentloaded")

    if "presentador=P" not in page.url:
        presentador = page.locator(config.presentador_link_selector).first
        if await presentador.count() > 0:
            await presentador.click()
            await page.wait_for_url("**presentador=P**", timeout=config.navigation_timeout)
            await page.wait_for_load_state("domcontentloaded")

    return page
