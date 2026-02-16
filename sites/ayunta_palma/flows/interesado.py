"""
Flujo para registrar al interesado en Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, expect

from sites.ayunta_palma.config import AyuntaPalmaConfig, AyuntaPalmaSelectors
from sites.ayunta_palma.data_models import AyuntaPalmaTarget


async def _abrir_modal_nuevo_interesado(page: Page, selectors: AyuntaPalmaSelectors, delay_ms: int) -> None:
    tipo_usuario = page.locator(selectors.persona_tipo_usuario).first
    try:
        await tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass

    boton_nuevo = page.locator(selectors.btn_nuevo_interesado).first
    if await boton_nuevo.count() > 0 and await boton_nuevo.is_visible():
        await boton_nuevo.click()
    else:
        input_nuevo = page.locator(selectors.input_nuevo_interesado).first
        if await input_nuevo.count() > 0:
            if await input_nuevo.is_visible():
                await input_nuevo.click()
            else:
                await page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    selectors.input_nuevo_interesado,
                )

    await tipo_usuario.wait_for(state="visible", timeout=20000)
    await page.wait_for_timeout(delay_ms)


async def _wait_for_velo_to_vanish(
    page: Page,
    selectors: AyuntaPalmaSelectors,
    timeout: int = 12000,
) -> None:
    try:
        await page.wait_for_selector(selectors.velo, state="hidden", timeout=timeout)
    except PlaywrightTimeoutError:
        pass


async def _select_otro_option(locator: Locator) -> None:
    try:
        await locator.select_option(label="[Otro]")
    except Exception:
        await locator.select_option(value="")


async def _fill_email(page: Page, selectors: AyuntaPalmaSelectors, correo: str) -> None:
    email_selector = page.locator(selectors.email_selector)
    await email_selector.wait_for(state="visible")
    await _select_otro_option(email_selector)

    email_input = page.locator(selectors.email_input)
    email_confirm = page.locator(selectors.email_confirm_input)
    await email_input.fill(correo)
    await email_confirm.fill(correo)


async def _fill_telefono(page: Page, selectors: AyuntaPalmaSelectors, telefono: str) -> None:
    telefono_selector = page.locator(selectors.telefono_selector)
    await telefono_selector.wait_for(state="visible")
    await _select_otro_option(telefono_selector)

    telefono_input = page.locator(selectors.telefono_input)
    await telefono_input.fill(telefono)


async def registrar_interesado(
    page: Page,
    config: AyuntaPalmaConfig,
    target: AyuntaPalmaTarget,
) -> Page:
    selectors = config.selectors

    await _abrir_modal_nuevo_interesado(page, selectors, config.delay_ms)

    tipo_usuario = page.locator(selectors.persona_tipo_usuario)
    await tipo_usuario.wait_for(state="visible")
    await tipo_usuario.select_option("OtraPersona")
    await page.wait_for_timeout(config.delay_ms)

    personalidad = page.locator(selectors.persona_tipo_personalidad)
    await expect(personalidad).to_be_enabled()
    await personalidad.select_option(target.tipo_persona)
    await _wait_for_velo_to_vanish(page, selectors)

    if target.tipo_persona == "PersonaFisica":
        fisica = target.fisica
        if not fisica:
            raise ValueError("Ayunta Palma: faltan datos de PersonaFisica.")
        tipo_doc = page.locator(selectors.persona_tipo_documento)
        await tipo_doc.wait_for(state="visible")
        await tipo_doc.select_option(fisica.tipo_documento)
        await _wait_for_velo_to_vanish(page, selectors)

        await page.locator(selectors.persona_documento).fill(fisica.documento)
        await page.locator(selectors.persona_nombre).fill(fisica.nombre)
        await page.locator(selectors.persona_apellido1).fill(fisica.apellido1)
        if fisica.apellido2:
            await page.locator(selectors.persona_apellido2).fill(fisica.apellido2)
        if fisica.pais:
            pais_selector = page.locator(selectors.persona_pais)
            await pais_selector.select_option(fisica.pais)
    else:
        juridica = target.juridica
        if not juridica:
            raise ValueError("Ayunta Palma: faltan datos de PersonaJuridica.")
        await page.locator(selectors.persona_documento).fill(juridica.nif)
        await page.locator(selectors.persona_nombre).fill(juridica.razon_social)

    await _fill_email(page, selectors, target.contacto.correo)
    await _fill_telefono(page, selectors, target.contacto.telefono)

    aceptar = page.locator(selectors.btn_aceptar_modal)
    await aceptar.wait_for(state="visible")
    await aceptar.click()
    await _wait_for_velo_to_vanish(page, selectors)
    await page.wait_for_timeout(config.delay_ms)
    return page
