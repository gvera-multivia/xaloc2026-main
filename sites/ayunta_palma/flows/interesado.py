"""
Flujo para registrar al interesado en Ayunta Palma.
"""

from __future__ import annotations

import logging

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, expect

from sites.ayunta_palma.config import AyuntaPalmaConfig, AyuntaPalmaSelectors
from sites.ayunta_palma.data_models import AyuntaPalmaTarget

PALMA_CONTACT_EMAIL = "info@xvia-serviciosjuridicos.com"
PALMA_CONTACT_PHONE = "722761154"
logger = logging.getLogger(__name__)


async def _abrir_modal_nuevo_interesado(page: Page, selectors: AyuntaPalmaSelectors, delay_ms: int) -> None:
    tipo_usuario = page.locator(selectors.persona_tipo_usuario).first
    try:
        await tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass

    # Evitar clics durante cargas parciales.
    try:
        await page.wait_for_selector(selectors.velo, state="hidden", timeout=6000)
    except PlaywrightTimeoutError:
        pass

    # Importante: no usar el boton visible (redirect-url), para evitar
    # redirecciones al mismo enlace y quedarnos en la misma pantalla.
    # Disparamos solo el submit oculto ASP.NET del control exacto.
    await page.wait_for_timeout(5000)
    await page.evaluate(
        """() => {
            const normalize = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").trim();
            const submits = Array.from(document.querySelectorAll("input[type='submit']"));
            const hidden = submits.find((el) => {
                const id = (el.id || "").toLowerCase();
                const name = (el.name || "").toLowerCase();
                const value = normalize(el.value || "");
                return (
                    id.includes("btnlistainteresadosopcionesnuevo") ||
                    name.includes("btnlistainteresadosopcionesnuevo") ||
                    value.includes("nuevo/a interesado/a") ||
                    value.includes("nou interessat") ||
                    value.includes("nova interessada")
                );
            });
            if (hidden) {
                try { hidden.click(); } catch {}
            }
            if (typeof window.__doPostBack === "function") {
                try { window.__doPostBack("ctl00$ctl00$cphM$cph$btnListaInteresadosOpcionesNuevo", ""); } catch {}
            }
        }"""
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
    if await email_selector.count() > 0:
        try:
            await email_selector.wait_for(state="visible", timeout=3000)
            await _select_otro_option(email_selector)
        except PlaywrightTimeoutError:
            # En algunas variantes del formulario no hay selector visible:
            # solo aparecen los campos manuales de email.
            pass

    email_input = page.locator(selectors.email_input)
    email_confirm = page.locator(selectors.email_confirm_input)
    await email_input.wait_for(state="visible", timeout=20000)
    await email_confirm.wait_for(state="visible", timeout=20000)
    await email_input.fill(correo)
    await email_confirm.fill(correo)


async def _fill_telefono(page: Page, selectors: AyuntaPalmaSelectors, telefono: str) -> None:
    telefono_selector = page.locator(selectors.telefono_selector)
    if await telefono_selector.count() > 0:
        try:
            await telefono_selector.wait_for(state="visible", timeout=3000)
            await _select_otro_option(telefono_selector)
        except PlaywrightTimeoutError:
            # Variante con telefono manual sin selector previo.
            pass

    telefono_input = page.locator(selectors.telefono_input)
    await telefono_input.wait_for(state="visible", timeout=20000)
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
        razon_social_loc = page.locator(selectors.persona_razon_social).first
        nombre_loc = page.locator(selectors.persona_nombre).first
        try:
            await razon_social_loc.wait_for(state="visible", timeout=5000)
            await razon_social_loc.fill(juridica.razon_social)
        except PlaywrightTimeoutError:
            await nombre_loc.wait_for(state="visible", timeout=15000)
            await nombre_loc.fill(juridica.razon_social)

    await _fill_email(page, selectors, PALMA_CONTACT_EMAIL)
    await _fill_telefono(page, selectors, PALMA_CONTACT_PHONE)

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
    await _wait_for_velo_to_vanish(page, selectors)
    await page.wait_for_timeout(config.delay_ms)
    return page
