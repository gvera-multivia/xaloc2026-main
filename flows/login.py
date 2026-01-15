"""
Flujo de autenticación VÀLid para Xaloc.
"""

import logging
import re

from playwright.async_api import Page, TimeoutError

from config import Config


async def _aceptar_cookies_si_aparece(page: Page) -> None:
    posibles = [
        r"Acceptar",
        r"Aceptar",
        r"Aceptar todo",
        r"Aceptar todas",
        r"Accept all",
        r"Entesos",
    ]
    for patron in posibles:
        boton = page.get_by_role("button", name=re.compile(patron, re.IGNORECASE))
        try:
            if await boton.count() > 0:
                await boton.first.click(timeout=1500)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def ejecutar_login(page: Page, config: Config) -> None:
    logging.info(f"🌐 Navegando a {config.url_base}")
    await page.goto(config.url_base, wait_until="networkidle")
    
    # 0. Gestionar cookies (si aparecen)
    await _aceptar_cookies_si_aparece(page)

    # 1. Localizar enlace de trámite
    logging.info("🔗 Localizando enlace 'Tramitació en línia'...")
    enlace = page.get_by_role(
        "link", 
        name=re.compile(r"Tramitaci[oó] en l[ií]nia", re.IGNORECASE)
    ).first
    await enlace.wait_for(state="visible", timeout=10000)

    # 2. CAPTURA DE NUEVA PESTAÑA (La solución clave)
    logging.info("🚀 Pulsando enlace y esperando nueva pestaña de VÀLid...")
    try:
        async with page.expect_popup() as popup_info:
            await enlace.click()
        
        # 'valid_page' es ahora nuestro objeto de control para la pasarela
        valid_page = await popup_info.value
        await valid_page.wait_for_load_state("domcontentloaded")
        logging.info(f"✅ Pestaña detectada: {valid_page.url}")

    except Exception as e:
        logging.error(f"❌ Error crítico: No se abrió la pasarela de autenticación: {e}")
        await page.screenshot(path="error_apertura_pasarela.png")
        return

    # 3. INTERACCIÓN EN LA NUEVA PESTAÑA
    logging.info("⏳ Esperando el botón de certificado...")
    # Usamos un selector combinado para asegurar que lo encuentre por ID o por Test-ID
    selector_boton = "#btnContinuaCert, [data-testid='certificate-btn']"
    
    try:
        boton_cert = valid_page.locator(selector_boton).first
        
        # Esperar a que sea visible (importante para evitar errores de interatividad)
        await boton_cert.wait_for(state="visible", timeout=15000)
        
        logging.info("✅ Botón detectado. Pulsando para iniciar identificación...")
        await boton_cert.click()
        
    except Exception as e:
        logging.error(f"❌ No se pudo interactuar con el botón en la nueva pestaña: {e}")
        await valid_page.screenshot(path="error_boton_valid.png")
        return

    # 4. ESPERAR REDIRECCIÓN FINAL AL FORMULARIO
    # Una vez pulsado el certificado, la pestaña valid_page nos llevará al formulario STA
    logging.info("⏳ Esperando retorno al formulario STA...")
    try:
        await valid_page.wait_for_url(
            "**/seu.xalocgirona.cat/sta/**", 
            timeout=config.timeouts.login
        )
        logging.info("✅ Login completado con éxito - Formulario STA cargado")
    except Exception as e:
        logging.error(f"❌ Tiempo excedido esperando el formulario final: {e}")
        await valid_page.screenshot(path="error_timeout_sta.png")

