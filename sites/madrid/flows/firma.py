from __future__ import annotations
import logging
import re
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)

async def _imprimir_visor_a_pdf(popup_page: Page, nombre_pdf: str) -> Path:
    """
    Fuerza la impresión a PDF del visor de Madrid.
    Espera a que los blobs de las páginas (.pagerect) estén cargados.
    """
    # Guardar en la raíz del proyecto
    destino = Path(".") / nombre_pdf
    logger.info(f"Iniciando renderizado y captura de PDF en: {destino.absolute()}")

    try:
        # 1. Esperar a que el contenedor de las páginas PDF aparezca en el DOM
        # Según tu HTML, las páginas tienen la clase 'pagerect'
        await popup_page.wait_for_selector(".pagerect", state="visible", timeout=20000)
        
        # 2. Ocultar la interfaz del visor (toolbar) para que no salga en el PDF
        await popup_page.add_style_tag(content="#toolbar { display: none !important; }")
        
        # 3. Esperar a que el navegador termine de procesar los blobs de red
        await popup_page.wait_for_load_state("networkidle", timeout=10000)
        
        # 4. Margen de seguridad para asegurar que el motor de renderizado "dibuje" el PDF
        await popup_page.wait_for_timeout(5000)

        # 5. Ejecutar la impresión virtual (Solo funciona en modo HEADLESS)
        await popup_page.pdf(
            path=destino,
            format="A4",
            print_background=True,
            display_header_footer=False,
            margin={"top": "0cm", "right": "0cm", "bottom": "0cm", "left": "0cm"}
        )

        size = destino.stat().st_size
        if size < 5000:
            raise RuntimeError(f"El PDF generado es demasiado pequeño ({size} bytes). Verifique modo headless.")
            
        logger.info(f"✓ PDF generado exitosamente mediante impresión ({size} bytes)")
        return destino

    except Exception as e:
        logger.error(f"Error crítico durante la impresión virtual: {e}")
        # Backup: Si falla el PDF, intentamos un screenshot de alta resolución
        await popup_page.screenshot(path=Path(".") / f"emergencia_{nombre_pdf}.png", full_page=True)
        raise

async def ejecutar_firma_madrid(
    page: Page, 
    config: "MadridConfig", 
    destino_descarga: Path
) -> Page:
    """
    Flujo de firma y verificación con captura visual del justificante.
    """
    logger.info("=" * 80)
    logger.info("INICIANDO FLUJO DE FIRMA (MODO IMPRESIÓN VIRTUAL)")
    logger.info("=" * 80)

    # PASO 1: Validar botón
    await page.wait_for_selector(config.firma_registrar_selector, state="visible")
    
    # PASO 2: Click y esperar navegación
    async with page.expect_navigation(wait_until="domcontentloaded"):
        await page.click(config.firma_registrar_selector)
    
    # PASO 3: Click en Verificar y Capturar Popup
    popup_page = None
    try:
        async with page.context.expect_page(timeout=config.popup_wait_timeout) as new_page_info:
            logger.info("Haciendo click en 'Verificar documento'...")
            await page.click(config.verificar_documento_selector)
        
        popup_page = await new_page_info.value
        # Esperar a que cargue el visor (wrapper HTML)
        await popup_page.wait_for_load_state("domcontentloaded")
    except PlaywrightTimeoutError:
        raise RuntimeError("El portal de Madrid no abrió el visor del documento.")

    # PASO 4: Generar el PDF desde el visor
    # Limpiamos el nombre para que sea el del expediente
    nombre_final = destino_descarga.name if destino_descarga.name.endswith(".pdf") else f"{destino_descarga.stem}.pdf"
    
    try:
        await _imprimir_visor_a_pdf(popup_page, nombre_final)
    finally:
        # PASO 5: Limpieza
        if popup_page:
            await popup_page.close()
            logger.info("✓ Visor de documento cerrado.")

    await page.bring_to_front()
    logger.info("=" * 80)
    logger.info("PROCESO DE FIRMA E IMPRESIÓN FINALIZADO")
    logger.info("=" * 80)
    
    return page