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

        # --- FASE SUBIDA DE ARCHIVOS (Integrada) ---
        if datos.archivos_para_subir:
             logging.info("Iniciando subida de documentos dentro del formulario...")
             await subir_documento(page, datos.archivos_para_subir)
        else:
             logging.info("No hay archivos para subir.")

        # --- FASE LOPD ---
        try:
            logging.info("Verificando checkbox LOPD (#lopdok)...")
            lopd = page.locator("#lopdok")
            if await lopd.count() > 0:
                await lopd.wait_for(state="visible", timeout=5000)
                await lopd.scroll_into_view_if_needed()
                await lopd.check()
                # Breve pausa para que se procese el evento onchange
                await page.wait_for_timeout(500)
                logging.info("Checkbox LOPD marcado.")
            else:
                logging.info("Checkbox LOPD no encontrado (¿ya marcado?).")
        except Exception as e:
            logging.warning(f"No se pudo interactuar con LOPD: {e}")

        # --- FASE CONTINUAR ---
        logging.info("Buscando botón 'Continuar' (onSave)...")
        # Selector para <a ... onclick="javascript:onSave();">Continuar >></a>
        # Usamos un selector robusto combinando texto y onclick si es posible, o solo texto.
        continuar_btn = page.locator("a").filter(has_text="Continuar")
        
        if await continuar_btn.count() > 0:
            if await continuar_btn.is_visible():
                logging.info("Pulsando botón Continuar...")
                # Navegación esperada
                async with page.expect_navigation(timeout=60000, wait_until="domcontentloaded"):
                    await continuar_btn.click()
                logging.info("Navegación completada tras 'Continuar'.")
            else:
                logging.warning("El botón Continuar existe pero NO es visible.")
        else:
             logging.warning("No se encontró el botón 'Continuar' con texto 'Continuar'")

        logging.info("Formulario completado (y enviado) con éxito")

    except Exception as e:
        logging.error(f"Error durante el rellenado: {e}")
        await page.screenshot(path="fallo_formulario.png")
        raise
