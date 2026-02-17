"""
Flujo de autenticacion para Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig


async def _abrir_nueva_instancia(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    persona_tipo_usuario = page.locator(selectors.persona_tipo_usuario).first

    try:
        await persona_tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass

    try:
        await page.wait_for_selector(selectors.velo, state="hidden", timeout=6000)
    except Exception:
        pass

    boton_visible = page.locator(selectors.btn_nueva_instancia_visible).first
    boton_alt = page.locator(selectors.btn_nueva_instancia).first
    hidden_selector = selectors.input_nueva_instancia

    if await boton_visible.count() > 0:
        await boton_visible.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(5000)
        try:
            await boton_visible.click(timeout=5000)
        except Exception:
            await boton_visible.click(force=True, timeout=5000)
    elif await boton_alt.count() > 0:
        await boton_alt.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(5000)
        try:
            await boton_alt.click(timeout=5000)
        except Exception:
            await boton_alt.click(force=True, timeout=5000)
    else:
        await page.wait_for_timeout(5000)
        await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (el) el.click();
            }""",
            hidden_selector,
        )

    await page.wait_for_timeout(config.delay_ms)
    await persona_tipo_usuario.wait_for(state="visible", timeout=25000)
    await page.wait_for_timeout(config.delay_ms)


async def ejecutar_login(page: Page, config: AyuntaPalmaConfig) -> Page:
    """
    Accede al portal de Palma y pulsa la opcion de certificado dentro del iframe.
    """
    try:
        await page.locator(config.selectors.persona_tipo_usuario).first.wait_for(state="visible", timeout=1200)
        return page
    except Exception:
        pass

    if not page.url.startswith(config.url_base):
        await page.goto(config.url_base, wait_until="domcontentloaded")
    await page.wait_for_timeout(config.delay_ms)

    frame = page.frame_locator(config.selectors.login_frame)
    opcion_titulo = frame.locator(config.selectors.login_option_cert_titulo).first
    opcion_fila = frame.locator(config.selectors.login_option_rows).first

    if await opcion_titulo.count() > 0:
        await opcion_titulo.wait_for(state="visible", timeout=20000)
        await page.wait_for_timeout(5000)
        try:
            await opcion_titulo.click(timeout=5000)
        except Exception:
            await opcion_titulo.click(force=True, timeout=5000)
    else:
        await opcion_fila.wait_for(state="visible", timeout=20000)
        await page.wait_for_timeout(5000)
        try:
            await opcion_fila.click(timeout=5000)
        except Exception:
            await opcion_fila.click(force=True, timeout=5000)

    await page.wait_for_timeout(config.delay_ms)
    await _abrir_nueva_instancia(page, config)
    return page
