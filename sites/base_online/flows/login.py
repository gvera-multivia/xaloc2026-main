"""
Flujo de autenticación para BASE On-line (landing -> VÀLid -> Common Desktop).
"""

from __future__ import annotations

import logging
import re
import threading

from playwright.async_api import Page

from sites.base_online.config import BaseOnlineConfig
from utils.windows_popup import esperar_y_aceptar_certificado


async def _aceptar_cookies_si_aparece(page: Page) -> None:
    posibles = [
        r"Acceptar",
        r"Aceptar",
        r"Aceptar todo",
        r"Aceptar todas",
        r"Accept all",
        r"Entesos",
    ]
    for patron in posibles:
        boton = page.get_by_role("button", name=re.compile(patron, re.IGNORECASE))
        try:
            if await boton.count() > 0:
                await boton.first.click(timeout=1500)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def _click_y_capturar_popup_si_existe(page: Page, *, locator) -> Page:
    try:
        async with page.expect_popup(timeout=3000) as popup_info:
            await locator.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded")
        return popup
    except Exception:
        await locator.click()
        await page.wait_for_load_state("domcontentloaded")
        return page


async def ejecutar_login_base(page: Page, config: BaseOnlineConfig) -> Page:
    logging.info(f"Navegando a {config.url_base}")
    await page.goto(config.url_base, wait_until="networkidle")

    await _aceptar_cookies_si_aparece(page)

    logging.info("Localizando enlace 'Base On-line'...")
    enlace = page.locator(config.base_online_link_selector).first
    await enlace.wait_for(state="visible", timeout=15000)

    logging.info("Abriendo VÀLid...")
    page = await _click_y_capturar_popup_si_existe(page, locator=enlace)

    logging.info("Esperando el botón de certificado...")
    boton_cert = page.locator(config.cert_button_selector).first
    await boton_cert.wait_for(state="visible", timeout=20000)

    def _resolver_popup_windows() -> None:
        esperar_y_aceptar_certificado(delay_inicial=2.0)

    thread_popup = threading.Thread(target=_resolver_popup_windows, daemon=True)
    thread_popup.start()

    logging.info("Pulsando botón de certificado...")
    await boton_cert.click()
    thread_popup.join(timeout=10)

    logging.info("Esperando acceso a Common Desktop...")
    await page.wait_for_url(config.url_post_login, timeout=config.timeouts.login)
    logging.info("Login completado - Common Desktop cargado")
    return page

