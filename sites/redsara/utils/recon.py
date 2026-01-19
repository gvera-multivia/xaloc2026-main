import logging
from playwright.async_api import Page
from pathlib import Path

async def capturar_reconocimiento_formulario(page: Page, output_dir: Path):
    """
    Captura el código fuente y una captura de pantalla del estado inicial del formulario
    para facilitar la identificación de selectores.
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Guardar HTML
        html_content = await page.content()
        html_file = output_dir / "form_source.html"
        html_file.write_text(html_content, encoding="utf-8")
        logging.info(f"📄 Fuente del formulario guardada en: {html_file}")
        
        # 2. Guardar Captura de Pantalla
        screenshot_file = output_dir / "form_initial_state.png"
        await page.screenshot(path=str(screenshot_file), full_page=True)
        logging.info(f"📸 Captura inicial del formulario guardada en: {screenshot_file}")
        
    except Exception as e:
        logging.error(f"❌ Error durante el reconocimiento del formulario: {e}")
