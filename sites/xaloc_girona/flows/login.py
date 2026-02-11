"""
Flujo de autenticación VÀLid para Xaloc.
"""

from __future__ import annotations

import fnmatch
import logging
import re

from playwright.async_api import Page

from sites.xaloc_girona.config import XalocConfig


def _matches_post_login(url: str, pattern: str) -> bool:
    return fnmatch.fnmatch((url or "").lower(), (pattern or "").lower())


async def _aceptar_cookies_si_aparece(page: Page, config: XalocConfig) -> None:
    posibles = config.selectors.cookie_buttons
    for patron in posibles:
        boton = page.get_by_role("button", name=re.compile(patron, re.IGNORECASE))
        try:
            if await boton.count() > 0:
                await boton.first.click(timeout=config.flow_timeouts.cookie_click)
                await page.wait_for_timeout(config.flow_timeouts.short_delay)
                return
        except Exception:
            continue


async def ejecutar_login(page: Page, config: XalocConfig) -> Page:
    # 1. Comprobar si ya estamos en el formulario (por reutilización de pestaña)
    # url_post_login suele ser algo como "http://.../sta/sta/sta"
    actual_url = page.url
    if _matches_post_login(actual_url, config.url_post_login):
        logging.info("Pestaña ya está en el formulario STA. Saltando login.")
        return page

    logging.info(f"Navegando a {config.url_base}")
    await page.goto(config.url_base, wait_until="networkidle")
    await page.wait_for_timeout(config.delay_ms)

    # 2. Tras el goto, puede que hayamos redirigido directamente al formulario si hay sesión activa
    if _matches_post_login(page.url, config.url_post_login):
        logging.info("Redirección directa detectada (sesión activa). Saltando login.")
        return page

    await _aceptar_cookies_si_aparece(page, config)

    logging.info("Localizando enlace 'Tramitació en línia'...")
    enlace = page.get_by_role(
        "link",
        name=re.compile(config.selectors.tramite_link_regex, re.IGNORECASE),
    ).first
    await enlace.wait_for(state="visible", timeout=config.flow_timeouts.link_appear)

    logging.info("Pulsando enlace y esperando nueva pestaña de VÀLid...")
    async with page.expect_popup() as popup_info:
        await enlace.click()
        await page.wait_for_timeout(config.delay_ms)

    valid_page = await popup_info.value
    await valid_page.wait_for_load_state("domcontentloaded")
    logging.info(f"Pestaña detectada: {valid_page.url}")

    logging.info("Esperando el botón de certificado...")
    boton_cert = valid_page.locator(config.selectors.cert_button).first
    await boton_cert.wait_for(state="attached", timeout=config.flow_timeouts.cert_button_appear)

    logging.info("Pulsando botón de certificado...")
    await boton_cert.click(timeout=config.timeouts.login, no_wait_after=True, force=True)
    await valid_page.wait_for_timeout(config.delay_ms)

    logging.info("Esperando retorno al formulario STA...")
    await valid_page.wait_for_url(config.url_post_login, timeout=config.timeouts.login)
    logging.info("Login completado con éxito - Formulario STA cargado")

    return valid_page


__all__ = ["ejecutar_login"]

