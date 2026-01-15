import asyncio
import sys
import logging
from pathlib import Path
from playwright.async_api import async_playwright

from config import Config, DatosMulta
from xaloc_automation import XalocAsync

logging.basicConfig(level=logging.INFO, format="%(message)s")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

async def realizar_login_guiado(config: Config):
    """Lógica para grabar la sesión pulsando el botón de certificado."""
    print("\n" + "!" * 70)
    print(" INICIANDO LOGIN GUIADO - SELECCIÓN DE CERTIFICADO ".center(70, "!"))
    print("!" * 70 + "\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel=config.navegador.canal,
            args=config.navegador.args,
        )
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        logging.info("1. Navegando a %s...", config.url_base)
        await page.goto(config.url_base, wait_until="domcontentloaded")

        # Aceptar cookies si aparecen
        try:
            await page.get_by_role("button", name="Acceptar").click(timeout=3000)
        except: pass

        # Ir a la pasarela
        logging.info("2. Pulsando 'Tramitació en línia'...")
        enlace = page.get_by_role("link", name="Tramitació en línia").first
        await enlace.click()

        # ESPERAR A LA PASARELA VÀLid (AOC)
        logging.info("3. Esperando a que cargue la pasarela VÀLid (AOC)...")
        
        # Aquí es donde estaba el fallo: hay que esperar y pulsar el botón de certificado
        try:
            # Buscamos el botón por ID (btnCert) o por texto
            btn_cert = page.locator("#btnCert")
            await btn_cert.wait_for(state="visible", timeout=10000)
            
            logging.info("4. Pulsando el botón 'Certificat digital' (#btnCert)...")
            
            # Al pulsar aquí es cuando el navegador lanza el popup del sistema
            async with page.expect_popup(timeout=10000) as popup_info:
                await btn_cert.click()
            
            target_page = await popup_info.value
            logging.info("✅ Pasarela de certificado abierta.")
        except Exception as e:
            logging.warning(f"No se pudo interactuar con #btnCert automáticamente: {e}")
            print("Por favor, haz click tú mismo en 'Certificat Digital' si no se ha pulsado.")

        print("\n" + "="*75)
        print(" ACCIÓN MANUAL REQUERIDA ".center(75, " "))
        print("-" * 75)
        print(" 1. Selecciona tu CERTIFICADO en la ventana emergente del sistema.")
        print(" 2. Introduce el PIN si es necesario.")
        print(" 3. Navega hasta que veas el formulario de Xaloc (donde pones el DNI).")
        print("="*75 + "\n")
        
        input(">>> CUANDO ESTÉS DENTRO DEL FORMULARIO DE XALOC, PULSA ENTER AQUÍ...")

        # Guardar el estado después de la interacción manual
        config.dir_auth.mkdir(exist_ok=True)
        await context.storage_state(path=str(config.auth_state_path))
        logging.info("💾 Estado guardado en: %s", config.auth_state_path)
        
        await browser.close()

async def main():
    config = Config()
    
    # Si no existe el auth_state, forzamos el login guiado
    if not config.auth_state_path.exists():
        await realizar_login_guiado(config)
    
    # Ejecución normal del bot
    datos = DatosMulta(
        email="test@example.com",
        num_denuncia="DEN/2024/001",
        matricula="1234ABC",
        num_expediente="EXP/2024/001",
        motivos="Texto de prueba para la alegación.",
        archivo_adjunto=None
    )
    
    print("\n🚀 Lanzando automatización con la sesión guardada...")
    
    async with XalocAsync(config) as bot:
        try:
            # Aquí es donde bot.ejecutar_flujo_completo usará el storage_state
            # que acabamos de crear o que ya existía.
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\n✅ ÉXITO. Captura guardada en: {screenshot_path}")
        except Exception as e:
            print(f"\n❌ Error: {e}")
        finally:
            input("\nPresiona ENTER para finalizar...")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())