"""
Flujo de rellenado del formulario STA
"""
from playwright.async_api import Page
import logging
from config import DatosMulta


async def rellenar_formulario(page: Page, datos: DatosMulta) -> None:
    """
    Rellena el formulario STA de alegación
    
    Args:
        page: Página de Playwright
        datos: Datos de la multa a rellenar
    """
    
    logging.info("📝 Rellenando formulario de alegación")
    
    # IMPORTANTE: Esperar a que la página cargue completamente para evitar errores
    await page.wait_for_load_state("networkidle")
    
    # Campo Email
    email_input = page.locator("#contact21")
    await email_input.wait_for(state="visible", timeout=30000)
    logging.info(f"  → Email: {datos.email}")
    await email_input.fill(datos.email)
    
    # Campo Nº Denuncia
    denuncia_input = page.locator("#DinVarNUMDEN")
    await denuncia_input.wait_for(state="visible")
    logging.info(f"  → Nº Denuncia: {datos.num_denuncia}")
    await denuncia_input.fill(datos.num_denuncia)
    
    # Campo Matrícula
    matricula_input = page.locator("#DinVarMATRICULA")
    await matricula_input.wait_for(state="visible")
    logging.info(f"  → Matrícula: {datos.matricula}")
    await matricula_input.fill(datos.matricula)
    
    # Campo Nº Expediente
    expediente_input = page.locator("#DinVarNUMEXP")
    await expediente_input.wait_for(state="visible")
    logging.info(f"  → Nº Expediente: {datos.num_expediente}")
    await expediente_input.fill(datos.num_expediente)
    
    # Campo TinyMCE (dentro de iframe)
    logging.info("📝 Rellenando editor de motivos (TinyMCE)")
    
    # Esperar a que el iframe exista
    frame_loc = page.frame_locator("#DinVarMOTIUS_ifr")
    # Esperar al body dentro del iframe
    body_loc = frame_loc.locator("body#tinymce")
    await body_loc.wait_for(state="visible", timeout=30000)
    
    await body_loc.fill(datos.motivos)
    
    logging.info("✅ Formulario completado")
