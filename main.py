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
    """Graba la sesión con detección robusta del formulario real."""
    print("\n" + "="*75)
    print(" 🛠️ REPARACIÓN DE SESIÓN ".center(75, " "))
    print("="*75 + "\n")
    
    async with async_playwright() as p:
        # Preparar argumentos del navegador
        args = ["--start-maximized"]
        
        # AUTO-SELECCIÓN DE CERTIFICADO: Si está configurado, añadir política
        if config.navegador.certificado_cn:
            # Formato JSON: {"pattern":"URL","filter":{"SUBJECT":{"CN":"NOMBRE"}}}
            policy = f'{{"pattern":"https://valid.aoc.cat","filter":{{"SUBJECT":{{"CN":"{config.navegador.certificado_cn}"}}}}}}'
            args.append(f'--auto-select-certificate-for-urls=[{policy}]')
            logging.info(f"🔐 Auto-selección de certificado activada: {config.navegador.certificado_cn}")
        
        # Forzamos canal 'chrome' o 'msedge' para acceso a certificados del sistema
        browser = await p.chromium.launch(
            headless=False, 
            channel=config.navegador.canal or "chrome",
            args=args
        )
        context = await browser.new_context(ignore_https_errors=True, no_viewport=True)
        page = await context.new_page()

        logging.info("1. Navegando a Xaloc...")
        await page.goto(config.url_base, wait_until="networkidle")
        
        # Aceptar cookies
        try:
            await page.get_by_role("button", name="Acceptar").click(timeout=3000)
        except: pass

        logging.info("2. Abriendo pasarela AOC...")
        async with page.expect_popup() as popup_info:
            await page.get_by_role("link", name="Tramitació en línia").first.click()
        
        aoc_page = await popup_info.value
        await aoc_page.wait_for_load_state("domcontentloaded")

        # FIX CLICK: Intentamos varias formas para el botón de certificado
        logging.info("3. Intentando disparar botón de certificado...")
        try:
            # Opción 1: Selector ID con hover previo (simula comportamiento humano)
            btn = aoc_page.locator("#btnCert")
            await btn.wait_for(state="visible", timeout=5000)
            await btn.hover()  # Simula movimiento humano - algunos botones lo requieren
            await asyncio.sleep(0.5)
            await btn.click()
            logging.info("✅ Click enviado con éxito.")
        except Exception:
            # Opción 2: Buscar por texto si el ID falla
            try:
                await aoc_page.get_by_text("Certificat digital").click(timeout=3000)
                logging.info("✅ Click enviado mediante texto.")
            except Exception:
                logging.warning("⚠️ El script no pudo clicar. POR FAVOR, HAZ CLICK MANUAL EN EL BOTÓN AZUL.")

        print("\n" + "!" * 75)
        print(" ESPERANDO LOGIN COMPLETO ".center(75, "!"))
        print(" 1. Selecciona tu certificado en la ventana de Windows.")
        print(" 2. Rellena el PIN si te lo pide.")
        print(" 3. Espera a que el navegador cargue el formulario real de Xaloc.")
        print("!" * 75 + "\n")

        # DETECCIÓN DEL FORMULARIO
        # Primero esperamos URL correcta, luego buscamos cualquier campo de formulario
        intentos = 0
        max_intentos = 120  # 2 minutos de margen
        formulario_detectado = False
        
        while intentos < max_intentos:
            url_actual = aoc_page.url
            
            # Verificamos que la URL sea de la sede Y NO de valid.aoc
            es_url_sede = "seu.xalocgirona.cat" in url_actual
            no_es_pasarela = "valid.aoc.cat" not in url_actual
            url_correcta = es_url_sede and no_es_pasarela
            
            if url_correcta:
                # Buscamos cualquier campo de formulario típico
                campos_posibles = aoc_page.locator(
                    "input[type='text'], input[type='email'], textarea, "
                    "input#f_dni, input[name='f_dni'], input#dni, "
                    "form input:not([type='hidden'])"
                )
                
                if await campos_posibles.count() > 0:
                    print(f"\n✨ FORMULARIO DETECTADO CORRECTAMENTE")
                    print(f"   Campos encontrados: {await campos_posibles.count()}")
                    print(f"   URL verificada: {url_actual}")
                    formulario_detectado = True
                    break
                else:
                    # Si la URL es correcta pero no hay campos, igual aceptamos
                    # (puede ser que los campos tarden en renderizar)
                    await asyncio.sleep(2)
                    if await campos_posibles.count() > 0 or intentos > 30:
                        print(f"\n✨ FORMULARIO DETECTADO (por URL)")
                        print(f"   URL verificada: {url_actual}")
                        formulario_detectado = True
                        break
            
            if intentos % 10 == 0:
                logging.info(f"Esperando formulario... (URL actual: {url_actual[:60]}...)")
            
            await asyncio.sleep(1)
            intentos += 1
        
        if not formulario_detectado:
            logging.error("❌ Tiempo máximo excedido esperando el formulario.")
            await browser.close()
            return

        print(f"\nURL Final confirmada: {aoc_page.url}")
        input("\n>>> PULSA ENTER AQUÍ PARA GUARDAR LA SESIÓN DEFINITIVA...")

        # GUARDAR ESTADO Y URL FINAL
        config.dir_auth.mkdir(exist_ok=True)
        await context.storage_state(path=str(config.auth_state_path))
        
        with open(config.dir_auth / "last_url.txt", "w") as f:
            f.write(aoc_page.url)
            
        logging.info(f"✅ Sesión guardada en {config.auth_state_path}")
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