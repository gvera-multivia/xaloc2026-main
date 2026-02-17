"""
Flujo para indicar representante dentro del sitio Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.flows.common import robust_click

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
    await boton.wait_for(state="visible")
    dialog_titulo = page.locator(".ui-dialog-title", has_text="Nuevo/a representante del/de la interesado/a").first

    async def _dialogo_no_visible() -> bool:
        try:
            return not (await dialog_titulo.count() > 0 and await dialog_titulo.is_visible())
        except Exception:
            return True

    await robust_click(
        page,
        description="Abrir modal representante",
        primary=boton,
        fallback_selector=selectors.btn_indicar_representante,
        same_screen_check=_dialogo_no_visible,
        max_attempts=3,
        retry_wait_ms=5000,
    )
    await page.wait_for_timeout(config.delay_ms)

    await dialog_titulo.wait_for(state="visible", timeout=15000)
    await _sobrescribir_contacto_representante(page, config)

    aceptar = page.locator(selectors.btn_aceptar_modal).first
    await aceptar.wait_for(state="visible")

    async def _dialogo_sigue_visible() -> bool:
        try:
            return await dialog_titulo.count() > 0 and await dialog_titulo.is_visible()
        except Exception:
            return False

    await robust_click(
        page,
        description="Aceptar modal representante",
        primary=aceptar,
        fallback_selector=selectors.btn_aceptar_modal,
        same_screen_check=_dialogo_sigue_visible,
        max_attempts=3,
        retry_wait_ms=5000,
    )
    await page.wait_for_timeout(config.delay_ms)
    return page
