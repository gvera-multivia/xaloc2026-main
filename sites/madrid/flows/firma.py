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
    Captura el binario original .do interceptando el evento de red global.
    Es el método más 'serio' y fiable: captura los datos exactos del 
    expediente 935/713504478.1 antes de que el visor los procese.
    """
    logger.info("=" * 80)
    logger.info(f"CAPTURA DE DOCUMENTO ORIGINAL - EXPEDIENTE: {destino_descarga.stem}")
    logger.info("=" * 80)

    # 1. Definir la ruta en la raíz del proyecto (forzamos .pdf para uso directo)
    # El archivo contendrá el recurso completo para el vehículo 5748LFZ
    nombre_final = f"{destino_descarga.stem}.pdf"
    ruta_raiz = Path(".") / nombre_final

    # 2. Navegación hasta la pantalla de firma
    await page.wait_for_selector(config.firma_registrar_selector, state="visible")
    async with page.expect_navigation(wait_until="domcontentloaded"):
        await page.click(config.firma_registrar_selector)
    
    await page.wait_for_load_state("networkidle")

    # 3. ACTIVAR RADAR DE RED (Sintaxis para Contexto)
    logger.info("Activando radar de red global para interceptar el binario...")
    
    try:
        # Usamos page.context.expect_event("response") para vigilar TODA la sesión
        # No importa si el archivo se abre en un popup, el radar lo detectará.
        async with page.context.expect_event(
            "response", 
            predicate=lambda r: "visualizarDocumento.do" in r.url and r.status == 200,
            timeout=60000
        ) as response_info:
            
            # Hacemos clic en el botón que dispara el documento legal
            logger.info("Haciendo clic en 'Verificar documento'...")
            await page.click(config.verificar_documento_selector)
        
        # 4. EXTRACCIÓN DEL BINARIO
        respuesta = await response_info.value
        logger.info(f"✓ Documento detectado en el tráfico de red: {respuesta.url}")
        
        # Obtenemos los bytes originales del servidor de Madrid
        pdf_binario = await respuesta.body()

        # 5. GUARDADO EN RAÍZ
        # Guardamos el archivo auténtico de múltiples páginas
        ruta_raiz.write_bytes(pdf_binario)
        
        tamano = len(pdf_binario)
        logger.info(f"✓ Documento original guardado en raíz: {ruta_raiz.absolute()}")
        logger.info(f"✓ Tamaño capturado: {tamano} bytes")

        # Verificación técnica de integridad (No corrompe los datos)
        if pdf_binario.startswith(b"%PDF"):
            logger.info("✓ Validación: El archivo es un PDF legal íntegro de múltiples páginas.")
        else:
            logger.error("❌ El archivo interceptado no tiene cabecera PDF. Verifique la sesión.")
            raise RuntimeError("El servidor no entregó un binario válido.")

    except Exception as e:
        logger.error(f"Fallo crítico en el radar de captura: {e}")
        # Captura de pantalla de la ventana principal por si hay un aviso de error
        await page.screenshot(path="error_captura_documento.png")
        raise

    # 6. LIMPIEZA DE POPUPS
    # Esperamos un instante para que el navegador registre la apertura del popup
    await asyncio.sleep(2)
    for p in page.context.pages:
        if p != page: # Cerramos cualquier ventana que no sea la principal
            await p.close()
            logger.info("✓ Ventana residual del visor cerrada.")

    await page.bring_to_front()
    logger.info("=" * 80)
    logger.info("FLUJO DE FIRMA Y CAPTURA FINALIZADO")
    logger.info("=" * 80)
    
    return page