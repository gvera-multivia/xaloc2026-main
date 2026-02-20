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
    input_siguiente = page.locator(selectors.input_siguiente).first
    await page.wait_for_timeout(5000)
    if await boton_siguiente.count() > 0:
        await boton_siguiente.wait_for(state="visible", timeout=15000)
        try:
            await boton_siguiente.click(timeout=5000)
        except Exception:
            await boton_siguiente.click(force=True, timeout=5000)
    else:
        await input_siguiente.wait_for(state="attached", timeout=15000)
        await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (el) el.click();
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

    confirmar = frame.locator(selectors.alegaciones_confirm).first
    await confirmar.wait_for(state="visible")
    await page.wait_for_timeout(5000)
    try:
        await confirmar.click(timeout=5000)
    except Exception:
        await confirmar.click(force=True, timeout=5000)
    await page.wait_for_timeout(config.delay_ms)
    return page
