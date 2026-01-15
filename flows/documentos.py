"""
Flujo de subida de documentos
"""
from playwright.async_api import Page
from pathlib import Path
import logging


async def subir_documento(page: Page, archivo: Path) -> None:
    """
    Sube un documento adjunto al trámite
    
    Args:
        page: Página de Playwright
        archivo: Ruta al archivo a subir
    """
    
    if not archivo or not archivo.exists():
        logging.info("📂 Sin archivo para adjuntar, saltando...")
        return
    
    logging.info(f"📂 Subiendo: {archivo.name}")
    
    # Abrir modal de carga
    await page.locator("a.docs").click()
    await page.wait_for_selector("#fichero", state="visible")
    
    # Subir archivo
    await page.locator("#fichero").set_input_files(archivo)
    
    # Esperar procesamiento
    await page.wait_for_timeout(2000)
    await page.wait_for_load_state("networkidle")
    
    logging.info("✅ Documento subido")
