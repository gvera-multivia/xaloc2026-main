"""
Flujo para indicar representante dentro del sitio Ayunta Palma.
"""

from __future__ import annotations

import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig

REPRESENTANTE_EMAIL = "info@xvia-serviciosjuridicos.com"
REPRESENTANTE_TELEFONO = "722761154"
logger = logging.getLogger(__name__)


def _resolver_pagina_activa(page: Page) -> Page:
    if not page.is_closed():
        return page
    ctx = page.context
    abiertas = [p for p in ctx.pages if not p.is_closed()]
    if not abiertas:
        raise PlaywrightTimeoutError("No hay pestañas activas en el contexto para continuar.")
    return abiertas[-1]


async def _sobrescribir_contacto_representante(page: Page, config: AyuntaPalmaConfig) -> Page:
    page = _resolver_pagina_activa(page)
    selectors = config.selectors
    # Evitar select_option en combos autopostback del popup de representante:
    # en producción está provocando cierres/rotaciones de target.
    email_input = page.locator(selectors.email_input).first
    email_confirm = page.locator(selectors.email_confirm_input).first
    telefono_input = page.locator(selectors.telefono_input).first

    if await email_input.count() > 0 and await email_input.is_visible():
        await email_input.fill(REPRESENTANTE_EMAIL)
    if await email_confirm.count() > 0 and await email_confirm.is_visible():
        await email_confirm.fill(REPRESENTANTE_EMAIL)
    if await telefono_input.count() > 0 and await telefono_input.is_visible():
        await telefono_input.fill(REPRESENTANTE_TELEFONO)
    return page


async def indicar_representante(page: Page, config: AyuntaPalmaConfig) -> Page:
    page = _resolver_pagina_activa(page)
    selectors = config.selectors
    logger.info("[AP-REP] Inicio indicar_representante.")

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
    logger.info("[AP-REP] Accion de apertura de representante ejecutada.")
    await page.wait_for_timeout(config.delay_ms)
    try:
        await page.wait_for_selector(selectors.velo, state="hidden", timeout=12000)
    except Exception:
        pass

    try:
        page = await _sobrescribir_contacto_representante(page, config)
        logger.info("[AP-REP] Contacto representante revisado (sin select_option autopostback).")
    except Exception:
        # Si justo en esta fase el sitio cierra/rota target, reenganchar y reintentar una vez.
        page = _resolver_pagina_activa(page)
        try:
            page = await _sobrescribir_contacto_representante(page, config)
            logger.info("[AP-REP] Reintento de contacto representante OK tras reenganche.")
        except PlaywrightTimeoutError as e:
            titulos = []
            try:
                titulos = await page.locator(".ui-dialog-title").all_inner_texts()
            except Exception:
                pass
            raise PlaywrightTimeoutError(
                f"No se abrio el popup de representante (campos no visibles). Titulos detectados: {titulos}"
            ) from e

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
            logger.info("[AP-REP] Click en btnAceptarPersona (hidden submit) ejecutado.")
            try:
                await page.wait_for_selector(selectors.velo, state="hidden", timeout=12000)
            except Exception:
                pass
            await page.wait_for_timeout(config.delay_ms)
            if await _post_ok():
                logger.info("[AP-REP] Representante confirmado correctamente.")
                return page
    except Exception:
        pass

    try:
        await aceptar.wait_for(state="visible", timeout=3000)
        await aceptar.scroll_into_view_if_needed()
        await aceptar.click()
        logger.info("[AP-REP] Fallback click en boton visible 'Aceptar'.")
        try:
            await page.wait_for_selector(selectors.velo, state="hidden", timeout=12000)
        except Exception:
            pass
        await page.wait_for_timeout(config.delay_ms)
        if await _post_ok():
            logger.info("[AP-REP] Representante confirmado tras fallback boton visible.")
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
            logger.info("[AP-REP] Fallback final en btnAceptarPersona ejecutado.")
            try:
                await page.wait_for_selector(selectors.velo, state="hidden", timeout=12000)
            except Exception:
                pass
            await page.wait_for_timeout(config.delay_ms)
            if await _post_ok():
                logger.info("[AP-REP] Representante confirmado tras fallback final.")
                return page
    except Exception:
        pass

    raise PlaywrightTimeoutError("No se pudo confirmar el representante (Aceptar).")
