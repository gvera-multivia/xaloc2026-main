"""
Flujo de autenticación para BASE On-line (landing -> VÀLid -> Common Desktop).
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from sites.base_online.config import BaseOnlineConfig


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
                await page.wait_for_timeout(1000)
                return
        except Exception:
            continue


async def _esperar_dom_estable(page: Page, config: BaseOnlineConfig, timeout_ms: int = 2000) -> None:
    """
    Espera a que el DOM esté estable.

    NOTA: No usamos 'networkidle' porque los scripts de INSUIT (accesibilidad)
    hacen peticiones de red constantes y nunca se alcanza el estado idle.
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=config.flow_timeouts.dom_content_loaded)
    except PlaywrightTimeout:
        logging.warning("Timeout esperando domcontentloaded, continuando...")

    try:
        await page.wait_for_load_state("load", timeout=config.flow_timeouts.page_load)
    except PlaywrightTimeout:
        logging.warning("Timeout esperando load completo, continuando...")

    await page.wait_for_timeout(timeout_ms)


async def _localizar_enlace_base_online(page: Page, config: BaseOnlineConfig):
    """
    Intenta localizar el enlace 'Base On-line' usando múltiples estrategias.
    """
    logging.info("[FASE 1.2] Buscando enlace 'Base On-line'...")

    estrategias = [
        ("Por rol y texto", lambda: page.get_by_role("link", name=re.compile(r"Base\s+On-?line", re.IGNORECASE)).first),
        ("Selector CSS config", lambda: page.locator(config.base_online_link_selector).first),
        ("Por href /sav/valid", lambda: page.locator(config.selectors.landing_link_href).first),
        ("Por clase logo_text", lambda: page.locator(config.selectors.landing_link_logo).first),
    ]

    for nombre, estrategia in estrategias:
        try:
            logging.debug(f"[FASE 1.2] Probando estrategia: {nombre}")
            enlace = estrategia()
            count = await enlace.count()
            logging.debug(f"[FASE 1.2] Estrategia '{nombre}': encontrados {count} elementos")

            if count > 0:
                await enlace.wait_for(state="visible", timeout=config.flow_timeouts.dom_content_loaded)
                logging.info(f"[FASE 1.2] OK Enlace encontrado con '{nombre}'")
                return enlace
        except PlaywrightTimeout:
            logging.warning(f"[FASE 1.2] Estrategia '{nombre}': elemento no visible en 5s")
            continue
        except Exception as e:
            logging.warning(f"[FASE 1.2] Estrategia '{nombre}' fallo: {e}")
            continue

    raise RuntimeError("No se pudo localizar el enlace 'Base On-line' con ninguna estrategia")


async def _click_enlace_robusto(page: Page, enlace, url_destino: str, config: BaseOnlineConfig) -> Page:
    """
    Intenta hacer click en el enlace con múltiples estrategias.
    Si todos los clicks fallan, navega directamente a la URL destino.
    """
    logging.info("[FASE 1.3] Intentando click en enlace...")

    try:
        await enlace.scroll_into_view_if_needed()
        await page.wait_for_timeout(config.delay_ms)
    except Exception:
        pass

    logging.debug("[FASE 1.3] Metodo 1: Click con captura de popup")
    try:
        async with page.expect_popup(timeout=config.flow_timeouts.click_popup) as popup_info:
            await enlace.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded")
        logging.info("[FASE 1.3] OK Click exitoso - popup capturado")
        return popup
    except PlaywrightTimeout:
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] Sin popup, URL actual: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] OK Click exitoso - navegacion en misma pagina")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Metodo 1 fallo: {e}")

    logging.debug("[FASE 1.3] Metodo 2: Click forzado")
    try:
        await enlace.click(force=True, timeout=config.flow_timeouts.click_popup)
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] URL despues de click forzado: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] OK Click forzado exitoso")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Metodo 2 fallo: {e}")

    logging.debug("[FASE 1.3] Metodo 3: Click via JavaScript")
    try:
        await page.evaluate(config.scripts.click_link_js)
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] URL despues de JS click: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] OK Click via JavaScript exitoso")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Metodo 3 fallo: {e}")

    logging.warning("[FASE 1.3] Todos los clicks fallaron, navegando directamente a VALid")
    await page.goto(url_destino, wait_until="domcontentloaded")
    logging.info(f"[FASE 1.3] Navegacion directa completada: {url_destino}")
    return page


async def ejecutar_login_base(page: Page, config: BaseOnlineConfig) -> Page:
    logging.info(f"[FASE 1.1] Navegando a landing: {config.url_base}")

    try:
        await page.goto(config.url_base, wait_until="domcontentloaded", timeout=config.timeouts.general)
        logging.info(f"[FASE 1.1] DOM cargado, URL actual: {page.url}")
    except PlaywrightTimeout:
        logging.error("[FASE 1.1] Timeout al cargar la pagina. Verificar conexion a internet.")
        raise

    logging.info("[FASE 1.1] Esperando estabilizacion del DOM...")
    await _esperar_dom_estable(page, config, timeout_ms=config.flow_timeouts.dom_stable)
    await page.wait_for_timeout(config.delay_ms)

    await _aceptar_cookies_si_aparece(page)

    enlace = await _localizar_enlace_base_online(page, config)
    page = await _click_enlace_robusto(page, enlace, url_destino="https://www.base.cat/sav/valid", config=config)

    await page.wait_for_timeout(config.delay_ms)
    if "/commons-desktop/index" in (page.url or ""):
        logging.info("[FASE 1.4] OK Ya autenticado (Common Desktop), saltando certificado")
        return page

    logging.info("[FASE 1.4] Esperando el boton de certificado...")
    logging.debug(f"[FASE 1.4] URL actual: {page.url}")
    logging.debug(f"[FASE 1.4] Selector boton certificado: {config.cert_button_selector}")

    boton_cert = page.locator(config.cert_button_selector).first
    try:
        await boton_cert.wait_for(state="attached", timeout=config.flow_timeouts.cert_button_visible)
        logging.info("[FASE 1.4] OK Boton de certificado encontrado")
    except PlaywrightTimeout:
        logging.error("[FASE 1.4] X Boton de certificado no encontrado en 20s")
        logging.error(f"[FASE 1.4] URL actual: {page.url}")
        raise

    logging.info("[FASE 1.5] Pulsando boton de certificado...")
    await boton_cert.click(timeout=config.timeouts.login, no_wait_after=True, force=True)
    await page.wait_for_timeout(config.delay_ms)

    logging.info("[FASE 1.6] Esperando salida de VALid / acceso post-login...")
    # A veces VÀLid redirige a Common Desktop y requiere una interacción humana (elegir enlace).
    # El worker NO debe quedarse bloqueado ahí: navegará a la rama (P1/P2/P3) por URL directa.
    await page.wait_for_function(config.scripts.post_login_ready, timeout=config.timeouts.login)
    logging.info(f"[FASE 1.6] OK Post-login detectado - URL: {page.url}")
    return page

