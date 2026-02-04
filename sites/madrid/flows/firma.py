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
    Captura el binario original del portal de Madrid interceptando la respuesta.
    Evita el error de Timeout de 'download' al capturar el flujo de datos directamente.
    """
    logger.info("=" * 80)
    logger.info("INICIANDO CAPTURA DE ARCHIVO ORIGINAL .DO (MODO RED)")
    logger.info("=" * 80)

    # 1. Definir la ruta en la raíz del proyecto
    # Basado en el expediente 935/713504478.1 mencionado en el documento
    nombre_do = f"{destino_descarga.stem}.do"
    ruta_raiz = Path(".") / nombre_do

    # 2. Llegar a la pantalla de firma (mismo flujo previo)
    try:
        await page.wait_for_selector(config.firma_registrar_selector, state="visible")
        async with page.expect_navigation(wait_until="domcontentloaded"):
            await page.click(config.firma_registrar_selector)
        await page.wait_for_load_state("networkidle")
    except Exception as e:
        logger.error(f"Error en navegación previa: {e}")
        raise

    # 3. INTERCEPCIÓN DE RED: Capturar los bytes del .do
    logger.info(f"Preparando captura de red para: {nombre_do}")
    
    try:
        # Preparamos la escucha de la respuesta ANTES del clic
        # Buscamos la URL que contiene 'visualizarDocumento.do'
        async with page.expect_response(
            lambda r: "visualizarDocumento.do" in r.url and r.status == 200,
            timeout=60000
        ) as response_info:
            
            # Hacemos clic en el botón que genera el documento para el vehículo 5748LFZ
            await page.click(config.verificar_documento_selector)
        
        # Obtenemos el objeto respuesta una vez el clic ha disparado la carga
        respuesta = await response_info.value
        logger.info(f"✓ Respuesta interceptada de: {respuesta.url}")
        
        # Extraemos los bytes originales del servidor
        binario_datos = await respuesta.body()
        
        # 4. GUARDADO FÍSICO: Escribimos el archivo .do en la raíz
        ruta_raiz.write_bytes(binario_datos)
        
        tamano = len(binario_datos)
        logger.info(f"✓ Archivo .do guardado en la raíz ({tamano} bytes)")
        logger.info(f"Ruta: {ruta_raiz.absolute()}")

        if tamano < 2000:
            logger.warning("⚠️ El archivo capturado es muy pequeño, revise si es un error HTML.")

    except Exception as e:
        logger.error(f"Fallo crítico interceptando el documento: {e}")
        await page.screenshot(path="error_intercepcion_madrid.png")
        raise

    # 5. LIMPIEZA: Cerrar el popup que Madrid abre automáticamente
    await asyncio.sleep(2) # Tiempo para que el navegador registre la nueva ventana
    for p in page.context.pages:
        if p != page:
            await p.close()
            logger.info("✓ Ventana residual del visor cerrada.")

    await page.bring_to_front()
    logger.info("=" * 80)
    logger.info("PROCESO DE CAPTURA FINALIZADO")
    logger.info("=" * 80)
    
    return page