"""
Flujo de autenticación para BASE On-line (landing -> VÀLid -> Common Desktop).
"""

from __future__ import annotations

import logging
import re
import threading

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

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


async def _esperar_dom_estable(page: Page, timeout_ms: int = 2000) -> None:
    """Espera a que el DOM esté estable (sin modificaciones de INSUIT u otros scripts)."""
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_load_state("networkidle")
    # Espera adicional para scripts dinámicos como INSUIT
    await page.wait_for_timeout(timeout_ms)


async def _localizar_enlace_base_online(page: Page, config: BaseOnlineConfig):
    """
    Intenta localizar el enlace 'Base On-line' usando múltiples estrategias.
    
    Estrategias (en orden de prioridad):
    1. get_by_role con texto exacto - más robusto contra cambios de DOM
    2. Selector CSS desde config
    3. Selector por href directo
    """
    estrategias = [
        # Estrategia 1: Por rol y texto (más robusto)
        lambda: page.get_by_role("link", name=re.compile(r"Base\s+On-?line", re.IGNORECASE)).first,
        # Estrategia 2: Selector CSS configurado
        lambda: page.locator(config.base_online_link_selector).first,
        # Estrategia 3: Selector por href directo
        lambda: page.locator("a[href*='/sav/valid']").first,
        # Estrategia 4: Por clase y contenido de texto
        lambda: page.locator("a.logo_text:has-text('Base On-line')").first,
    ]
    
    for i, estrategia in enumerate(estrategias, 1):
        try:
            enlace = estrategia()
            # Verificar que el elemento existe y es visible
            if await enlace.count() > 0:
                await enlace.wait_for(state="visible", timeout=5000)
                logging.info(f"Enlace 'Base On-line' encontrado con estrategia {i}")
                return enlace
        except PlaywrightTimeout:
            logging.debug(f"Estrategia {i} no encontró el enlace visible")
            continue
        except Exception as e:
            logging.debug(f"Estrategia {i} falló: {e}")
            continue
    
    raise RuntimeError("No se pudo localizar el enlace 'Base On-line' con ninguna estrategia")


async def _click_enlace_robusto(page: Page, enlace, url_destino: str) -> Page:
    """
    Intenta hacer click en el enlace con múltiples estrategias.
    Si todos los clicks fallan, navega directamente a la URL destino.
    """
    # Asegurar que el elemento está en el viewport
    try:
        await enlace.scroll_into_view_if_needed()
        await page.wait_for_timeout(300)  # Pequeña pausa para animaciones
    except Exception:
        pass
    
    # Intentar capturar popup si el enlace abre una nueva ventana
    try:
        async with page.expect_popup(timeout=3000) as popup_info:
            await enlace.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded")
        logging.info("Click exitoso - popup capturado")
        return popup
    except PlaywrightTimeout:
        # No hubo popup, el click pudo haber funcionado en la misma página
        await page.wait_for_load_state("domcontentloaded")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("Click exitoso - navegación en misma página")
            return page
    except Exception as e:
        logging.warning(f"Click normal falló: {e}")
    
    # Intentar click forzado (ignora overlays)
    try:
        await enlace.click(force=True)
        await page.wait_for_load_state("domcontentloaded")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("Click forzado exitoso")
            return page
    except Exception as e:
        logging.warning(f"Click forzado falló: {e}")
    
    # Intentar click via JavaScript
    try:
        await page.evaluate("""
            const enlace = document.querySelector("a.logo_text[href*='/sav/valid']") 
                        || document.querySelector("a[href*='/sav/valid']");
            if (enlace) enlace.click();
        """)
        await page.wait_for_load_state("domcontentloaded")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("Click via JavaScript exitoso")
            return page
    except Exception as e:
        logging.warning(f"Click JavaScript falló: {e}")
    
    # Último recurso: navegar directamente
    logging.warning("Todos los clicks fallaron, navegando directamente a VÀLid")
    await page.goto(url_destino, wait_until="networkidle")
    logging.info(f"Navegación directa a {url_destino}")
    return page


async def ejecutar_login_base(page: Page, config: BaseOnlineConfig) -> Page:
    logging.info(f"Navegando a {config.url_base}")
    await page.goto(config.url_base, wait_until="networkidle")

    # Esperar a que el DOM esté completamente cargado y estable
    await _esperar_dom_estable(page, timeout_ms=1500)

    await _aceptar_cookies_si_aparece(page)

    logging.info("Localizando enlace 'Base On-line'...")
    enlace = await _localizar_enlace_base_online(page, config)

    logging.info("Abriendo VÀLid...")
    page = await _click_enlace_robusto(
        page, 
        enlace, 
        url_destino="https://www.base.cat/sav/valid"
    )

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

