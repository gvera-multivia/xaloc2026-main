"""
Flujo para completar el formulario interno de alegaciones en Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page

from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.data_models import AyuntaPalmaAlegaciones


async def completar_alegaciones(
    page: Page,
    config: AyuntaPalmaConfig,
    datos: AyuntaPalmaAlegaciones,
) -> Page:
    selectors = config.selectors
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
