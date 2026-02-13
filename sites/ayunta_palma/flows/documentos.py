"""
Subida de documentos en el flujo de Ayunta Palma.
"""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page

from sites.ayunta_palma.config import AyuntaPalmaConfig


async def subir_documentos(
    page: Page,
    config: AyuntaPalmaConfig,
    archivos: list[Path] | None,
) -> Page:
    if not archivos:
        return page

    selectors = config.selectors
    boton_anadir = page.locator(selectors.btn_anadir_documento)
    await boton_anadir.wait_for(state="visible")
    await boton_anadir.click()
    await page.wait_for_timeout(config.delay_ms)

    ruta = [str(p) for p in archivos]
    await page.set_input_files(selectors.archivo_input, ruta)
    await page.wait_for_selector(".tabla-ficheros td", timeout=config.timeouts.subida_archivo)

    confirmar = page.locator(selectors.btn_confirmar_archivo)
    await confirmar.wait_for(state="visible", timeout=config.timeouts.general)
    await confirmar.click(timeout=config.timeouts.subida_archivo)
    await page.wait_for_timeout(config.delay_ms)
    return page
