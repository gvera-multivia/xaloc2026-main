from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .cookies import ensure_cookie_banner_cleared, dismiss_cookie_banners_in_context

if TYPE_CHECKING:
    from playwright.async_api import Page

    from ..config import ServeiCatTransConfig
    from ..data_models import ServeiCatTransTarget


async def _dismiss_cookie_banner_if_present(page: "Page", *, timeout_ms: int = 4000) -> None:
    await ensure_cookie_banner_cleared(page, total_timeout_ms=timeout_ms, poll_ms=250)


def _is_identificacion(datos: "ServeiCatTransTarget") -> bool:
    return str(getattr(datos, "tramite_tipo", "") or "").strip().lower() == "identificacion"


async def _click_service_link(page: "Page", config: "ServeiCatTransConfig", *, service_selector: str) -> "Page":
    await dismiss_cookie_banners_in_context(page)
    link = page.locator(service_selector).first
    if await link.count() <= 0:
        return page
    await link.wait_for(state="visible", timeout=config.navigation_timeout)
    try:
        async with page.context.expect_page(timeout=5000) as popup_info:
            await link.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded")
        await dismiss_cookie_banners_in_context(popup)
        return popup
    except PlaywrightTimeoutError:
        try:
            await page.wait_for_url("**/renderitzar.do?reqCode=inicial**", timeout=8000)
        except Exception:
            pass
        return page
    except Exception:
        await link.click(force=True)
        try:
            await page.wait_for_url("**/renderitzar.do?reqCode=inicial**", timeout=8000)
        except Exception:
            pass
        return page


async def _click_access(page: "Page", config: "ServeiCatTransConfig") -> None:
    access_btn = page.locator(config.access_button_selector).first
    if await access_btn.count() <= 0:
        return
    await dismiss_cookie_banners_in_context(page)
    await access_btn.click()
    await dismiss_cookie_banners_in_context(page)


async def _click_certificate_button(page: "Page", config: "ServeiCatTransConfig") -> None:
    await dismiss_cookie_banners_in_context(page)
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
    is_identificacion = _is_identificacion(datos)
    service_selector = (
        config.service_link_selector_identificacion if is_identificacion else config.service_link_selector
    )
    expected_service_token = "idServei=TRN002SIGN" if is_identificacion else "idServei=TRN001SIGN"
    service_entry_url = (
        config.url_service_entry_identificacion if is_identificacion else config.url_service_entry
    )

    if "presentador=P" in page.url:
        return page

    await page.goto(config.url_base, wait_until="domcontentloaded", timeout=config.navigation_timeout)
    await dismiss_cookie_banners_in_context(page)
    page = await _click_service_link(page, config, service_selector=service_selector)
    await page.wait_for_load_state("domcontentloaded")
    await dismiss_cookie_banners_in_context(page)

    current = str(page.url or "")
    if "renderitzar.do?reqCode=inicial" not in current and "renderitzaruploadSecure.do" not in current:
        await page.goto(service_entry_url, wait_until="domcontentloaded", timeout=config.navigation_timeout)
        await dismiss_cookie_banners_in_context(page)
    elif "renderitzar.do?reqCode=inicial" in current and expected_service_token not in current:
        await page.goto(service_entry_url, wait_until="domcontentloaded", timeout=config.navigation_timeout)
        await dismiss_cookie_banners_in_context(page)

    if "valid.aoc.cat" not in page.url and "renderitzaruploadSecure.do" not in page.url:
        await _click_access(page, config)
        await dismiss_cookie_banners_in_context(page)

    if "valid.aoc.cat" in page.url:
        await _click_certificate_button(page, config)

    await page.wait_for_url(
        "**/renderitzaruploadSecure.do?reqCode=autenticarFormulariHtml**",
        timeout=config.auth_timeout_ms,
    )
    await page.wait_for_load_state("domcontentloaded")
    await dismiss_cookie_banners_in_context(page)

    if "presentador=P" not in page.url:
        await dismiss_cookie_banners_in_context(page)
        presentador = page.locator(config.presentador_link_selector).first
        if await presentador.count() > 0:
            await presentador.click()
            await page.wait_for_url("**presentador=P**", timeout=config.navigation_timeout)
            await page.wait_for_load_state("domcontentloaded")
            await dismiss_cookie_banners_in_context(page)

    return page
