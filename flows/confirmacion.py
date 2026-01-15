"""
Flujo de confirmación final (sin envío real)
"""
from playwright.async_api import Page
from pathlib import Path
from datetime import datetime
import logging


async def confirmar_tramite(page: Page, screenshots_dir: Path) -> str:
    """
    Confirma el trámite y toma screenshot (NO ENVÍA)
    
    Args:
        page: Página de Playwright
        screenshots_dir: Directorio para guardar screenshots
        
    Returns:
        Ruta del screenshot guardado
    """
    
    # 1. Marcar checkbox LOPD
    logging.info("☑️ Marcando aceptación LOPD")
    await page.locator("#lopdok").check()
    
    # 2. Esperar botón continuar
    await page.wait_for_selector("div#botoncontinuar", state="visible")
    
    # 3. Click continuar
    logging.info("➡️ Avanzando a pantalla final")
    await page.locator("div#botoncontinuar a").click()
    
    # 4. Esperar pantalla de envío
    await page.wait_for_url("**/TramitaSign", timeout=30000)
    await page.wait_for_load_state("networkidle")
    
    # 5. Screenshot de éxito
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = screenshots_dir / f"xaloc_final_{timestamp}.png"
    await page.screenshot(path=screenshot_path, full_page=True)
    
    logging.warning("🛑 PROCESO DETENIDO - Screenshot guardado")
    logging.warning("⚠️ Botón 'Enviar' NO pulsado (modo testing)")
    
    return str(screenshot_path)
