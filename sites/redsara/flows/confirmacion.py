from playwright.async_api import Page
import logging
import asyncio

async def enviar_solicitud(page: Page) -> str:
    """
    Acción final de revisión y pausa en RedSARA demo.
    """
    logging.info("🚀 Avanzando a pantalla de Confirmación...")
    
    boton_siguiente = page.get_by_role("button", name="Siguiente") 
    if not await boton_siguiente.count():
        boton_siguiente = page.locator("button:has-text('Siguiente')")

    if await boton_siguiente.count():
        await boton_siguiente.first.click()
    else:
        logging.warning("No se encontró botón Siguiente.")

    logging.info("⏳ Esperando pantalla de confirmación...")
    
    selector_check = 'dnt-checkbox[formcontrolname="checkTerms"]'
    try:
        await page.wait_for_selector(selector_check, timeout=10000)
        logging.info("✅ Marcando checkbox de conformidad...")
        await page.locator(selector_check).click()
        await asyncio.sleep(1)
        
        # En una estructura real, aquí se capturaría el screenshot final en la ruta de logs/screenshots configurada
        logging.info("📸 Captura final sugerida en pantalla de confirmación.")
    except Exception:
        logging.error("No se encontró el checkbox de términos 'checkTerms'")
        raise

    logging.info("🛑 PAUSA SOLICITADA: No se firma en modo demo.")
    return "NO_FIRMADO_DEMO"
