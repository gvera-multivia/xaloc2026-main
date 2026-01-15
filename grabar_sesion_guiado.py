import asyncio
import logging
import sys
from playwright.async_api import async_playwright
from config import Config

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

async def grabar_sesion_guiada() -> None:
    config = Config()
    auth_file = config.auth_state_path
    
    # Asegurar que el directorio existe
    config.dir_auth.mkdir(exist_ok=True)

    async with async_playwright() as p:
        logging.info("Iniciando navegador para grabación guiada...")

        # Lanzamos el navegador con la configuración de tu config.py
        browser = await p.chromium.launch(
            headless=False,
            channel=config.navegador.canal,
            args=config.navegador.args,
        )

        # Creamos un contexto limpio
        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()

        logging.info("Navegando a la URL base: %s", config.url_base)
        await page.goto(config.url_base, wait_until="domcontentloaded")

        # 1. Manejo de Cookies (igual que en el flujo principal)
        try:
            boton_cookies = page.get_by_role("button", name="Acceptar")
            if await boton_cookies.count() > 0:
                await boton_cookies.first.click(timeout=3000)
                logging.info("Cookies aceptadas.")
        except Exception:
            logging.info("No se detectó banner de cookies o ya fue aceptado.")

        # 2. Localizar el enlace de 'Tramitació en línia'
        logging.info("Buscando botón 'Tramitació en línia'...")
        enlace = page.get_by_role("link", name="Tramitació en línia").first
        
        await enlace.wait_for(state="visible", timeout=config.timeouts.general)
        await enlace.scroll_into_view_if_needed()

        # 3. Flujo de Click y Captura de Popup (El "fix" que mencionas)
        logging.info("Haciendo click para abrir la pasarela VÀLid...")
        try:
            async with page.expect_popup(timeout=10000) as popup_info:
                await enlace.click()
            
            # Cambiamos el foco a la nueva página (la de VÀLid/AOC)
            target_page = await popup_info.value
            await target_page.wait_for_load_state("domcontentloaded")
            logging.info("Pasarela detectada con éxito: %s", target_page.url)
        
        except Exception as e:
            logging.warning("No se detectó popup, intentando continuar en la página actual: %s", e)
            target_page = page

        # 4. Instrucciones manuales
        print("\n" + "!" * 75)
        print(" ACCIÓN MANUAL REQUERIDA ".center(75, "="))
        print("1. En la ventana del navegador, selecciona tu CERTIFICADO DIGITAL.")
        print("2. Si se te solicita, introduce el PIN.")
        print("3. Una vez veas el formulario de Xaloc (donde se rellenan los datos),")
        print("   vuelve aquí y pulsa ENTER.")
        print("!" * 75 + "\n")

        input(">>> Pulsa ENTER aquí para GUARDAR LA SESIÓN una vez estés logueado...")

        # 5. Guardar el estado
        logging.info("Guardando storage_state en %s", auth_file)
        await context.storage_state(path=str(auth_file))

        logging.info("✅ Sesión guardada correctamente. Ya puedes usar main.py.")
        
        # Cerramos con un pequeño delay
        await asyncio.sleep(1)
        await browser.close()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        asyncio.run(grabar_sesion_guiada())
    except KeyboardInterrupt:
        pass