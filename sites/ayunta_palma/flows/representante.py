"""
Flujo para indicar representante dentro del sitio Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig

REPRESENTANTE_EMAIL = "info@xvia-serviciosjuridicos.com"
REPRESENTANTE_TELEFONO = "722761154"


async def _sobrescribir_contacto_representante(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors

    email_selector = page.locator(selectors.email_selector).first
    if await email_selector.count() > 0:
        try:
            await email_selector.wait_for(state="visible", timeout=3000)
            try:
                await email_selector.select_option(label="[Otro]")
            except Exception:
                await email_selector.select_option(value="")
        except PlaywrightTimeoutError:
            pass

    email_input = page.locator(selectors.email_input).first
    email_confirm = page.locator(selectors.email_confirm_input).first
    telefono_selector = page.locator(selectors.telefono_selector).first
    telefono_input = page.locator(selectors.telefono_input).first

    await email_input.wait_for(state="visible", timeout=20000)
    await email_confirm.wait_for(state="visible", timeout=20000)
    await email_input.fill(REPRESENTANTE_EMAIL)
    await email_confirm.fill(REPRESENTANTE_EMAIL)

    if await telefono_selector.count() > 0:
        try:
            await telefono_selector.wait_for(state="visible", timeout=3000)
            try:
                await telefono_selector.select_option(label="[Otro]")
            except Exception:
                await telefono_selector.select_option(value="")
        except PlaywrightTimeoutError:
            pass

    await telefono_input.wait_for(state="visible", timeout=20000)
    await telefono_input.fill(REPRESENTANTE_TELEFONO)


async def indicar_representante(page: Page, config: AyuntaPalmaConfig) -> Page:
    selectors = config.selectors

    boton = page.locator(selectors.btn_indicar_representante_visible).first
    boton_alt = page.locator(selectors.btn_indicar_representante).first
    await boton_alt.wait_for(state="visible")
    dialog_titulo = page.locator(".ui-dialog-title", has_text="Nuevo/a representante del/de la interesado/a").first

    await page.wait_for_timeout(5000)
    if await boton.count() > 0:
        try:
            await boton.click(timeout=5000)
        except Exception:
            await boton.click(force=True, timeout=5000)
    else:
        try:
            await boton_alt.click(timeout=5000)
        except Exception:
            await page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (el) el.click();
                }""",
                selectors.input_indicar_representante,
            )
    await page.wait_for_timeout(config.delay_ms)

    await dialog_titulo.wait_for(state="visible", timeout=15000)
    await _sobrescribir_contacto_representante(page, config)

    aceptar = page.locator(selectors.btn_aceptar_modal_visible).first
    aceptar_alt = page.locator(selectors.btn_aceptar_modal).first
    try:
        await aceptar.wait_for(state="visible", timeout=4000)
    except PlaywrightTimeoutError:
        await aceptar_alt.wait_for(state="visible", timeout=4000)

    await page.wait_for_timeout(5000)
    try:
        await aceptar.click(timeout=5000)
    except Exception:
        if await aceptar_alt.count() > 0:
            try:
                await aceptar_alt.click(force=True, timeout=5000)
            except Exception:
                await page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (el) el.click();
                    }""",
                    selectors.input_aceptar_modal_persona,
                )
    await page.wait_for_timeout(config.delay_ms)
    return page
