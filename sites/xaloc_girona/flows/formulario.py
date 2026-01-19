"""
Flujo de rellenado del formulario STA
"""

from __future__ import annotations

import logging
import sys

from playwright.async_api import Page

from sites.xaloc_girona.data_models import DatosMulta
from sites.xaloc_girona.flows.documentos import subir_documento

DELAY_MS = 500


async def _rellenar_input(page: Page, selector: str, valor: str) -> None:
    locator = page.locator(selector)
    await locator.wait_for(state="visible", timeout=15000)
    await locator.scroll_into_view_if_needed()
    await locator.click()

    select_all = "Meta+A" if sys.platform == "darwin" else "Control+A"
    await locator.press(select_all)
    await locator.press("Backspace")

    await locator.press_sequentially(str(valor), delay=30)
    await locator.press("Tab")

    try:
        contenido = (await locator.input_value()).strip()
        if not contenido:
            await locator.fill(str(valor))
            await locator.press("Tab")
    except Exception:
        pass
    await page.wait_for_timeout(DELAY_MS)


async def _rellenar_tinymce_motius(page: Page, texto: str) -> None:
    # Preferimos la API de TinyMCE para que el <textarea> oculto se sincronice (save()).
    try:
        await page.wait_for_function(
            "() => window.tinymce && tinymce.get && tinymce.get('DinVarMOTIUS')",
            timeout=10000,
        )
        ok = await page.evaluate(
            """(texto) => {
                const ed = window.tinymce?.get?.('DinVarMOTIUS');
                if (!ed) return false;
                const p = document.createElement('p');
                p.textContent = texto ?? '';
                ed.setContent(p.outerHTML);
                ed.save();
                return true;
            }""",
            texto,
        )
        if ok:
            return
    except Exception:
        pass

    # Fallback: escribir en el body del iframe.
    frame = page.frame_locator("#DinVarMOTIUS_ifr")
    body = frame.locator("body#tinymce")
    await body.wait_for(state="visible", timeout=10000)
    await body.click()
    await body.fill(texto)
    await page.wait_for_timeout(DELAY_MS)


async def rellenar_formulario(page: Page, datos: DatosMulta) -> None:
    logging.info("Iniciando rellenado del formulario STA")

    try:
        await page.wait_for_selector("form#formulario", state="attached", timeout=20000)
        await page.wait_for_selector("#contact21", state="visible", timeout=20000)

        logging.info(f"Email: {datos.email}")
        await _rellenar_input(page, "#contact21", str(datos.email))

        logging.info(f"Denuncia: {datos.num_denuncia}")
        await _rellenar_input(page, "#DinVarNUMDEN", str(datos.num_denuncia))

        logging.info(f"Matrícula: {datos.matricula}")
        await _rellenar_input(page, "#DinVarMATRICULA", str(datos.matricula))

        logging.info(f"Expediente: {datos.num_expediente}")
        await _rellenar_input(page, "#DinVarNUMEXP", str(datos.num_expediente))

        logging.info("Rellenando motivos (TinyMCE)...")
        await _rellenar_tinymce_motius(page, str(datos.motivos))

        # NOTA: La subida de archivos se hace en una fase separada después de rellenar el formulario.
        # Esto evita problemas de sincronización con el navegador.

        logging.info("Formulario completado con éxito")

    except Exception as e:
        logging.error(f"Error durante el rellenado: {e}")
        await page.screenshot(path="fallo_formulario.png")
        raise
