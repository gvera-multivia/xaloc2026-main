"""
Flujo para registrar al interesado en Ayunta Palma.
"""

from __future__ import annotations

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, expect

from sites.ayunta_palma.config import AyuntaPalmaConfig, AyuntaPalmaSelectors
from sites.ayunta_palma.data_models import AyuntaPalmaTarget

PALMA_CONTACT_EMAIL = "info@xvia-serviciosjuridicos.com"
PALMA_CONTACT_PHONE = "722761154"


async def _abrir_modal_nuevo_interesado(page: Page, selectors: AyuntaPalmaSelectors, delay_ms: int) -> None:
    tipo_usuario = page.locator(selectors.persona_tipo_usuario).first
    try:
        await tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass

    async def _try_open_once() -> None:
        # Evitar clics durante cargas parciales.
        try:
            await page.wait_for_selector(selectors.velo, state="hidden", timeout=6000)
        except PlaywrightTimeoutError:
            pass

        boton_nuevo = page.locator(selectors.btn_nuevo_interesado).first
        if await boton_nuevo.count() > 0 and await boton_nuevo.is_visible():
            try:
                await boton_nuevo.click()
            except Exception:
                await boton_nuevo.click(force=True)
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

    for _ in range(3):
        await _try_open_once()
        try:
            await tipo_usuario.wait_for(state="visible", timeout=7000)
            await page.wait_for_timeout(delay_ms)
            return
        except PlaywrightTimeoutError:
            await page.wait_for_timeout(800)

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

        apellido1 = (fisica.apellido1 or "").strip()
        apellido2 = (fisica.apellido2 or "").strip() if fisica.apellido2 else ""
        if not apellido1 and apellido2:
            apellido1, apellido2 = apellido2, ""
        if not apellido1:
            raise ValueError("Ayunta Palma: PersonaFisica requiere al menos un apellido.")

        await page.locator(selectors.persona_apellido1).fill(apellido1)
        apellido2_loc = page.locator(selectors.persona_apellido2).first
        if await apellido2_loc.count() > 0:
            await apellido2_loc.fill(apellido2)
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

    aceptar = page.locator(selectors.btn_aceptar_modal).first
    aceptar_input_real = page.locator("#ctl00_ctl00_cphM_cph_btnAceptarPersona").first
    boton_rep = page.locator(selectors.btn_indicar_representante).first

    async def _estado_ok_post_aceptar(timeout_ms: int = 8000) -> bool:
        try:
            await boton_rep.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    # 1) Prioridad absoluta: submit real ASP.NET (aunque este hidden).
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
            await _wait_for_velo_to_vanish(page, selectors, timeout=15000)
            await page.wait_for_timeout(config.delay_ms)
            if await _estado_ok_post_aceptar():
                return page
    except Exception:
        pass

    # 2) Fallback: boton visible del modal activo.
    try:
        await aceptar.wait_for(state="visible", timeout=3000)
        await aceptar.click()
        await _wait_for_velo_to_vanish(page, selectors, timeout=15000)
        await page.wait_for_timeout(config.delay_ms)
        if await _estado_ok_post_aceptar():
            return page
    except Exception:
        pass

    # 3) Fallback generico por texto.
    try:
        aceptar_generico = page.locator("button:has-text('Aceptar')").first
        if await aceptar_generico.count() > 0 and await aceptar_generico.is_visible():
            await aceptar_generico.click()
            await _wait_for_velo_to_vanish(page, selectors, timeout=15000)
            await page.wait_for_timeout(config.delay_ms)
            if await _estado_ok_post_aceptar():
                return page
    except Exception:
        pass

    # 4) Ultimo intento al submit real (por si aparecio tras postback parcial).
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
            await _wait_for_velo_to_vanish(page, selectors, timeout=15000)
            await page.wait_for_timeout(config.delay_ms)
            if await _estado_ok_post_aceptar(timeout_ms=15000):
                return page
    except Exception:
        pass

    raise PlaywrightTimeoutError(
        "No se pudo confirmar 'Nuevo/a interesado/a': no aparecio el estado post-aceptar esperado."
    )
