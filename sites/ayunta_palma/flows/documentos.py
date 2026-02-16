"""
Subida de documentos en el flujo de Ayunta Palma.
"""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page

from sites.ayunta_palma.config import AyuntaPalmaConfig


async def _esperar_subida_completa(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    await page.wait_for_selector(".tabla-ficheros td", timeout=config.timeouts.subida_archivo)

    # Si existe velo de carga, esperar a que desaparezca.
    try:
        await page.wait_for_selector(selectors.velo, state="hidden", timeout=config.timeouts.subida_archivo)
    except Exception:
        pass

    # Esperar a que el boton Aceptar del modal de ficheros este habilitado.
    confirmar = page.locator(selectors.btn_confirmar_archivo).first
    await confirmar.wait_for(state="visible", timeout=config.timeouts.subida_archivo)
    await page.wait_for_function(
        """(selector) => {
            const btn = document.querySelector(selector);
            if (!btn) return false;
            const disabled = btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true';
            return !disabled;
        }""",
        arg=selectors.btn_confirmar_archivo,
        timeout=config.timeouts.subida_archivo,
    )


async def _esperar_velo_oculto(page: Page, config: AyuntaPalmaConfig) -> None:
    try:
        await page.wait_for_selector(
            config.selectors.velo,
            state="hidden",
            timeout=config.timeouts.general,
        )
    except Exception:
        pass


async def _click_siguiente(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    btn = page.locator(selectors.btn_siguiente).first
    if await btn.count() > 0 and await btn.is_visible():
        await btn.click()
    else:
        hidden_input = page.locator(selectors.input_siguiente).first
        if await hidden_input.count() > 0:
            if await hidden_input.is_visible():
                await hidden_input.click()
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
    await _esperar_velo_oculto(page, config)


async def _marcar_proteccion_datos(page: Page, config: AyuntaPalmaConfig) -> None:
    chk = page.locator(config.selectors.chk_proteccion_datos).first
    await chk.wait_for(state="visible", timeout=config.timeouts.general)
    if not await chk.is_checked():
        try:
            await chk.check()
        except Exception:
            await chk.check(force=True)
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


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
    await _esperar_subida_completa(page, config)

    confirmar = page.locator(selectors.btn_confirmar_archivo)
    await confirmar.wait_for(state="visible", timeout=config.timeouts.general)
    await confirmar.click(timeout=config.timeouts.subida_archivo)
    await page.wait_for_timeout(config.delay_ms)

    # 1) Confirmar/aceptar los documentos y avanzar.
    await _click_siguiente(page, config)

    # 2) Avanzar a la pantalla de aceptación de condiciones.
    await page.wait_for_timeout(config.delay_ms)
    await _click_siguiente(page, config)

    # 3) Marcar protección de datos y avanzar de nuevo.
    await page.wait_for_timeout(config.delay_ms)
    await _marcar_proteccion_datos(page, config)
    await _click_siguiente(page, config)
    return page
