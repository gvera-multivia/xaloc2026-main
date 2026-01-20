"""
Flujo de autenticación VÀLid para Xaloc.
"""

from __future__ import annotations

import logging
import re
import sys
import threading

from playwright.async_api import Page

from sites.xaloc_girona.config import XalocConfig
from utils.windows_popup import aceptar_popup_certificado

DELAY_MS = 500


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


async def ejecutar_login(page: Page, config: XalocConfig) -> Page:
    logging.info(f"Navegando a {config.url_base}")
    await page.goto(config.url_base, wait_until="networkidle")
    await page.wait_for_timeout(getattr(config, "delay_ms", DELAY_MS))

    await _aceptar_cookies_si_aparece(page)

    logging.info("Localizando enlace 'Tramitació en línia'...")
    enlace = page.get_by_role(
        "link",
        name=re.compile(
            r"Tramitaci[oó] en l[ií]nia|Tramitaci[oó]n en l[ií]nea",
            re.IGNORECASE,
        ),
    ).first
    await enlace.wait_for(state="visible", timeout=10000)

    logging.info("Pulsando enlace y esperando nueva pestaña de VÀLid...")
    async with page.expect_popup() as popup_info:
        await enlace.click()
        await page.wait_for_timeout(getattr(config, "delay_ms", DELAY_MS))

    valid_page = await popup_info.value
    await valid_page.wait_for_load_state("domcontentloaded")
    logging.info(f"Pestaña detectada: {valid_page.url}")

    logging.info("Esperando el botón de certificado...")
    boton_cert = valid_page.locator(config.cert_button_selector).first
    await boton_cert.wait_for(state="visible", timeout=15000)

    # En headless no podemos interactuar con popups nativos (PyAutoGUI).
    # Con auto-selección de certificado (policy/flag), no debería aparecer el popup.
    thread_popup = None
    if sys.platform == "win32" and not getattr(config.navegador, "headless", False):
        def _resolver_popup_windows() -> None:
            aceptar_popup_certificado(
                tabs_atras=2,
                delay_inicial=max(0.0, getattr(config, "cert_popup_delay_ms", 1500) / 1000.0),
            )

        thread_popup = threading.Thread(target=_resolver_popup_windows, daemon=True)
        thread_popup.start()

    logging.info("Pulsando botón de certificado...")
    # Evita timeout por "scheduled navigations" en el click; el control lo hace wait_for_url().
    await boton_cert.click(timeout=config.timeouts.login, no_wait_after=True)
    await valid_page.wait_for_timeout(getattr(config, "delay_ms", DELAY_MS))
    if thread_popup:
        thread_popup.join(timeout=10)

    # Si tras aceptar el popup seguimos en login, reintentar Shift+Tab x2.
    await valid_page.wait_for_timeout(4000)
    if "seu.xalocgirona.cat/sta/" not in (valid_page.url or ""):
        logging.warning("Seguimos en login tras 4s; reintentando aceptación de certificado")
        if sys.platform == "win32" and not getattr(config.navegador, "headless", False):
            thread_popup_2 = threading.Thread(
                target=aceptar_popup_certificado,
                kwargs={"tabs_atras": 2, "delay_inicial": 0.0},
                daemon=True,
            )
            thread_popup_2.start()
            thread_popup_2.join(timeout=10)

    logging.info("Esperando retorno al formulario STA...")
    await valid_page.wait_for_url(config.url_post_login, timeout=config.timeouts.login)
    logging.info("Login completado con éxito - Formulario STA cargado")

    return valid_page
