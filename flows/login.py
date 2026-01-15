"""
Flujo de autenticación VÀLid para Xaloc
"""
from playwright.async_api import Page, TimeoutError
import logging
from config import Config
import re

async def ejecutar_login(page: Page, config: Config) -> None:
    logging.info(f"🌐 Navegando a {config.url_base}")
    await page.goto(config.url_base, wait_until="networkidle")
    
    # 1. Capturar la apertura de la nueva pestaña
    logging.info("🔗 Haciendo click en 'Tramitació en línia' y esperando nueva pestaña...")
    
    # Definimos el evento de espera de popup
    async with page.expect_popup() as popup_info:
        await page.get_by_role("link", name="Tramitació en línia").click()
    
    valid_page = await popup_info.value
    await valid_page.wait_for_load_state("domcontentloaded")
    logging.info(f"✅ Nueva pestaña detectada: {valid_page.url}")

    # VERIFICACIÓN: ¿Estamos ya en el formulario STA (login automático)?
    # Si las cookies funcionaron, puede que nos redirija directamente.
    if "seu.xalocgirona.cat/sta" in valid_page.url:
         logging.info("🎉 ¡Sesión válida detectada! Redirección directa al formulario.")
         return

    # Si NO estamos en STA, asumimos que estamos en VÀLid y necesitamos login
    # 2. Interactuar con el botón en la NUEVA página (valid_page)
    logging.info("⏳ Esperando el botón de certificado (Login requerido)...")
    try:
        # Usamos el data-testid que confirmamos en tu captura
        boton_cert = valid_page.locator("[data-testid='certificate-btn']")
        
        # Verificar si el botón existe antes de esperar mucho tiempo
        # Si ya estamos logueados pero la URL no cambió rápido, esto podría fallar
        if await boton_cert.count() > 0 or await valid_page.title() == "VÁLid":
             await boton_cert.wait_for(state="visible", timeout=5000)
             logging.info("✅ Botón detectado. Pulsando...")
             await boton_cert.click()
        else:
             logging.info("ℹ️ No se detectó pantalla de login VÀLid, verificando si redirige...")

    except TimeoutError:
        logging.warning("⚠️ Tiempo de espera agotado buscando botón de certificado.")
    except Exception as e:
        logging.error(f"❌ Error al interactuar con el botón en la nueva pestaña: {e}")
        await valid_page.screenshot(path="error_boton_valid.png")

    # 3. Esperar el retorno al formulario STA (en la pestaña valid_page)
    logging.info("⏳ Esperando redirección final al formulario STA...")
    try:
        await valid_page.wait_for_url(
            "**/seu.xalocgirona.cat/sta/**", 
            timeout=config.timeouts.login
        )
        logging.info("✅ Login completado con éxito")
    except TimeoutError:
        logging.error("❌ Fallo esperando redirección a STA. ¿Caducó la sesión?")
        raise