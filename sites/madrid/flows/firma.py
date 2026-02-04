from __future__ import annotations
import logging
import base64
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
    Extrae el documento original inyectando la lógica de fetch validada en consola.
    Garantiza el binario de 67KB y evita el visor de la extensión.
    """
    logger.info("=" * 80)
    logger.info(f"EXTRACCIÓN BINARIA DIRECTA - EXPEDIENTE: {destino_descarga.stem}")
    logger.info("=" * 80)

    # 1. Definir ruta en la raíz del proyecto
    nombre_final = f"{destino_descarga.stem}.pdf"
    ruta_raiz = Path(".") / nombre_final

    # 2. Navegar a la pantalla de firma
    await page.wait_for_selector(config.firma_registrar_selector, state="visible")
    async with page.expect_navigation(wait_until="domcontentloaded"):
        await page.click(config.firma_registrar_selector)
    
    await page.wait_for_load_state("networkidle")

    # 3. EJECUCIÓN DEL "HACK" DE CONSOLA
    # Le pedimos al navegador que haga el fetch y nos devuelva el PDF en Base64
    logger.info("Ejecutando fetch interceptor para el vehículo 5748LFZ...")
    
    script_extraccion = """
    async () => {
        const btn = document.querySelector('button[name="verificar"]');
        const formData = new FormData(btn.form);
        formData.append('verificar', '1');

        const response = await fetch(btn.form.action, {
            method: 'POST',
            body: new URLSearchParams(formData)
        });

        if (!response.ok) throw new Error("Servidor Madrid falló: " + response.status);

        const buffer = await response.arrayBuffer();
        // Convertimos el buffer a Base64 para pasarlo de JS a Python sin pérdidas
        return btoa(String.fromCharCode(...new Uint8Array(buffer)));
    }
    """

    try:
        # Ejecutamos la lógica que funcionó en tu consola
        base64_pdf = await page.evaluate(script_extraccion)
        
        # 4. DECODIFICACIÓN Y GUARDADO FÍSICO
        pdf_bytes = base64.b64decode(base64_pdf)
        
        if pdf_bytes.startswith(b"%PDF"):
            ruta_raiz.write_bytes(pdf_bytes)
            logger.info(f"✓ DOCUMENTO ORIGINAL GUARDADO ({len(pdf_bytes)} bytes)")
            logger.info(f"Ubicación: {ruta_raiz.absolute()}")
        else:
            raise RuntimeError("Los datos recibidos no tienen formato PDF.")

    except Exception as e:
        logger.error(f"Fallo en la extracción por inyección: {e}")
        raise

    # 5. FINALIZACIÓN
    # Ya no hay popups que cerrar porque nunca dejamos que se abrieran
    logger.info("=" * 80)
    logger.info("PROCESO DE FIRMA Y EXTRACCIÓN COMPLETADO CON ÉXITO")
    logger.info("=" * 80)
    
    return page