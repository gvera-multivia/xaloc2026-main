"""
Flujo de confirmación final (sin envío real)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError

DELAY_MS = 500


async def _wait_mask_hidden(page: Page, timeout_ms: int = 8000) -> None:
    logging.info(f"-- Comprobando si existe el overlay #mask...")
    mask = page.locator("#mask")
    try:
        count = await mask.count()
        if count > 0:
            is_visible = await mask.is_visible()
            if is_visible:
                logging.info(f"!! Overlay #mask DETECTADO Y VISIBLE. Esperando hasta {timeout_ms}ms a que desaparezca...")
                await mask.wait_for(state="hidden", timeout=timeout_ms)
                logging.info("-> Overlay #mask ha desaparecido")
            else:
                logging.info("INFO Overlay #mask existe en el DOM pero no es visible")
        else:
            logging.info("INFO No se detecta el overlay #mask")
    except Exception as e:
        logging.info(f"INFO Error/Timeout esperando #mask: {e}")


async def _check_lopd(page: Page) -> None:
    logging.info("¿? Iniciando proceso de marcado LOPD...")
    
    await page.wait_for_selector("#lopdok", state="attached", timeout=60000)
    checkbox = page.locator("#lopdok").first
    
    logging.info("¿? Esperando visibilidad del checkbox #lopdok...")
    await checkbox.wait_for(state="visible", timeout=30000)
    
    logging.info("¿? Desplazando checkbox a la vista...")
    await checkbox.scroll_into_view_if_needed()

    # Primero intentar click directo (caso rápido sin overlay)
    logging.info(">> Intento 1: Marcado directo (rápido)...")
    try:
        await checkbox.check(timeout=1000)
        if await checkbox.is_checked():
            logging.info("-> Marcado directo EXITOSO")
            await page.wait_for_timeout(DELAY_MS)
            return
    except Exception as e:
        logging.info(f"!! Intento 1 fallado o interceptado: {e}")

    # Si hay overlay (#mask), esperar a que desaparezca y reintentar
    logging.info("-- Paso intermedio: Esperando posible overlay #mask...")
    await _wait_mask_hidden(page, timeout_ms=6000)
    
    logging.info(">> Intento 2: Marcado tras espera de overlay...")
    try:
        await checkbox.check(timeout=2000)
        if await checkbox.is_checked():
            logging.info("-> Marcado tras espera EXITOSO")
            await page.wait_for_timeout(DELAY_MS)
            return
    except Exception as e:
        logging.info(f"!! Intento 2 fallado: {e}")
        
    # Forzar el click si sigue bloqueado
    logging.info(">> Intento 3: Marcado FORZADO (force=True)...")
    try:
        await checkbox.check(timeout=1000, force=True)
        if await checkbox.is_checked():
            logging.info("-> Marcado forzado EXITOSO")
            await page.wait_for_timeout(DELAY_MS)
            return
    except Exception as e:
        logging.info(f"!! Intento 3 (forzado) fallado: {e}")

    # Último recurso: JavaScript
    logging.info(">> Intento FINAL: Marcado vía JavaScript (eval)...")
    ok = await page.evaluate(
        """() => {
            console.log("Iniciando fallback JS para LOPD");
            const cb = document.getElementById('lopdok');
            if (!cb) {
                console.error("No se encontró el checkbox #lopdok en el DOM");
                return false;
            }
            cb.checked = true;
            cb.dispatchEvent(new Event('click', { bubbles: true }));
            cb.dispatchEvent(new Event('change', { bubbles: true }));
            if (typeof window.checkContinuar === 'function') {
                console.log("Llamando a checkContinuar(cb)");
                window.checkContinuar(cb);
            }
            return cb.checked === true;
        }"""
    )
    if ok:
        logging.info("-> Marcado vía JavaScript EXITOSO")
        await page.wait_for_timeout(DELAY_MS)
    else:
        logging.error("!! ERROR CRÍTICO: No se pudo marcar el checkbox de ninguna forma")
        raise TimeoutError("No se pudo marcar el checkbox LOPD (#lopdok)")


async def _wait_boton_continuar(page: Page) -> None:
    logging.info("-- Esperando a que el botón 'Continuar' sea visible...")
    await page.wait_for_function(
        """() => {
            const el = document.querySelector('#botoncontinuar');
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const isVisible = style && style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
            return isVisible;
        }""",
        timeout=30000,
    )
    logging.info("-> Botón 'Continuar' detectado y visible")


async def confirmar_tramite(page: Page, screenshots_dir: Path) -> str:
    """
    Confirma el trámite y toma screenshot (NO ENVÍA).

    Returns:
        Ruta del screenshot guardado
    """

    logging.info("Marcando aceptación LOPD")
    await _check_lopd(page)

    await _wait_boton_continuar(page)

    logging.info("Avanzando a pantalla final")
    continuar = page.locator("div#botoncontinuar a").first
    await continuar.scroll_into_view_if_needed()
    await continuar.wait_for(state="visible", timeout=30000)

    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
            await continuar.click()
    except TimeoutError:
        await continuar.click()
    await page.wait_for_timeout(DELAY_MS)

    if "TramitaSign" not in page.url:
        await page.wait_for_url("**/TramitaSign**", timeout=60000)
    await page.wait_for_load_state("networkidle")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = screenshots_dir / f"xaloc_final_{timestamp}.png"
    await page.screenshot(path=screenshot_path, full_page=True)

    logging.warning("PROCESO DETENIDO - Screenshot guardado")
    logging.warning("Botón 'Enviar' NO pulsado (modo testing)")

    return str(screenshot_path)


__all__ = ["confirmar_tramite"]
