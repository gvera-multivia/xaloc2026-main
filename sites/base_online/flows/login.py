"""
Flujo de autenticación para BASE On-line (landing -> VÀLid -> Common Desktop).
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from sites.base_online.config import BaseOnlineConfig

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

    await page.wait_for_timeout(timeout_ms)


async def _localizar_enlace_base_online(page: Page, config: BaseOnlineConfig):
    """
    Intenta localizar el enlace 'Base On-line' usando múltiples estrategias.
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

    try:
        await enlace.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
    except Exception:
        pass

    logging.debug("[FASE 1.3] Método 1: Click con captura de popup")
    try:
        async with page.expect_popup(timeout=3000) as popup_info:
            await enlace.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("domcontentloaded")
        logging.info("[FASE 1.3] ✓ Click exitoso - popup capturado")
        return popup
    except PlaywrightTimeout:
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] Sin popup, URL actual: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] ✓ Click exitoso - navegación en misma página")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Método 1 falló: {e}")

    logging.debug("[FASE 1.3] Método 2: Click forzado")
    try:
        await enlace.click(force=True, timeout=3000)
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] URL después de click forzado: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] ✓ Click forzado exitoso")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Método 2 falló: {e}")

    logging.debug("[FASE 1.3] Método 3: Click via JavaScript")
    try:
        await page.evaluate(
            """
            const enlace = document.querySelector("a.logo_text[href*='/sav/valid']")
                        || document.querySelector("a[href*='/sav/valid']");
            if (enlace) enlace.click();
            """
        )
        await page.wait_for_load_state("domcontentloaded")
        logging.debug(f"[FASE 1.3] URL después de JS click: {page.url}")
        if "/sav/valid" in page.url or "valid.aoc.cat" in page.url:
            logging.info("[FASE 1.3] ✓ Click via JavaScript exitoso")
            return page
    except Exception as e:
        logging.warning(f"[FASE 1.3] Método 3 falló: {e}")

    logging.warning("[FASE 1.3] Todos los clicks fallaron, navegando directamente a VÀLid")
    await page.goto(url_destino, wait_until="domcontentloaded")
    logging.info(f"[FASE 1.3] Navegación directa completada: {url_destino}")
    return page


async def ejecutar_login_base(page: Page, config: BaseOnlineConfig) -> Page:
    logging.info(f"[FASE 1.1] Navegando a landing: {config.url_base}")

    try:
        await page.goto(config.url_base, wait_until="domcontentloaded", timeout=30000)
        logging.info(f"[FASE 1.1] DOM cargado, URL actual: {page.url}")
    except PlaywrightTimeout:
        logging.error("[FASE 1.1] Timeout al cargar la página. Verificar conexión a internet.")
        raise

    logging.info("[FASE 1.1] Esperando estabilización del DOM...")
    await _esperar_dom_estable(page, timeout_ms=2000)
    await page.wait_for_timeout(getattr(config, "delay_ms", DELAY_MS))

    await _aceptar_cookies_si_aparece(page)

    enlace = await _localizar_enlace_base_online(page, config)
    page = await _click_enlace_robusto(page, enlace, url_destino="https://www.base.cat/sav/valid")

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

    logging.info("[FASE 1.5] Pulsando botón de certificado...")
    await boton_cert.click(timeout=config.timeouts.login, no_wait_after=True)
    await page.wait_for_timeout(getattr(config, "delay_ms", DELAY_MS))

    logging.info("[FASE 1.6] Esperando salida de VÀLid / acceso post-login...")
    # A veces VÀLid redirige a Common Desktop y requiere una interacción humana (elegir enlace).
    # El worker NO debe quedarse bloqueado ahí: navegará a la rama (P1/P2/P3) por URL directa.
    await page.wait_for_function(
        """() => {
          const u = (location && location.href) ? location.href : '';
          return u.includes('/commons-desktop/index')
            || u.includes('baseonline.cat/pst/flow/')
            || (!u.includes('valid.aoc.cat') && !u.includes('cert.valid.aoc.cat'));
        }""",
        timeout=config.timeouts.login,
    )
    logging.info(f"[FASE 1.6] ✓ Post-login detectado - URL: {page.url}")
    return page

