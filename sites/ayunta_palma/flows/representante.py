"""
Flujo para indicar representante dentro del sitio Ayunta Palma.
"""

from __future__ import annotations

import asyncio
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig

REPRESENTANTE_EMAIL = "info@xvia-serviciosjuridicos.com"
REPRESENTANTE_TELEFONO = "722761154"


async def _esperar_velo_oculto(page: Page, config: AyuntaPalmaConfig, timeout_ms: int = 6000) -> None:
    try:
        await page.wait_for_selector(config.selectors.velo, state="hidden", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass


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

    await asyncio.gather(
        email_input.wait_for(state="visible", timeout=12000),
        email_confirm.wait_for(state="visible", timeout=12000),
    )
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

    await telefono_input.wait_for(state="visible", timeout=12000)
    await telefono_input.fill(REPRESENTANTE_TELEFONO)


async def indicar_representante(page: Page, config: AyuntaPalmaConfig) -> Page:
    selectors = config.selectors

    await _esperar_velo_oculto(page, config, timeout_ms=6000)

    # Buscar el boton de indicar representante interactuando con DOM, 
    # buscando su etiqueta y el input subyacente de submit
    clicked_indicar = await page.evaluate("""() => {
        // Opción 1: buscar por ID si lo conocemos
        const els = document.querySelectorAll("input[id$='_btnListaInteresadosItemNuevoRepresentante']");
        if (els.length > 0) {
            els[els.length - 1].click();
            return true;
        }
        
        // Opción 2: DOM walking desde el boton visual
        const buttons = Array.from(document.querySelectorAll("button"));
        const btnIndicar = buttons.find(b => {
             const t = (b.textContent || "").toLowerCase();
             return t.includes("indicar representante") || t.includes("representant del/de la");
        });
        
        if (btnIndicar) {
            const container = btnIndicar.closest('.btn-bar-mini') || btnIndicar.parentElement;
            const hiddenInputs = Array.from(container.querySelectorAll("input[type='submit']"));
            if (hiddenInputs.length > 0) {
                 hiddenInputs[hiddenInputs.length - 1].click();
                 return true;
            }
            btnIndicar.click();
            return true;
        }
        return false;
    }""")

    if not clicked_indicar:
        # Fallback extremo visual
        boton = page.locator(selectors.btn_indicar_representante).last
        if await boton.count() > 0:
            await boton.click(force=True)

    # Esperar el panel modal por su clase general en lugar del titulo traducible
    dialog_titulo = page.locator(".ui-dialog:visible").last
    await dialog_titulo.wait_for(state="visible", timeout=15000)
    
    await _sobrescribir_contacto_representante(page, config)

    # Hacer clic en el input de Aceptar, recorriendo el DOM dialog en vez del boton volatil
    clicked_aceptar = await page.evaluate(f"""() => {{
        // Si sabemos el ID 
        const btnDirecto = document.querySelector("{selectors.input_aceptar_modal_persona}");
        if (btnDirecto) {{
            btnDirecto.click();
            return true;
        }}
        
        // Buscar dialogos abiertos
        const dialogs = Array.from(document.querySelectorAll('.ui-dialog')).filter(d => d.style.display !== 'none' && d.offsetWidth > 0);
        if (dialogs.length === 0) return false;
        const dialog = dialogs[dialogs.length - 1]; // ultimo abierto
        
        // Buscar boton aceptar
        const buttons = Array.from(dialog.querySelectorAll('button'));
        const acceptBtn = buttons.find(b => {{
             const t = (b.textContent || "").toLowerCase();
             return t.includes("aceptar") || t.includes("acceptar");
        }});
        
        if (acceptBtn) {{
            const container = acceptBtn.closest('.btn-bar-horizontal-centrada-inner') || acceptBtn.parentElement;
            const hiddenInputs = Array.from(container.querySelectorAll("input[type='submit']"));
            if (hiddenInputs.length > 0) {{
                 hiddenInputs[hiddenInputs.length - 1].click();
                 return true;
            }}
            acceptBtn.click();
            return true;
        }}
        return false;
    }}""")

    if not clicked_aceptar:
        aceptar = page.locator(selectors.btn_aceptar_modal).first
        if await aceptar.count() > 0:
            await aceptar.click(force=True)
            
    await _esperar_velo_oculto(page, config, timeout_ms=max(3000, config.delay_ms * 6))
    try:
        await page.locator(".ui-dialog:visible").last.wait_for(state="hidden", timeout=2500)
    except PlaywrightTimeoutError:
        pass
    return page
