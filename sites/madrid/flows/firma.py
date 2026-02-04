"""
Flujo de firma y verificación de documento para Madrid Ayuntamiento mediante impresión virtual.

Pasos:
1. Click en "Firma y registrar" (btRedireccion)
2. Esperar navegación a SIGNA_WBFIRMAR/solicitarFirma.do
3. Click en "Verificar documento"
4. Capturar popup con el visor del documento
5. Generar PDF mediante impresión virtual (Print to PDF)
6. Cerrar popup y volver a ventana principal
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)


def _extraer_jsessionid(url: str) -> str:
    """Extrae el jsessionid de una URL."""
    match = re.search(r'jsessionid=([^&;/?]+)', url)
    if match:
        return match.group(1)
    raise ValueError(f"No se pudo extraer jsessionid de la URL: {url}")


async def _imprimir_pdf_desde_popup(popup_page: Page, nombre_archivo: str) -> Path:
    """
    Utiliza el motor de Chromium para imprimir el contenido del popup a un PDF físico.
    IMPORTANTE: Solo funciona si Playwright se ejecuta en modo HEADLESS.
    """
    # Guardamos en la raíz del proyecto
    destino = Path(".") / nombre_archivo
    logger.info(f"Iniciando impresión virtual a PDF: {destino.absolute()}")

    try:
        # 1. Esperar a que el visor termine de cargar el documento y la red esté inactiva
        await popup_page.wait_for_load_state("networkidle", timeout=30000)
        
        # 2. Pequeño margen para asegurar el renderizado de fuentes y firmas
        await popup_page.wait_for_timeout(3000)

        # 3. Generar el PDF
        # Nota: 'print_background' es clave para que salgan los logos del Ayuntamiento
        await popup_page.pdf(
            path=destino,
            format="A4",
            print_background=True,
            margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"}
        )

        size = destino.stat().st_size
        logger.info(f"✓ PDF generado con éxito ({size} bytes)")
        
        if size < 5000:
            logger.warning("⚠️ El PDF generado es sospechosamente pequeño, revisa el modo headless.")
            
        return destino

    except Exception as e:
        logger.error(f"Error durante la impresión virtual a PDF: {e}")
        raise


async def ejecutar_firma_madrid(
    page: Page, 
    config: "MadridConfig", 
    destino_descarga: Path
) -> Page:
    """
    Ejecuta el flujo completo de firma y captura el documento final.
    """
    logger.info("=" * 80)
    logger.info("INICIANDO FLUJO DE FIRMA E IMPRESIÓN VIRTUAL")
    logger.info("=" * 80)

    # =========================================================================
    # PASO 1: Validar botón 'Firma y registrar'
    # =========================================================================
    logger.info("Validando presencia del botón 'Firma y registrar'...")
    try:
        await page.wait_for_selector(config.firma_registrar_selector, state="visible", timeout=config.default_timeout)
        logger.info("✓ Botón 'Firma y registrar' encontrado")
    except PlaywrightTimeoutError:
        raise RuntimeError(f"No se encontró el botón 'Firma y registrar' ({config.firma_registrar_selector})")

    # =========================================================================
    # PASO 2: Click y Navegación
    # =========================================================================
    logger.info("Haciendo click en 'Firma y registrar'...")
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.firma_navigation_timeout):
            await page.click(config.firma_registrar_selector)
        logger.info(f"✓ Navegación completada. URL actual: {page.url}")
    except PlaywrightTimeoutError:
        raise RuntimeError("Timeout esperando navegación tras 'Firma y registrar'")

    # =========================================================================
    # PASO 3 y 4: Click 'Verificar' y Captura de Popup
    # =========================================================================
    logger.info("Preparando click en 'Verificar documento'...")
    await page.wait_for_selector(config.verificar_documento_selector, state="visible")

    popup_page = None
    try:
        async with page.context.expect_page(timeout=config.popup_wait_timeout) as new_page_info:
            logger.info("Haciendo click en 'Verificar documento'...")
            await page.click(config.verificar_documento_selector)
        
        popup_page = await new_page_info.value
        await popup_page.wait_for_load_state("domcontentloaded")
        logger.info(f"✓ Popup capturado con URL: {popup_page.url}")
    except PlaywrightTimeoutError:
        raise RuntimeError("No se abrió el popup de verificación a tiempo.")

    # =========================================================================
    # PASO 5: Extraer jsessionid (Opcional, para log)
    # =========================================================================
    try:
        jsid = _extraer_jsessionid(popup_page.url)
        logger.info(f"✓ jsessionid detectado: {jsid[:15]}...")
    except Exception:
        logger.warning("No se pudo extraer jsessionid, continuando con impresión...")

    # =========================================================================
    # PASO 6: Generar PDF (Versión Impresión)
    # =========================================================================
    # Usamos el nombre del archivo definido originalmente, pero lo guardaremos en la raíz
    nombre_final = destino_descarga.name if destino_descarga.name.endswith(".pdf") else f"{destino_descarga.stem}.pdf"
    
    try:
        # Llamamos a la función de impresión virtual
        await _imprimir_pdf_desde_popup(popup_page, nombre_final)
    except Exception as e:
        logger.error(f"Fallo en la impresión del documento: {e}")
        # Captura de pantalla de emergencia por si el PDF falla
        await popup_page.screenshot(path=f"error_captura_{nombre_final}.png", full_page=True)
        raise

    # =========================================================================
    # PASO 7: Cierre y vuelta
    # =========================================================================
    logger.info("Cerrando popup y volviendo a ventana principal...")
    await popup_page.close()
    await page.bring_to_front()
    
    logger.info("=" * 80)
    logger.info("FLUJO DE FIRMA Y VERIFICACIÓN COMPLETADO CON ÉXITO")
    logger.info("=" * 80)
    
    return page