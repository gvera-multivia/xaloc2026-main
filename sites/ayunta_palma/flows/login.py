"""
Flujo de autenticación para Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig


async def _abrir_nueva_instancia(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors

    # Si ya estamos dentro del flujo de interesado, no hacer nada.
    persona_tipo_usuario = page.locator(selectors.persona_tipo_usuario)
    try:
        await persona_tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass

    boton_visible = page.locator(selectors.btn_nueva_instancia).first
    if await boton_visible.count() > 0 and await boton_visible.is_visible():
        await boton_visible.click()
        await page.wait_for_timeout(config.delay_ms)
        return

    input_submit = page.locator(selectors.input_nueva_instancia).first
    if await input_submit.count() == 0:
        return

    if await input_submit.is_visible():
        await input_submit.click()
    else:
        clickable_url = await input_submit.get_attribute("data-clickable-url")
        if clickable_url:
            await page.goto(clickable_url, wait_until="networkidle")
    await page.wait_for_timeout(config.delay_ms)


async def ejecutar_login(page: Page, config: AyuntaPalmaConfig) -> Page:
    """
    Accede al portal de Palma y pulsa la opción de certificado dentro del iframe.
    """
    if page.url.startswith(config.url_base):
        # Evitar recargar si ya estamos en la misma URL (perfil persistente)
        await page.wait_for_timeout(config.delay_ms)
        await _abrir_nueva_instancia(page, config)
        return page

    await page.goto(config.url_base, wait_until="networkidle")
    await page.wait_for_timeout(config.delay_ms)

    frame = page.frame_locator(config.selectors.login_frame)
    opcion = frame.locator(config.selectors.login_option_rows).first
    await opcion.wait_for(state="visible")
    await opcion.click()
    await page.wait_for_timeout(config.delay_ms)
    await _abrir_nueva_instancia(page, config)
    return page
