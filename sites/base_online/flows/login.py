"""
Flujo de autenticación para BASE On-line (landing -> VÀLid -> Common Desktop).
"""

from __future__ import annotations

import logging
import re
import threading

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from sites.base_online.config import BaseOnlineConfig
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


async def _esperar_dom_estable(page: Page, timeout_ms: int = 2000) -> None:
    """
    Espera a que el DOM esté estable.
    
    NOTA: No usamos 'networkidle' porque los scripts de INSUIT (accesibilidad)
    hacen peticiones de red constantes y nunca se alcanza el estado idle.
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=6000)
    except PlaywrightTimeout:
        logging.warning("Timeout esperando domcontentloaded, continuando...")
    
    try:
        await page.wait_for_load_state("load", timeout=10000)
    except PlaywrightTimeout:
        logging.warning("Timeout esperando load completo, continuando...")
    
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
    logging.info("[FASE 1.2] Buscando enlace 'Base On-line'...")
    
    estrategias = [
        ("Por rol y texto", lambda: page.get_by_role("link", name=re.compile(r"Base\s+On-?line", re.IGNORECASE)).first),
        ("Selector CSS config", lambda: page.locator(config.base_online_link_selector).first),
        ("Por href /sav/valid", lambda: page.locator("a[href*='/sav/valid']").first),
        ("Por clase logo_text", lambda: page.locator("a.logo_text:has-text('Base On-line')").first),
    ]
    
    for nombre, estrategia in estrategias:
        try:
            logging.debug(f"[FASE 1.2] Probando estrategia: {nombre}")
            enlace = estrategia()
            count = await enlace.count()
            logging.debug(f"[FASE 1.2] Estrategia '{nombre}': encontrados {count} elementos")
            
            if count > 0:
                await enlace.wait_for(state="visible", timeout=6000)
                logging.info(f"[FASE 1.2] ✓ Enlace encontrado con '{nombre}'")
                return enlace
        except PlaywrightTimeout:
            logging.warning(f"[FASE 1.2] Estrategia '{nombre}': elemento no visible en 5s")
            continue
        except Exception as e:
            logging.warning(f"[FASE 1.2] Estrategia '{nombre}' falló: {e}")
            continue
    
    raise RuntimeError("No se pudo localizar el enlace 'Base On-line' con ninguna estrategia")


async def _click_enlace_robusto(page: Page, enlace, url_destino: str) -> Page:
    """
    Intenta hacer click en el enlace con múltiples estrategias.
    Si todos los clicks fallan, navega directamente a la URL destino.
    """
    logging.info("[FASE 1.3] Intentando click en enlace...")
    
    # Asegurar que el elemento está en el viewport
    try:
        await enlace.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)  # Pequeña pausa para animaciones (demo)
    except Exception:
        pass
    
    # Intentar capturar popup si el enlace abre una nueva ventana
    logging.debug("[FASE 1.3] Método 1: Click con captura de popup")
    try:
        async with page.expect_popup(timeout=3000) as popup_info:
            await enlace.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded")
        logging.info("[FASE 1.3] ✓ Click exitoso - popup capturado")
        return popup
    except PlaywrightTimeout:
        # No hubo popup, el click pudo haber funcionado en la misma página
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] Sin popup, URL actual: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] ✓ Click exitoso - navegación en misma página")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Método 1 falló: {e}")
    
    # Intentar click forzado (ignora overlays)
    logging.debug("[FASE 1.3] Método 2: Click forzado (force=True)")
    try:
        await enlace.click(force=True)
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] URL después de click forzado: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] ✓ Click forzado exitoso")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Método 2 falló: {e}")
    
    # Intentar click via JavaScript
    logging.debug("[FASE 1.3] Método 3: Click via JavaScript")
    try:
        await page.evaluate("""
            const enlace = document.querySelector("a.logo_text[href*='/sav/valid']") 
                        || document.querySelector("a[href*='/sav/valid']");
            if (enlace) enlace.click();
        """)
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] URL después de JS click: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] ✓ Click via JavaScript exitoso")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Método 3 falló: {e}")
    
    # Último recurso: navegar directamente
    logging.warning("[FASE 1.3] Todos los clicks fallaron, navegando directamente a VÀLid")
    await page.goto(url_destino, wait_until="domcontentloaded")
    logging.info(f"[FASE 1.3] Navegación directa completada: {url_destino}")
    return page


async def ejecutar_login_base(page: Page, config: BaseOnlineConfig) -> Page:
    logging.info(f"[FASE 1.1] Navegando a landing: {config.url_base}")
    
    # IMPORTANTE: Usamos 'domcontentloaded' en lugar de 'networkidle'
    # porque los scripts de INSUIT (accesibilidad) hacen peticiones constantes
    # y 'networkidle' nunca se alcanza
    try:
        await page.goto(config.url_base, wait_until="domcontentloaded", timeout=30000)
        logging.info(f"[FASE 1.1] DOM cargado, URL actual: {page.url}")
    except PlaywrightTimeout:
        logging.error(f"[FASE 1.1] Timeout al cargar la página. Verificar conexión a internet.")
        raise
    
    # Esperar un momento para que los scripts dinámicos terminen
    logging.info("[FASE 1.1] Esperando estabilización del DOM...")
    await _esperar_dom_estable(page, timeout_ms=2000)
    await page.wait_for_timeout(getattr(config, "delay_ms", DELAY_MS))

    await _aceptar_cookies_si_aparece(page)

    enlace = await _localizar_enlace_base_online(page, config)

    page = await _click_enlace_robusto(
        page, 
        enlace, 
        url_destino="https://www.base.cat/sav/valid"
    )

    # En algunos casos, tras el primer click ya estamos autenticados y
    # redirige directamente a Common Desktop (sin pasar por certificado).
    await page.wait_for_timeout(getattr(config, "delay_ms", DELAY_MS))
    if "/commons-desktop/index" in (page.url or ""):
        logging.info("[FASE 1.4] ✓ Ya autenticado (Common Desktop), saltando certificado")
        return page

    logging.info("[FASE 1.4] Esperando el botón de certificado...")
    logging.debug(f"[FASE 1.4] URL actual: {page.url}")
    logging.debug(f"[FASE 1.4] Selector botón certificado: {config.cert_button_selector}")
    
    boton_cert = page.locator(config.cert_button_selector).first
    try:
        await boton_cert.wait_for(state="visible", timeout=20000)
        logging.info("[FASE 1.4] ✓ Botón de certificado visible")
    except PlaywrightTimeout:
        logging.error("[FASE 1.4] ✗ Botón de certificado no encontrado en 20s")
        logging.error(f"[FASE 1.4] URL actual: {page.url}")
        raise

    def _resolver_popup_windows() -> None:
        aceptar_popup_certificado(
            tabs_atras=2,
            delay_inicial=max(0.0, getattr(config, "cert_popup_delay_ms", 2000) / 1000.0),
        )

    thread_popup = threading.Thread(target=_resolver_popup_windows, daemon=True)
    thread_popup.start()

    logging.info("[FASE 1.5] Pulsando botón de certificado...")
    await boton_cert.click()
    await page.wait_for_timeout(getattr(config, "delay_ms", DELAY_MS))
    thread_popup.join(timeout=10)

    # Si tras aceptar el popup seguimos en login, reintentar Shift+Tab x2.
    await page.wait_for_timeout(4000)
    if "/commons-desktop/index" not in (page.url or ""):
        logging.warning("[FASE 1.5] Seguimos en login tras 4s; reintentando aceptación de certificado")
        thread_popup_2 = threading.Thread(
            target=aceptar_popup_certificado,
            kwargs={"tabs_atras": 2, "delay_inicial": 0.0},
            daemon=True,
        )
        thread_popup_2.start()
        thread_popup_2.join(timeout=10)

    logging.info("[FASE 1.6] Esperando acceso a Common Desktop...")
    logging.debug(f"[FASE 1.6] Patrón URL esperado: {config.url_post_login}")
    await page.wait_for_url(config.url_post_login, timeout=config.timeouts.login)
    logging.info(f"[FASE 1.6] ✓ Login completado - URL: {page.url}")
    return page
