import asyncio
import sys
import logging
from pathlib import Path

from config import Config, DatosMulta
from xaloc_automation import XalocAsync

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')


async def setup_sesion(config: Config):
    """
    PRIMERA EJECUCIÓN: El usuario hace login manualmente.
    La sesión se guarda en el perfil persistente para usos posteriores.
    """
    from playwright.async_api import async_playwright
    
    print("\n" + "="*70)
    print(" 🔐 CONFIGURACIÓN INICIAL - PRIMERA EJECUCIÓN ".center(70))
    print("="*70)
    print("""
    Este proceso solo es necesario UNA VEZ.
    
    Pasos a seguir:
    1. Se abrirá el navegador automáticamente
    2. Haz clic en "Tramitació en línia"
    3. Selecciona tu certificado cuando aparezca el popup
    4. Espera a que cargue el formulario de Xaloc
    5. Pulsa ENTER en esta consola para guardar la sesión
    """)
    input(">>> Pulsa ENTER para comenzar...")
    
    async with async_playwright() as p:
        # Usar el mismo perfil persistente que usará la automatización
        user_data_dir = str(config.navegador.perfil_path.absolute())
        config.navegador.perfil_path.mkdir(parents=True, exist_ok=True)
        
        args = [
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--lang=ca",
            "--disable-features=TranslateUI"
        ]
        
        logging.info(f"📂 Creando perfil persistente en: {user_data_dir}")
        
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel=config.navegador.canal,
            headless=False,
            args=args,
            ignore_https_errors=True,
            no_viewport=True  # Permite ventana maximizada
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        # Navegar a la página inicial
        logging.info("🌐 Navegando a Xaloc...")
        await page.goto(config.url_base, wait_until="networkidle")
        
        print("\n" + "!"*70)
        print(" AHORA HAZ EL LOGIN MANUALMENTE ".center(70, "!"))
        print("!"*70)
        print("""
    1. Haz clic en "Tramitació en línia"
    2. Selecciona tu certificado en el popup de Windows
    3. Espera a que cargue el formulario
        """)
        
        # Esperar a que el usuario complete el login
        input("\n>>> Cuando el formulario esté cargado, pulsa ENTER aquí...")
        
        # Guardar la URL actual para uso posterior
        url_final = page.url
        url_file = config.dir_auth / "last_url.txt"
        config.dir_auth.mkdir(exist_ok=True)
        url_file.write_text(url_final)
        
        # Crear archivo marcador de que el setup está completo
        setup_marker = config.dir_auth / "setup_complete.txt"
        setup_marker.write_text("OK")
        
        logging.info(f"✅ URL guardada: {url_final}")
        logging.info(f"✅ Perfil guardado en: {user_data_dir}")
        
        await context.close()
        
    print("\n" + "="*70)
    print(" ✅ CONFIGURACIÓN COMPLETADA ".center(70))
    print("="*70)
    print(f"""
    La sesión ha sido guardada correctamente.
    
    A partir de ahora, ejecuta:
        python main.py --auto
    
    para ejecutar la automatización sin necesidad de login manual.
    """)


async def ejecutar_automatizacion(config: Config):
    """Ejecuta la automatización usando la sesión guardada."""
    datos = DatosMulta(
        email="test@example.com",
        num_denuncia="DEN/2024/001",
        matricula="1234ABC",
        num_expediente="EXP/2024/001",
        motivos="Alegación de prueba.",
        archivo_adjunto=None
    )

    print("\n" + "="*60)
    print("🚀 INICIANDO AUTOMATIZACIÓN XALOC")
    print("="*60)
    
    async with XalocAsync(config) as bot:
        try:
            # Si tenemos URL guardada, ir directamente al formulario
            url_file = config.dir_auth / "last_url.txt"
            if url_file.exists():
                url_destino = url_file.read_text().strip()
                # Solo usar si es una URL de la sede (no de valid.aoc)
                if "seu.xalocgirona.cat" in url_destino:
                    logging.info(f"🎯 Navegando directamente al formulario guardado...")
                    await bot.page.goto(url_destino, wait_until="networkidle")
            
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\n✅ PROCESO FINALIZADO: {screenshot_path}")
            
        except Exception as e:
            print(f"\n❌ Error durante la ejecución: {e}")
        finally:
            input("\nProceso terminado. Pulsa ENTER para cerrar.")


async def main():
    config = Config()
    
    # Verificar si ya se ha hecho el setup
    setup_marker = config.dir_auth / "setup_complete.txt"
    
    if "--setup" in sys.argv or not setup_marker.exists():
        # Primera ejecución o forzar setup
        await setup_sesion(config)
    elif "--auto" in sys.argv or setup_marker.exists():
        # Modo automático
        await ejecutar_automatizacion(config)
    else:
        print("""
Uso:
    python main.py --setup    Primera ejecución (login manual)
    python main.py --auto     Ejecución automática (usa sesión guardada)
    python main.py            Auto-detecta el modo según estado
        """)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())