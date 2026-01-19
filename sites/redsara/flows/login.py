from playwright.async_api import Page, TimeoutError
import logging
from ..config import RedSaraConfig
from utils.validators import validar_elemento_visible, validar_texto_en_pagina

async def ejecutar_login(page: Page, config: RedSaraConfig) -> None:
    """
    Flujo completo de acceso a REDSARA hasta llegar al formulario de Nuevo Registro.
    Maneja sesión existente o nueva autenticación.
    """
    url_base = config.url_base
    logging.info(f"🌐 Navegando a {url_base}")
    
    await page.goto(url_base, wait_until="networkidle")
    
    # 1. Click en trámite "Nuevo registro/Inscripción"
    selector_nuevo_registro = ".dnt-link.dnt-link--l" 
    
    await validar_elemento_visible(page, selector_nuevo_registro, descripcion="Botón Nuevo Registro")
    await page.locator(selector_nuevo_registro).first.click()
    
    # 2. Detección de login
    try:
        # Buscamos botón de certificado con un timeout corto
        boton_certificado = page.get_by_role("button", name="Acceso DNIe / Certificado")
        
        await boton_certificado.wait_for(state="visible", timeout=5000)
        
        logging.info("🔐 Se requiere autenticación. Seleccionando certificado...")
        await boton_certificado.click()
        
        # Esperamos a que la URL cambie al formulario
        logging.info("⏳ Esperando redirección al formulario tras certificado...")
        await page.wait_for_url("**/nuevo-registro", timeout=config.timeouts.general)
        
    except TimeoutError:
        logging.info("✅ Parece que ya hay sesión activa (no apareció botón de login)")
    
    # 3. Validación final: Estamos en el formulario
    logging.info("🔍 Validando carga del formulario...")
    await validar_texto_en_pagina(page, "Datos del interesado", timeout=10000)
    
    logging.info("✓ Login/Acceso completado exitosamente")
