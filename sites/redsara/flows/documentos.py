from playwright.async_api import Page
from pathlib import Path
from typing import List
import logging
from ..data_models import ArchivoAdjunto
from utils.validators import validar_archivo_subido

async def subir_documentacion(page: Page, archivos: List[ArchivoAdjunto]) -> None:
    """
    Maneja la subida de múltiples archivos en RedSARA.
    """
    logging.info(f"📂 Iniciando subida de {len(archivos)} documentos...")
    
    for archivo in archivos:
        if not archivo.ruta.exists():
            logging.error(f"❌ Archivo no encontrado en disco: {archivo.ruta}")
            raise FileNotFoundError(f"Archivo no existe: {archivo.ruta}")
            
        logging.info(f"⬆ Subiendo: {archivo.ruta.name}")
        
        try:
             boton = page.locator('dnt-button[icon="Upload"]')
             if not await boton.count():
                  boton = page.get_by_text("Explorar documentos")
             
             if await boton.count() > 0:
                  async with page.expect_file_chooser() as fc_info:
                      await boton.first.click(force=True)
                  file_chooser = await fc_info.value
                  await file_chooser.set_files(archivo.ruta)
             else:
                  logging.warning("No se detectó botón explorar, intentando input oculto")
                  input_file = page.locator('input[type="file"]').first
                  await input_file.set_input_files(archivo.ruta)

             await validar_archivo_subido(page, archivo.ruta.name)
            
        except Exception as e:
            logging.error(f"Error subiendo archivo {archivo.ruta}: {e}")
            raise

        await page.wait_for_timeout(1000)
    
    logging.info("✓ Todos los documentos subidos y verificados")
