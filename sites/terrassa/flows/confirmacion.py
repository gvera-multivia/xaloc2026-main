from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget


async def run_confirmacion(page: "Page", config: "TerrassaConfig", datos: "TerrassaTarget") -> "Page":
    _ = datos
    url_before = page.url
    continuar = page.locator(config.continuar_selector).first
    await continuar.wait_for(state="visible", timeout=config.timeouts.transicion)
    await continuar.click()
    await page.wait_for_load_state("domcontentloaded")

    # Parada segura antes de firma: aceptar varias señales de "paso 2".
    signar_loc = page.locator(config.signar_selector).first
    try:
        await signar_loc.wait_for(state="visible", timeout=config.timeouts.transicion)
        return page
    except PlaywrightTimeoutError:
        pass

    # Fallback: si desapareció el botón "Continuar" del paso 1 o cambió la URL, ya estamos fuera del formulario.
    continuar_count = await page.locator(config.continuar_selector).count()
    if continuar_count == 0 or page.url != url_before:
        return page

    raise RuntimeError(
        "terrassa: tras pulsar Continuar no se detectó pantalla de revisión/firma; revisar validaciones del formulario."
    )
    return page
