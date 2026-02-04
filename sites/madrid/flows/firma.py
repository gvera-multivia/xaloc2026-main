from __future__ import annotations
import logging
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from playwright.async_api import Page

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)

async def ejecutar_firma_madrid(
    page: Page, 
    config: "MadridConfig", 
    destino_descarga: Path
) -> Page:
    """
    Simula la acción de 'Guardar como' (Ctrl + S) interceptando el binario original.
    Guarda el documento de múltiples páginas legal en la raíz del proyecto.
    """
    logger.info("=" * 80)
    logger.info("CAPTURA PROFESIONAL: BINARIO ORIGINAL DEL AYUNTAMIENTO")
    logger.info("=" * 80)

    # 1. Definir ruta en la raíz (forzamos .do para que veas que es el original)
    nombre_archivo = f"{destino_descarga.stem}.do"
    ruta_raiz = Path(".") / nombre_archivo

    try:
        # 2. Navegar a la pantalla de firma
        await page.wait_for_selector(config.firma_registrar_selector, state="visible")
        async with page.expect_navigation(wait_until="domcontentloaded"):
            await page.click(config.firma_registrar_selector)
        
        # 3. INTERCEPCIÓN (El radar): Escuchamos en todo el contexto (incluye el popup)
        # Esto captura la respuesta que Madrid envía para 'visualizarDocumento.do'
        async with page.context.expect_response(
            lambda r: "visualizarDocumento.do" in r.url and r.status == 200,
            timeout=60000
        ) as response_info:
            
            logger.info("Haciendo clic para generar el documento...")
            await page.click(config.verificar_documento_selector)
        
        # 4. CAPTURA DE DATOS: Extraemos el cuerpo del archivo
        respuesta = await response_info.value
        binario_original = await respuesta.body()

        # 5. GUARDADO FÍSICO: Volcamos el buffer al disco en la raíz
        ruta_raiz.write_bytes(binario_original)
        
        logger.info(f"✓ Archivo original guardado: {ruta_raiz.absolute()}")
        logger.info(f"✓ Tamaño capturado: {len(binario_original)} bytes")

        # Verificación rápida de cabecera (No corrompe el archivo)
        if binario_original.startswith(b"%PDF"):
            logger.info("✓ Validación: El .do contiene un PDF válido de múltiples páginas.")

    except Exception as e:
        logger.error(f"Error crítico en la captura del documento: {e}")
        raise

    # 6. LIMPIEZA DE VENTANAS: Cerramos el visor que se quedó abierto
    await asyncio.sleep(2)
    for p in page.context.pages:
        if p != page: 
            await p.close()
            logger.info("✓ Ventana emergente del visor cerrada.")

    await page.bring_to_front()
    logger.info("=" * 80)
    logger.info("PROCESO FINALIZADO: DOCUMENTO DISPONIBLE EN RAÍZ")
    logger.info("=" * 80)
    
    return page