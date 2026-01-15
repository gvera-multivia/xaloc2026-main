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
    """Graba la sesión forzando el click en el botón de la pasarela."""
    print("\n" + "!" * 75)
    print(" MODO GRABACIÓN ACTIVADO ".center(75, "!"))
    print("!" * 75 + "\n")
    
    async with async_playwright() as p:
        # Usamos launch_persistent_context para que sea más estable en la grabación
        browser = await p.chromium.launch(
            headless=False,
            channel=config.navegador.canal,
            args=config.navegador.args,
        )
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        logging.info("1. Navegando a Xaloc...")
        await page.goto(config.url_base, wait_until="networkidle")

        # Cookies
        try:
            await page.get_by_role("button", name="Acceptar").click(timeout=2000)
        except: pass

        logging.info("2. Abriendo pasarela AOC...")
        async with page.expect_popup() as popup_info:
            await page.get_by_role("link", name="Tramitació en línia").first.click()
        
        aoc_page = await popup_info.value
        await aoc_page.wait_for_load_state("domcontentloaded")

        try:
            logging.info("3. Forzando click en #btnCert...")
            # Si el click normal falla, usamos dispatch_event que suele saltarse bloqueos
            btn = aoc_page.locator("#btnCert")
            await btn.wait_for(state="visible", timeout=5000)
            await btn.dispatch_event("click") 
            logging.info("✅ Botón pulsado. Ahora el sistema te pedirá el certificado.")
        except Exception as e:
            logging.warning("No se pudo clicar automáticamente. Por favor, haz clic tú en 'Certificat Digital'.")

        print("\n" + "*" * 75)
        print(" ESPERANDO ACCIÓN DEL SISTEMA ".center(75, " "))
        print(" 1. Selecciona tu certificado en la ventana de Windows/Chrome.")
        print(" 2. Pon el PIN si es necesario.")
        print(" 3. CUANDO VEAS EL FORMULARIO DE XALOC (DNI, Nombre...), vuelve aquí.")
        print("*" * 75 + "\n")
        
        # IMPORTANTE: No guardamos hasta que la URL sea la correcta
        input(">>> PULSA ENTER AQUÍ SOLO CUANDO YA ESTÉS DENTRO DEL FORMULARIO FINAL...")

        # Guardar estado
        config.dir_auth.mkdir(exist_ok=True)
        await context.storage_state(path=str(config.auth_state_path))
        logging.info(f"💾 Sesión guardada correctamente en {config.auth_state_path}")
        
        await browser.close()

async def main():
    config = Config()
    
    # 1. Comprobamos si hay que grabar
    if not config.auth_state_path.exists() or config.auth_state_path.stat().st_size < 100:
        await realizar_login_guiado(config)
    else:
        print(f"\n✅ Usando sesión existente: {config.auth_state_path}")

    # 2. Datos de prueba
    datos = DatosMulta(
        email="test@example.com",
        num_denuncia="DEN/2024/001",
        matricula="1234ABC",
        num_expediente="EXP/2024/001",
        motivos="Texto de prueba para la alegación.",
        archivo_adjunto=None
    )
    
    print("\n🚀 Iniciando Bot de Automatización...")
    
    # 3. Ejecución
    async with XalocAsync(config) as bot:
        try:
            # Aquí es donde el bot usa las cookies guardadas
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\n🎉 ¡ÉXITO! Captura final: {screenshot_path}")
        except Exception as e:
            print(f"\n❌ Falló la ejecución: {e}")
            print("Si el error persiste, borra la carpeta 'auth' y repite el proceso.")
        finally:
            input("\nPresiona ENTER para cerrar el programa...")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())