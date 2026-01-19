"""
Flujo de autenticación VÀLid para Xaloc.
"""

from __future__ import annotations

import logging
import re
import threading
import time

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.xaloc_girona.config import XalocConfig
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


async def _detectar_error_auth(page: Page) -> str | None:
    url = (page.url or "").lower()
    try:
        titulo = (await page.title()).lower()
    except Exception:
        titulo = ""

    if "ssl" in titulo or "err_ssl" in titulo:
        return "ssl"
    try:
        if await page.locator("text=/no se puede obtener acceso/i").first.is_visible(timeout=500):
            return "acceso"
    except Exception:
        pass
    try:
        if await page.locator("text=/ssl\\s*(handshake|protocol|error)|err_ssl/i").first.is_visible(timeout=500):
            return "ssl"
    except Exception:
        pass
    if "commonauth" in url:
        try:
            if await page.locator("text=/redirigiendo/i").first.is_visible(timeout=500):
                return "redirigiendo"
        except Exception:
            pass
    return None


async def ejecutar_login(page: Page, config: XalocConfig) -> Page:
    logging.info(f"Navegando a {config.url_base}")
    await page.goto(config.url_base, wait_until="networkidle")

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

    valid_page = await popup_info.value
    await valid_page.wait_for_load_state("domcontentloaded")
    logging.info(f"Pestaña detectada: {valid_page.url}")

    logging.info("Esperando el botón de certificado...")
    boton_cert = valid_page.locator(config.cert_button_selector).first
    await boton_cert.wait_for(state="visible", timeout=15000)

    def _resolver_popup_windows() -> None:
        esperar_y_aceptar_certificado(delay_inicial=2.0)

    thread_popup = threading.Thread(target=_resolver_popup_windows, daemon=True)
    thread_popup.start()

    logging.info("Pulsando botón de certificado...")
    await boton_cert.click()
    thread_popup.join(timeout=10)

    logging.info("Esperando retorno al formulario STA...")
    deadline = time.monotonic() + (config.timeouts.login / 1000.0)
    while True:
        try:
            await valid_page.wait_for_url(config.url_post_login, timeout=2000)
            break
        except PlaywrightTimeoutError:
            if time.monotonic() > deadline:
                raise
            problema = await _detectar_error_auth(valid_page)
            if problema:
                logging.warning(f"Detectado problema auth '{problema}', recovery: espera 3s + refresh")
                await valid_page.wait_for_timeout(3000)
                try:
                    await valid_page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    try:
                        await valid_page.keyboard.press("F5")
                    except Exception:
                        pass
                await valid_page.wait_for_timeout(getattr(config, "cert_popup_delay_ms", 2000))
                thread_popup = threading.Thread(
                    target=esperar_y_aceptar_certificado,
                    kwargs={"delay_inicial": 0.0},
                    daemon=True,
                )
                thread_popup.start()
                try:
                    await boton_cert.click(timeout=2000)
                except Exception:
                    pass
                thread_popup.join(timeout=10)
    logging.info("Login completado con éxito - Formulario STA cargado")

    return valid_page
