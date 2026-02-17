"""
Flujo para completar el formulario interno de alegaciones en Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.flows.common import robust_click
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

    async def _inputs_no_visibles() -> bool:
        try:
            await inputs.nth(0).wait_for(state="visible", timeout=900)
            return False
        except PlaywrightTimeoutError:
            return True

    await robust_click(
        page,
        description="Abrir modal alegaciones (Siguiente)",
        primary=boton_siguiente,
        secondary=input_siguiente,
        fallback_selector=selectors.input_siguiente,
        same_screen_check=_inputs_no_visibles,
        max_attempts=3,
        retry_wait_ms=5000,
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

    async def _confirmar_sigue_visible() -> bool:
        try:
            return await confirmar.count() > 0 and await confirmar.is_visible()
        except Exception:
            return False

    await robust_click(
        page,
        description="Confirmar alegaciones",
        primary=confirmar,
        same_screen_check=_confirmar_sigue_visible,
        max_attempts=3,
        retry_wait_ms=5000,
    )
    await page.wait_for_timeout(config.delay_ms)
    return page
