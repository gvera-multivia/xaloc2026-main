"""
Flujo para completar el formulario interno de alegaciones en Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.data_models import AyuntaPalmaAlegaciones


async def _abrir_modal_alegaciones_si_no_esta(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    frame = page.frame_locator(selectors.alegaciones_frame)
    inputs = frame.locator(selectors.alegaciones_input)

    try:
        await inputs.nth(0).wait_for(state="visible", timeout=2500)
        return
    except PlaywrightTimeoutError:
        pass

    boton_siguiente = page.locator(selectors.btn_siguiente).first
    if await boton_siguiente.count() > 0 and await boton_siguiente.is_visible():
        await boton_siguiente.click()
    else:
        input_siguiente = page.locator(selectors.input_siguiente).first
        if await input_siguiente.count() > 0:
            if await input_siguiente.is_visible():
                await input_siguiente.click()
            else:
                await page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    selectors.input_siguiente,
                )

    await page.wait_for_timeout(config.delay_ms)
    await inputs.nth(0).wait_for(state="visible", timeout=30000)


async def completar_alegaciones(
    page: Page,
    config: AyuntaPalmaConfig,
    datos: AyuntaPalmaAlegaciones,
) -> Page:
    selectors = config.selectors
    await _abrir_modal_alegaciones_si_no_esta(page, config)
    frame = page.frame_locator(selectors.alegaciones_frame)

    inputs = frame.locator(selectors.alegaciones_input)
    await inputs.nth(0).wait_for(state="visible")
    await inputs.nth(0).fill(datos.expediente)
    await inputs.nth(1).fill(datos.matricula)

    textareas = frame.locator(selectors.alegaciones_textarea)
    await textareas.nth(0).fill(datos.expone)
    await textareas.nth(1).fill(datos.solicita)

    confirmar = frame.locator(selectors.alegaciones_confirm)
    await confirmar.wait_for(state="visible")
    await confirmar.click()
    await page.wait_for_timeout(config.delay_ms)
    return page