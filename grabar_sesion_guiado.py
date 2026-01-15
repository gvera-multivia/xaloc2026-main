"""
Grabación guiada de sesión para Xaloc Automation.

Motivación:
- Las pasarelas OAuth2/OIDC (VÀLid/AOC) requieren un flujo de navegación con contexto.
- Este script navega automáticamente hasta VÀLid y se detiene para que el usuario
  seleccione el certificado. Después guarda el `storage_state` en `auth/auth_state.json`.
"""

import asyncio
import logging
import sys

from playwright.async_api import async_playwright

from config import Config


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


async def grabar_sesion_guiada() -> None:
    config = Config()

    auth_file = config.auth_state_path
    config.dir_auth.mkdir(exist_ok=True)

    async with async_playwright() as p:
        logging.info("Iniciando navegador para grabación guiada...")

        browser = await p.chromium.launch(
            headless=False,
            channel=config.navegador.canal,
            args=config.navegador.args,
        )

        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        logging.info("Navegando a %s", config.url_base)
        await page.goto(config.url_base, wait_until="networkidle")

        logging.info("Pulsando 'Tramitació en línia' (esperando popup)...")
        async with page.expect_popup() as popup_info:
            await page.get_by_role("link", name="Tramitació en línia").click()

        valid_page = await popup_info.value
        await valid_page.wait_for_load_state("domcontentloaded")
        logging.info("Pasarela detectada: %s", valid_page.url)

        print("\n" + "!" * 72)
        print("MANUAL: Selecciona tu certificado en la ventana del navegador.")
        print("MANUAL: Completa el login hasta ver el formulario STA (Xaloc).")
        print("!" * 72 + "\n")
        input("Pulsa ENTER aquí cuando ya estés dentro para GUARDAR LA SESIÓN...")

        logging.info("Guardando estado de sesión en %s", auth_file)
        await context.storage_state(path=str(auth_file))

        logging.info("Sesión guardada correctamente.")
        await browser.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(grabar_sesion_guiada())

