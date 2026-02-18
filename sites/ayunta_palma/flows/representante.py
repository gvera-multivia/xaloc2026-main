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

    boton = page.locator(selectors.btn_indicar_representante).first
    hidden_boton = page.locator("input[id*='btnListaInteresadosItemNuevoRepresentante']").first
    clicked = False
    try:
        if await boton.count() > 0 and await boton.is_visible():
            await boton.click()
            clicked = True
    except Exception:
        pass
    if not clicked:
        try:
            if await hidden_boton.count() > 0:
                if await hidden_boton.is_visible():
                    await hidden_boton.click()
                else:
                    await page.evaluate(
                        """() => {
                            const el = document.querySelector("input[id*='btnListaInteresadosItemNuevoRepresentante']");
                            if (el) el.click();
                        }"""
                    )
                clicked = True
        except Exception:
            pass
    if not clicked:
        raise PlaywrightTimeoutError("No se encontro accion para abrir 'Indicar representante'.")
    await page.wait_for_timeout(config.delay_ms)

    dialog_titulo = page.locator(".ui-dialog-title", has_text="Nuevo/a representante del/de la interesado/a")
    await dialog_titulo.wait_for(state="visible", timeout=15000)
    await _sobrescribir_contacto_representante(page, config)

    aceptar = page.locator(selectors.btn_aceptar_modal).first
    aceptar_input_real = page.locator("#ctl00_ctl00_cphM_cph_btnAceptarPersona").first

    async def _post_ok() -> bool:
        boton_siguiente = page.locator(selectors.btn_siguiente).first
        input_siguiente = page.locator(selectors.input_siguiente).first
        try:
            if await boton_siguiente.count() > 0 and await boton_siguiente.is_visible():
                return True
        except Exception:
            pass
        try:
            if await input_siguiente.count() > 0:
                return True
        except Exception:
            pass
        return False

    try:
        clicked = await page.evaluate(
            """() => {
                const el = document.querySelector('#ctl00_ctl00_cphM_cph_btnAceptarPersona');
                if (!el) return false;
                el.click();
                return true;
            }"""
        )
        if clicked:
            try:
                await page.wait_for_selector(selectors.velo, state="hidden", timeout=12000)
            except Exception:
                pass
            await page.wait_for_timeout(config.delay_ms)
            if await _post_ok():
                return page
    except Exception:
        pass

    try:
        await aceptar.wait_for(state="visible", timeout=3000)
        await aceptar.scroll_into_view_if_needed()
        await aceptar.click()
        try:
            await page.wait_for_selector(selectors.velo, state="hidden", timeout=12000)
        except Exception:
            pass
        await page.wait_for_timeout(config.delay_ms)
        if await _post_ok():
            return page
    except Exception:
        pass

    try:
        if await aceptar_input_real.count() > 0:
            if await aceptar_input_real.is_visible():
                await aceptar_input_real.click()
            else:
                await page.evaluate(
                    """() => {
                        const el = document.querySelector('#ctl00_ctl00_cphM_cph_btnAceptarPersona');
                        if (el) el.click();
                    }"""
                )
            try:
                await page.wait_for_selector(selectors.velo, state="hidden", timeout=12000)
            except Exception:
                pass
            await page.wait_for_timeout(config.delay_ms)
            if await _post_ok():
                return page
    except Exception:
        pass

    raise PlaywrightTimeoutError("No se pudo confirmar el representante (Aceptar).")
