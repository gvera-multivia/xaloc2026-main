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
    Captura el PDF original utilizando el botón 'Guardar' del visor interno.
    Mueve el archivo temporal (UUID) a la raíz con el nombre del expediente.
    """
    logger.info("=" * 80)
    logger.info(f"CAPTURA OFICIAL DE DOCUMENTO: {destino_descarga.stem}")
    logger.info("=" * 80)

    # 1. Definir la ruta final en la raíz
    nombre_archivo = f"{destino_descarga.stem}.pdf"
    ruta_final = Path(".") / nombre_archivo

    # 2. Llegar a la pantalla de firma
    await page.wait_for_selector(config.firma_registrar_selector, state="visible")
    async with page.expect_navigation(wait_until="domcontentloaded"):
        await page.click(config.firma_registrar_selector)
    
    # 3. CAPTURA DEL POPUP: Abrimos la ventana del visor
    popup_page = None
    try:
        async with page.context.expect_page(timeout=60000) as popup_info:
            logger.info("Abriendo el visor de documentos...")
            await page.click(config.verificar_documento_selector)
        
        popup_page = await popup_info.value
        # Esperamos a que el visor cargue el documento del vehículo 5748LFZ
        await popup_page.wait_for_load_state("networkidle")
        logger.info(f"✓ Visor detectado en: {popup_page.url}")

        # 4. INTERACCIÓN CON EL VISOR: Clic en el botón Guardar (#save)
        # Este es el botón que viste en el HTML: <button id="save" ...>
        logger.info("Solicitando descarga oficial mediante el botón del visor...")
        
        # El visor PDF a veces está dentro de un Shadow DOM o tarda en ser clicable
        save_button = popup_page.locator("#save")
        await save_button.wait_for(state="visible", timeout=30000)

        # 5. CAPTURA DEL EVENTO DOWNLOAD: Para evitar el nombre UUID (hash)
        async with popup_page.expect_download(timeout=60000) as download_info:
            await save_button.click()
        
        download = await download_info.value
        
        # 6. GUARDADO DEFINITIVO: Convertimos el hash temporal en nuestro PDF de 3 páginas
        await download.save_as(ruta_final)
        
        logger.info(f"✓ Documento original guardado: {ruta_final.absolute()}")
        logger.info(f"✓ Tamaño: {ruta_final.stat().st_size} bytes")

    except Exception as e:
        logger.error(f"Error interactuando con el visor de Madrid: {e}")
        # Captura de pantalla del visor para ver qué botón falló
        if popup_page:
            await popup_page.screenshot(path="error_visor_botones.png")
        raise

    # 7. LIMPIEZA
    if popup_page:
        await popup_page.close()
        logger.info("✓ Ventana del visor cerrada.")

    await page.bring_to_front()
    logger.info("=" * 80)
    logger.info("DOCUMENTO RECUPERADO CON ÉXITO")
    logger.info("=" * 80)
    
    return page