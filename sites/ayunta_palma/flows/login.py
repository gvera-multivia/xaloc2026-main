"""
Flujo de autenticación para Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page

from sites.ayunta_palma.config import AyuntaPalmaConfig


async def ejecutar_login(page: Page, config: AyuntaPalmaConfig) -> Page:
    """
    Accede al portal de Palma y pulsa la opción de certificado dentro del iframe.
    """
    if page.url.startswith(config.url_base):
        # Evitar recargar si ya estamos en la misma URL (perfil persistente)
        await page.wait_for_timeout(config.delay_ms)
        return page

    await page.goto(config.url_base, wait_until="networkidle")
    await page.wait_for_timeout(config.delay_ms)

    frame = page.frame_locator(config.selectors.login_frame)
    opcion = frame.locator(config.selectors.login_option_rows).first
    await opcion.wait_for(state="visible")
    await opcion.click()
    await page.wait_for_timeout(config.delay_ms)
    return page
