"""
Flujo de rellenado del formulario STA
"""
from playwright.async_api import Page
import logging
from config import DatosMulta
async def rellenar_formulario(page: Page, datos: DatosMulta) -> None:
    logging.info("📝 Iniciando rellenado del formulario STA")

    try:
        # 1. Esperar a que el formulario sea visible (usamos el email como referencia)
        # Aumentamos el timeout por si la web es lenta
        await page.wait_for_selector("#contact21", state="visible", timeout=20000)

        # 2. Función auxiliar para rellenar con seguridad
        async def rellenar_con_fuerza(selector, valor):
            locator = page.locator(selector)
            await locator.scroll_into_view_if_needed() # Asegura que el campo esté en pantalla
            await locator.click() # Simula clic para ganar el foco
            # Usamos press_sequentially en lugar de fill. 
            # Esto simula pulsaciones de teclas una a una (más humano).
            await locator.press_sequentially(str(valor), delay=30) 
            await locator.press("Tab") # Salir del campo para disparar eventos 'change' o 'blur'

        # Rellenar campos principales
        logging.info(f"  → Email: {datos.email}")
        await rellenar_con_fuerza("#contact21", datos.email)

        logging.info(f"  → Denuncia: {datos.num_denuncia}")
        await rellenar_con_fuerza("#DinVarNUMDEN", datos.num_denuncia)

        logging.info(f"  → Matrícula: {datos.matricula}")
        await rellenar_con_fuerza("#DinVarMATRICULA", datos.matricula)

        logging.info(f"  → Expediente: {datos.num_expediente}")
        await rellenar_con_fuerza("#DinVarNUMEXP", datos.num_expediente)

        # 3. Rellenar el TinyMCE (dentro de su Iframe)
        logging.info("📝 Rellenando motivos en el Iframe...")
        
        # Localizamos el iframe por el ID que me has pasado
        iframe_motivos = page.frame_locator("#DinVarMOTIUS_ifr")
        body_editor = iframe_motivos.locator("body#tinymce")

        # Esperar a que el cuerpo del editor sea editable
        await body_editor.wait_for(state="visible", timeout=10000)
        await body_editor.click()
        
        # En TinyMCE a veces el texto se resiste. 
        # Probamos primero con fill, y si no, usamos JavaScript.
        await body_editor.fill(datos.motivos)
        
        # Verificación de seguridad para el editor:
        contenido_actual = await body_editor.inner_text()
        if not contenido_actual.strip():
            logging.warning("⚠️ El fill falló en TinyMCE, intentando vía JavaScript...")
            await body_editor.evaluate(
                "(el, texto) => el.innerHTML = '<p>' + texto + '</p>'", 
                datos.motivos
            )

        logging.info("✅ Formulario completado con éxito")

    except Exception as e:
        logging.error(f"❌ Error durante el rellenado: {str(e)}")
        # Hacemos una captura para ver qué falló exactamente
        await page.screenshot(path="fallo_formulario.png")
        raise e
