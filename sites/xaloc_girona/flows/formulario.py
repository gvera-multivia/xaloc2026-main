"""
Flujo de rellenado del formulario STA
"""

from __future__ import annotations

import logging
import sys

from playwright.async_api import Page

from sites.xaloc_girona.data_models import DatosMulta, DatosMandatario

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


async def _rellenar_input_mayusculas(page: Page, selector: str, valor: str) -> None:
    """
    Rellena un campo de input con el valor en MAYÚSCULAS.
    Aplica trim y ejecuta evento blur para triggers JS.
    """
    valor_clean = (valor or "").strip().upper()
    if not valor_clean:
        logging.warning(f"Campo {selector} vacío, saltando...")
        return
    
    locator = page.locator(selector)
    await locator.wait_for(state="visible", timeout=10000)
    await locator.scroll_into_view_if_needed()
    await locator.click()
    
    # Limpiar campo existente
    select_all = "Meta+A" if sys.platform == "darwin" else "Control+A"
    await locator.press(select_all)
    await locator.press("Backspace")
    
    # Escribir valor (simulando escritura humana)
    await locator.press_sequentially(valor_clean, delay=30)
    
    # Ejecutar blur para triggers JS (tomayus, checkTipo, etc.)
    await locator.dispatch_event("blur")
    await page.wait_for_timeout(DELAY_MS)


async def _rellenar_persona_juridica(page: Page, m: DatosMandatario) -> None:
    logging.info("Tipo de persona: JURÍDICA")
    
    # 1. Selector específico sin usar el ID '#' para evitar duplicados
    selector_rj = "input[name='tipoPersonaRepresented'][value='RJ']"
    radio_rj = page.locator(selector_rj)
    
    # Esperamos y clicamos una sola vez
    await radio_rj.wait_for(state="visible", timeout=10000)
    await radio_rj.click()
    await page.wait_for_timeout(DELAY_MS)
    
    # 2. Rellenar campos (estos IDs sí suelen ser únicos)
    await _rellenar_input_mayusculas(page, "#RepCIF", m.cif_documento or "")
    await _rellenar_input_mayusculas(page, "#RepCIFCtrlDigit", m.cif_control or "")
    await _rellenar_input_mayusculas(page, "#RepRazonSoc", m.razon_social or "")


async def _rellenar_persona_fisica(page: Page, m: DatosMandatario) -> None:
    logging.info("Tipo de persona: FÍSICA")
    
    # 1. Selector específico sin usar el ID '#' 
    selector_rf = "input[name='tipoPersonaRepresented'][value='RF']"
    radio_rf = page.locator(selector_rf)
    
    await radio_rf.wait_for(state="visible", timeout=10000)
    await radio_rf.click()
    await page.wait_for_timeout(DELAY_MS)
    
    # 2. Tipo de documento y datos personales
    tipo_doc_select = page.locator("#RepTipoDoc")
    await tipo_doc_select.wait_for(state="visible", timeout=10000)
    await tipo_doc_select.select_option(value=m.tipo_doc or "NIF")
    await page.wait_for_timeout(DELAY_MS)
    await tipo_doc_select.dispatch_event("change")
    
    await _rellenar_input_mayusculas(page, "#RepDocuNum", m.doc_numero or "")
    await _rellenar_input_mayusculas(page, "#RepDigito", m.doc_control or "")
    await _rellenar_input_mayusculas(page, "#RepNombre", m.nombre or "")
    await _rellenar_input_mayusculas(page, "#RepApellido1", m.apellido1 or "")
    await _rellenar_input_mayusculas(page, "#RepApellido2", m.apellido2 or "")


async def _rellenar_mandatario(page: Page, mandatario: DatosMandatario) -> None:
    logging.info("Rellenando sección de mandatario...")
    
    # CORRECCIÓN: Buscamos el radio 'RT' de forma única
    selector_rt = "input[name='tipoActuacion'][value='RT']"
    radio_rt = page.locator(selector_rt)
    
    await radio_rt.wait_for(state="visible", timeout=10000)
    await radio_rt.click()
    await page.wait_for_timeout(DELAY_MS)
    
    # Llamamos a la sub-función correspondiente
    if mandatario.tipo_persona == "JURIDICA":
        await _rellenar_persona_juridica(page, mandatario)
    else:
        await _rellenar_persona_fisica(page, mandatario)

    logging.info("Mandatario completado")

async def rellenar_formulario(page: Page, datos: DatosMulta) -> None:
    logging.info("Iniciando rellenado del formulario STA")

    try:
        await page.wait_for_selector("form#formulario", state="attached", timeout=20000)
        await page.wait_for_selector("#contact21", state="visible", timeout=20000)

        # CAMBIO DE ORDEN: Rellenar sección de mandatario PRIMERO
        # Esto es crítico porque el formulario puede tener validaciones JS que ocultan
        # el botón de adjuntar documentos hasta que los campos de mandatario estén completos
        if datos.mandatario:
            logging.info("Rellenando sección de mandatario PRIMERO...")
            await _rellenar_mandatario(page, datos.mandatario)
            # Pequeña espera para que el DOM se actualice tras seleccionar mandatario
            await page.wait_for_timeout(1000)

        # Ahora rellenamos el resto de campos
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
