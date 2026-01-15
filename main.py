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
    """Lógica mejorada para capturar el popup de la AOC y el botón #btnCert."""
    print("\n" + "!" * 75)
    print(" INICIANDO GRABACIÓN DE SESIÓN (MODO POPUP) ".center(75, "!"))
    print("!" * 75 + "\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel=config.navegador.canal,
            args=config.navegador.args,
        )
        # Importante: No cargamos auth aquí, queremos una sesión limpia
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        logging.info("1. Navegando a la web de Xaloc...")
        await page.goto(config.url_base, wait_until="domcontentloaded")

        # Aceptar cookies
        try:
            await page.get_by_role("button", name="Acceptar").click(timeout=3000)
        except: pass

        # Capturar la apertura de la nueva pestaña
        logging.info("2. Pulsando 'Tramitació en línia' y esperando nueva pestaña...")
        async with page.expect_popup() as popup_info:
            await page.get_by_role("link", name="Tramitació en línia").first.click()
        
        # Esta es la página de la AOC (VÀLid)
        aoc_page = await popup_info.value
        await aoc_page.wait_for_load_state("domcontentloaded")
        logging.info(f"3. Pasarela detectada: {aoc_page.url}")

        try:
            # Ahora buscamos el botón DENTRO de la página AOC
            logging.info("4. Buscando botón #btnCert en la pasarela...")
            btn_cert = aoc_page.locator("#btnCert")
            await btn_cert.wait_for(state="visible", timeout=10000)
            
            # Al pulsar aquí, saldrá el cuadro de diálogo del sistema (Windows)
            # Playwright no puede ver ese cuadro, por eso aquí paramos.
            await btn_cert.click()
            logging.info("5. Botón pulsado. El navegador debería pedirte el certificado ahora.")
        except Exception as e:
            logging.warning(f"No se pudo pulsar #btnCert automáticamente: {e}")
            print("PULSA TÚ MISMO EN 'Certificat Digital' en la ventana del navegador.")

        print("\n" + "="*75)
        print(" ESPERANDO FINALIZACIÓN MANUAL ".center(75, " "))
        print("-" * 75)
        print(" 1. Selecciona tu certificado y pon el PIN si hace falta.")
        print(" 2. Espera a que la página cargue el formulario de Xaloc.")
        print(" 3. IMPORTANTE: No cierres ninguna pestaña.")
        print("="*75 + "\n")
        
        input(">>> CUANDO ESTÉS DENTRO DEL FORMULARIO FINAL (STA), PULSA ENTER AQUÍ...")

        # Guardamos el estado de TODO el contexto (incluye las cookies de la nueva pestaña)
        config.dir_auth.mkdir(exist_ok=True)
        await context.storage_state(path=str(config.auth_state_path))
        logging.info(f"✅ Sesión guardada en: {config.auth_state_path}")
        
        await browser.close()

async def main():
    config = Config()
    
    # Si el archivo no existe o está vacío, grabamos
    if not config.auth_state_path.exists() or config.auth_state_path.stat().st_size < 100:
        await realizar_login_guiado(config)
    
    datos = DatosMulta(
        email="test@example.com",
        num_denuncia="DEN/2024/001",
        matricula="1234ABC",
        num_expediente="EXP/2024/001",
        motivos="Texto de prueba.",
        archivo_adjunto=None
    )
    
    print("\n🚀 Iniciando automatización con sesión guardada...")
    
    async with XalocAsync(config) as bot:
        try:
            # Si el bot está bien configurado, al navegar a la URL con las cookies,
            # debería saltarse la AOC y aparecer directamente en el formulario.
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\n✅ PROCESO COMPLETADO: {screenshot_path}")
        except Exception as e:
            print(f"\n❌ Error en ejecución: {e}")
            print("Sugerencia: Borra la carpeta 'auth' e inténtalo de nuevo.")
        finally:
            input("\nPresiona ENTER para salir...")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())

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