"""
Flujo para indicar representante dentro del sitio Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page

from sites.ayunta_palma.config import AyuntaPalmaConfig


async def indicar_representante(page: Page, config: AyuntaPalmaConfig) -> Page:
    selectors = config.selectors

    boton = page.locator(selectors.btn_indicar_representante)
    await boton.wait_for(state="visible")
    await boton.click()
    await page.wait_for_timeout(config.delay_ms)

    dialog_titulo = page.locator(".ui-dialog-title", has_text="Nuevo/a representante del/de la interesado/a")
    await dialog_titulo.wait_for(state="visible", timeout=15000)

    aceptar = page.locator(selectors.btn_aceptar_modal)
    await aceptar.wait_for(state="visible")
    await aceptar.scroll_into_view_if_needed()
    await aceptar.click()
    await page.wait_for_timeout(config.delay_ms)
    return page
