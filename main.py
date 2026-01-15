import asyncio
import sys
import logging
from pathlib import Path
from playwright.async_api import async_playwright

from config import Config, DatosMulta
from xaloc_automation import XalocAsync

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

async def realizar_login_guiado(config: Config):
    """Graba la sesión imitando el comportamiento exacto del bot."""
    print("\n" + "="*75)
    print(" CONFIGURACIÓN DE SESIÓN INICIAL ".center(75, " "))
    print("="*75 + "\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel=config.navegador.canal)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        logging.info("1. Navegando a Xaloc...")
        await page.goto(config.url_base, wait_until="networkidle")
        
        # Aceptar cookies
        try:
            await page.get_by_role("button", name="Acceptar").click(timeout=2000)
        except: pass

        logging.info("2. Esperando click en 'Tramitació en línia'...")
        # Usamos el mismo método que el bot
        async with page.expect_popup() as popup_info:
            await page.get_by_role("link", name="Tramitació en línia").first.click()
        
        aoc_page = await popup_info.value
        await aoc_page.wait_for_load_state("domcontentloaded")

        # 3. INTENTO DE CLICK EN BOTÓN AZUL (Mismo método que el bot)
        logging.info("3. Intentando pulsar 'Certificat Digital' (#btnCert)...")
        try:
            btn = aoc_page.locator("#btnCert")
            await btn.wait_for(state="visible", timeout=8000)
            # Pequeña pausa para evitar detección de bot
            await asyncio.sleep(1) 
            await btn.click()
            logging.info("✅ Botón de certificado pulsado.")
        except Exception as e:
            logging.warning("⚠️ No se pudo pulsar automáticamente. PULSALO TÚ EN EL NAVEGADOR.")

        print("\n" + "!" * 75)
        print(" ACCIÓN REQUERIDA EN EL NAVEGADOR ".center(75, "!"))
        print(" 1. Selecciona tu certificado y pon el PIN.")
        print(" 2. Navega hasta que veas el FORMULARIO DE XALOC (DNI, Nombre...).")
        print(" 3. NO CIERRES NADA.")
        print("!" * 75 + "\n")

        # Bucle de espera inteligente: detectamos cuándo llegas al destino
        print("Esperando a que la URL cambie a la Sede Electrónica de Xaloc...")
        while "seu.xalocgirona.cat/sta" not in aoc_page.url:
            await asyncio.sleep(1)
        
        print(f"\n✅ Formulario detectado en: {aoc_page.url}")
        input(">>> Pulsa ENTER aquí para guardar esta sesión permanentemente...")

        # GUARDAR ESTADO Y URL FINAL
        config.dir_auth.mkdir(exist_ok=True)
        await context.storage_state(path=str(config.auth_state_path))
        
        # Guardamos la URL del formulario, no la de la pasarela
        with open(config.dir_auth / "last_url.txt", "w") as f:
            f.write(aoc_page.url)
            
        logging.info(f"💾 Sesión guardada en {config.auth_state_path}")
        await browser.close()

async def main():
    config = Config()
    
    # Si no hay sesión válida, grabamos una
    if not config.auth_state_path.exists() or config.auth_state_path.stat().st_size < 100:
        await realizar_login_guiado(config)
    
    datos = DatosMulta(
        email="test@example.com",
        num_denuncia="DEN/2024/001",
        matricula="1234ABC",
        num_expediente="EXP/2024/001",
        motivos="Alegación de prueba.",
        archivo_adjunto=None
    )

    print("\n" + "="*60)
    print("🚀 INICIANDO AUTOMATIZACIÓN")
    print("="*60)
    
    async with XalocAsync(config) as bot:
        try:
            # Recuperamos la URL del formulario
            url_file = config.dir_auth / "last_url.txt"
            if url_file.exists():
                url_destino = url_file.read_text().strip()
                logging.info(f"🎯 Yendo directamente al formulario: {url_destino}")
                await bot.page.goto(url_destino, wait_until="networkidle")
            
            # Ejecutamos el rellenado de campos
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\n✅ PROCESO FINALIZADO: {screenshot_path}")
            
        except Exception as e:
            print(f"\n❌ Error durante la ejecución: {e}")
        finally:
            input("\nProceso terminado. Pulsa ENTER para cerrar.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())