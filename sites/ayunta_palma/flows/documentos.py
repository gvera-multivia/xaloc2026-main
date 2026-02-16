"""
Subida de documentos en el flujo de Ayunta Palma.
"""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig


async def _esperar_subida_completa(page: Page, config: AyuntaPalmaConfig) -> None:
    # Espera fija solicitada: dar margen a la subida antes de confirmar.
    await page.wait_for_timeout(6000)


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


async def _click_confirmar(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    btn_confirmar = page.locator(selectors.btn_confirmar).first
    if await btn_confirmar.count() > 0 and await btn_confirmar.is_visible():
        await btn_confirmar.click()
    else:
        # En esta pantalla "Confirmar" puede reutilizar el input hidden de btnSiguiente.
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


async def _click_modal_aceptar(page: Page, config: AyuntaPalmaConfig) -> None:
    btn_modal_aceptar = page.locator(config.selectors.btn_modal_aceptar).first
    await btn_modal_aceptar.wait_for(state="visible", timeout=config.timeouts.general)
    await btn_modal_aceptar.click()
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


async def _click_firmar(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    btn_firmar = page.locator(selectors.btn_firmar).first
    if await btn_firmar.count() > 0 and await btn_firmar.is_visible():
        await btn_firmar.click()
    else:
        hidden_input = page.locator(selectors.input_firmar).first
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
                    selectors.input_firmar,
                )
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _click_signar_tots_documents(page: Page, config: AyuntaPalmaConfig) -> None:
    candidates = [
        page.locator("button.btnFirmar").first,
        page.locator("button", has_text="Signar tots els documents").first,
        page.locator("button", has_text="Firmar todos los documentos").first,
        page.locator(config.selectors.btn_signar_tots_documents).first,
    ]

    for locator in candidates:
        try:
            await locator.wait_for(state="visible", timeout=12000)
            await locator.click()
            await page.wait_for_timeout(config.delay_ms)
            await _esperar_velo_oculto(page, config)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            try:
                await locator.click(force=True)
                await page.wait_for_timeout(config.delay_ms)
                await _esperar_velo_oculto(page, config)
                return
            except Exception:
                continue

    # Fallback final por JS: localizar por clase/Texto y clicar.
    clicked = await page.evaluate(
        """() => {
            const byClass = document.querySelector('button.btnFirmar');
            if (byClass) { byClass.click(); return true; }
            const buttons = Array.from(document.querySelectorAll('button'));
            const target = buttons.find(b => {
                const t = (b.textContent || '').toLowerCase();
                return t.includes('signar tots els documents') || t.includes('firmar todos los documentos');
            });
            if (target) { target.click(); return true; }
            return false;
        }"""
    )
    if not clicked:
        raise PlaywrightTimeoutError("No se localizó el botón 'Signar tots els documents'.")
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

    # 1) Avanzar tras aceptar el documento subido.
    await _click_siguiente(page, config)

    # 2) Marcar protección de datos y avanzar.
    await page.wait_for_timeout(config.delay_ms)
    await _marcar_proteccion_datos(page, config)
    await _click_siguiente(page, config)

    # 3) Aceptar modal intermedio y confirmar.
    await page.wait_for_timeout(config.delay_ms)
    await _click_modal_aceptar(page, config)
    await _click_confirmar(page, config)

    # 4) Ir a firma y lanzar firma de todos los documentos.
    await page.wait_for_timeout(config.delay_ms)
    await _click_firmar(page, config)
    await _click_signar_tots_documents(page, config)
    return page
