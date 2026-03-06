"""
Flujo de autenticación para Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig


def _is_nueva_entrada_url(url: str) -> bool:
    return "/carpetaciudadana/nueva_entrada.aspx" in (url or "")


def _is_preguntar_entrada_url(url: str) -> bool:
    return "/carpetaciudadana/preguntar_entrada_anterior.aspx" in (url or "")


def _is_post_login_url(url: str) -> bool:
    return _is_nueva_entrada_url(url) or _is_preguntar_entrada_url(url)


async def _abrir_nueva_instancia(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors

    # Si ya estamos dentro del flujo de interesado, no hacer nada.
    persona_tipo_usuario = page.locator(selectors.persona_tipo_usuario)
    try:
        await persona_tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass

    input_submit = page.locator(selectors.input_nueva_instancia).first
    if await input_submit.count() == 0:
        return

    # 1) Prioridad absoluta: input oculto "Nueva instancia en blanco" (Cancelar).
    clickable_url = await input_submit.get_attribute("data-clickable-url")
    if clickable_url and "recuperar=false" in clickable_url.lower():
        await page.goto(clickable_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(config.delay_ms)
        return

    if await input_submit.is_visible():
        await input_submit.click()
        await page.wait_for_timeout(config.delay_ms)
        return

    # 2) Fallback visual, pero SIEMPRE acotado al contenedor del input "Cancelar".
    boton_visible = page.locator(selectors.btn_nueva_instancia_visible).first
    if await boton_visible.count() > 0 and await boton_visible.is_visible():
        await boton_visible.click()
        await page.wait_for_timeout(config.delay_ms)


async def ejecutar_login(page: Page, config: AyuntaPalmaConfig) -> Page:
    """
    Accede al portal de Palma y pulsa la opción de certificado dentro del iframe.
    """
    if page.url.startswith(config.url_base) or _is_post_login_url(page.url):
        # Evitar recargar si ya estamos en la misma URL (perfil persistente)
        await page.wait_for_timeout(config.delay_ms)
        await _abrir_nueva_instancia(page, config)
        return page

    await page.goto(config.url_base, wait_until="domcontentloaded")
    await page.wait_for_timeout(config.delay_ms)
    if _is_post_login_url(page.url):
        await _abrir_nueva_instancia(page, config)
        return page

    frame = page.frame_locator(config.selectors.login_frame)
    opcion = frame.locator(config.selectors.login_option_rows).first
    try:
        await opcion.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        # Si durante la espera ya hemos navegado a nueva_entrada, seguimos flujo.
        if _is_post_login_url(page.url):
            await _abrir_nueva_instancia(page, config)
            return page
        raise
    await opcion.click()
    await page.wait_for_timeout(config.delay_ms)
    await _abrir_nueva_instancia(page, config)
    return page
