"""
Flujo de confirmación final con pausa interactiva y envío real
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError

DELAY_MS = 500
RECEIPT_WAIT_TIMEOUT_MS = 120000


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


def _esperar_confirmacion_usuario() -> None:
    """
    Pausa la ejecución esperando que el usuario presione Enter para confirmar el envío.
    """
    print("\n" + "="*80)
    print("⚠️  PAUSA INTERACTIVA")
    print("="*80)
    print("")
    print("El formulario está listo para enviar.")
    print("")
    print("🔍 Por favor, revisa que todo esté correcto en el navegador.")
    print("")
    print("IMPORTANTE: Una vez que presiones Enter, se enviará el formulario REALMENTE.")
    print("")
    print("👉 Presiona Enter para CONFIRMAR el envío y continuar...")
    print("   (o presiona Ctrl+C para cancelar)")
    print("")
    print("="*80)
    
    try:
        input()
        logging.info("✓ Usuario confirmó el envío. Procediendo...")
    except KeyboardInterrupt:
        logging.warning("⚠️  Usuario canceló el envío con Ctrl+C")
        print("\n\n❌ Proceso cancelado por el usuario.")
        sys.exit(0)


async def _pulsar_boton_enviar(page: Page) -> None:
    """
    Pulsa el botón de enviar en la página TramitaSign.
    """
    logging.info("🚀 Localizando botón de envío...")
    
    # Intentar diferentes selectores para localizar el botón
    selectores = [
        "a.boton-style.naranja[onclick*='comprobar']",  # Selector específico para el botón de enviar
        "a[onclick*='comprobar()']",  # Fallback: cualquier enlace con onclick comprobar
        "a.naranja:has-text('Enviar')",  # Fallback: enlace naranja con texto Enviar
        "input[type='button'][value*='Enviar']",  # Fallback: el selector antiguo por si acaso
    ]
    
    boton_enviar = None
    for selector in selectores:
        try:
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=5000)
            boton_enviar = locator
            logging.info(f"✓ Botón encontrado con selector: {selector}")
            break
        except TimeoutError:
            logging.info(f"!! No se encontró el botón con selector: {selector}")
            continue
    
    if not boton_enviar:
        logging.error("❌ No se pudo localizar el botón de envío con ningún selector")
        raise TimeoutError("No se encontró el botón de envío")
    
    await boton_enviar.scroll_into_view_if_needed()
    logging.info("📤 Pulsando botón de ENVIAR...")
    
    try:
        # Esperamos navegación tras el click
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=RECEIPT_WAIT_TIMEOUT_MS):
            await boton_enviar.click()
        logging.info("✓ Formulario enviado exitosamente")
    except TimeoutError:
        # Si no hay navegación inmediata, intentar click de todas formas
        logging.warning("Timeout esperando navegación, intentando click directo...")
        await boton_enviar.click()
        await page.wait_for_timeout(2000)
    
    await page.wait_for_timeout(DELAY_MS)


async def _esperar_pagina_justificante(page: Page, timeout_ms: int = RECEIPT_WAIT_TIMEOUT_MS) -> None:
    """
    Espera a que la página redirija automáticamente a la página del justificante.
    """
    logging.info("⏳ Esperando redirección automática a página del justificante...")
    
    try:
        await page.wait_for_url("**/TramitaJustif**", timeout=timeout_ms)
        logging.info("✓ Redirigido a página del justificante")
    except TimeoutError:
        current_url = page.url
        logging.error(f"❌ Timeout esperando redirección. URL actual: {current_url}")
        raise TimeoutError(
            f"No se redirigió a la página del justificante. URL actual: {current_url}"
        )
    
    # Esperar a que la página esté completamente cargada
    await page.wait_for_load_state("networkidle", timeout=30000)
    logging.info("✓ Página del justificante cargada completamente")


async def confirmar_tramite(
    page: Page,
    screenshots_dir: Path,
    *,
    tiempo_espera_post_envio: int = 10,
) -> str:
    """
    Confirma el trámite con pausa interactiva y envía el formulario realmente.
    
    Args:
        page: Página de Playwright
        screenshots_dir: Carpeta donde guardar screenshots
        tiempo_espera_post_envio: Segundos a esperar tras enviar antes de proceder

    Returns:
        Ruta del screenshot de la página del justificante
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

    # Screenshot ANTES del envío
    timestamp_pre = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_pre = screenshots_dir / f"xaloc_pre_envio_{timestamp_pre}.png"
    await page.screenshot(path=screenshot_pre, full_page=True)
    logging.info(f"Screenshot pre-envío guardado: {screenshot_pre}")

    # ⚠️ PAUSA INTERACTIVA ⚠️
    _esperar_confirmacion_usuario()

    # Enviar formulario REALMENTE
    await _pulsar_boton_enviar(page)
    
    # Esperar tiempo configurable para que la página procese el envío
    if tiempo_espera_post_envio > 0:
        logging.info(f"⏳ Esperando {tiempo_espera_post_envio}s para que la página se actualice...")
        await page.wait_for_timeout(tiempo_espera_post_envio * 1000)
    
    # Esperar redirección automática a página del justificante
    await _esperar_pagina_justificante(page)

    # Screenshot de la página del justificante
    timestamp_post = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_post = screenshots_dir / f"xaloc_justificante_{timestamp_post}.png"
    await page.screenshot(path=screenshot_post, full_page=True)
    logging.info(f"✓ Screenshot del justificante guardado: {screenshot_post}")

    return str(screenshot_post)


__all__ = ["confirmar_tramite"]
