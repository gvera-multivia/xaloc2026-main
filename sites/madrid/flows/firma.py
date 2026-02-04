from __future__ import annotations
import logging
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)

async def ejecutar_firma_madrid(
    page: Page, 
    config: "MadridConfig", 
    destino_descarga: Path
) -> Page:
    """
    Captura el archivo original .do directamente desde el evento de descarga.
    Funciona perfectamente en modo VISIBLE.
    """
    logger.info("=" * 80)
    logger.info("INICIANDO DESCARGA DE ARCHIVO ORIGINAL .DO")
    logger.info("=" * 80)

    # 1. Definir la ruta en la raíz con extensión .do
    # Usamos el nombre base (ej: verificacion_87543.0) pero forzamos .do
    nombre_do = f"{destino_descarga.stem}.do"
    ruta_raiz = Path(".") / nombre_do

    # 2. Llegar a la página donde está el botón
    try:
        await page.wait_for_selector(config.firma_registrar_selector, state="visible")
        async with page.expect_navigation(wait_until="domcontentloaded"):
            await page.click(config.firma_registrar_selector)
        
        await page.wait_for_load_state("networkidle")
    except Exception as e:
        logger.error(f"Error llegando a la pantalla de descarga: {e}")
        raise

    # 3. CAPTURA DEL DOWNLOAD: El momento clave
    logger.info(f"Esperando descarga de: {nombre_do}")
    
    try:
        # Preparamos el escuchador de descargas de Playwright
        async with page.expect_download(timeout=60000) as download_info:
            # Hacemos clic en 'Verificar documento'
            # Este botón dispara el stream del archivo .do
            await page.click(config.verificar_documento_selector)
        
        download = await download_info.value
        
        # 4. GUARDADO: Salvamos el archivo en la raíz
        # Playwright espera a que el servidor termine de enviar todos los bytes
        await download.save_as(ruta_raiz)
        
        size = ruta_raiz.stat().st_size
        logger.info(f"✓ Archivo .do descargado correctamente ({size} bytes)")
        logger.info(f"Ubicación: {ruta_raiz.absolute()}")

        if size < 2000:
            logger.warning("⚠️ El archivo es muy pequeño, podría ser un error del servidor.")

    except Exception as e:
        logger.error(f"Fallo al capturar la descarga: {e}")
        # Si falla el download, es posible que Madrid haya abierto un popup con el error
        await page.screenshot(path="error_descarga_do.png")
        raise

    # 5. LIMPIEZA: Cerrar posibles popups residuales
    await asyncio.sleep(1)
    for p in page.context.pages:
        if p != page:
            await p.close()
            logger.info("✓ Ventana emergente cerrada.")

    await page.bring_to_front()
    logger.info("=" * 80)
    logger.info("PROCESO DE DESCARGA FINALIZADO")
    logger.info("=" * 80)
    
    return page