"""
Flujo para el formulario de Recurso de Reposición (P3) - paso 1/3.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re

from playwright.async_api import Page

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineReposicionData


def _normalizar_tipus_objecte(raw: str) -> str:
    valor = (raw or "").strip().upper()
    if valor in {"IBI"}:
        return "IBI"
    if valor in {"IVTM"}:
        return "IVTM"
    if valor in {"EXPEDIENTE EJECUTIVO", "EXPEDIENTE_EJECUTIVO", "EXPEDIENT EXECUTIU", "EXPEDIENT_EXECUTIU"}:
        return "EXPEDIENTE EJECUTIVO"
    if valor in {"OTROS", "ALTRES"}:
        return "OTROS"
    raise ValueError(f"tipus_objecte inválido: {raw}. Usa IBI, IVTM, Expediente Ejecutivo u Otros.")


async def _subir_documento_p3(page: Page, archivo: Path) -> None:
    if not archivo.exists():
        raise FileNotFoundError(f"No existe el archivo a adjuntar: {archivo}")

    logging.info("[P3] Abriendo popup de carga de fichero...")
    await page.get_by_role("button", name=re.compile(r"Carregar\s+Fitxer", re.IGNORECASE)).click()

    modal = page.locator("#fitxer")
    await modal.wait_for(state="visible", timeout=15000)

    frame = page.frame_locator("#contingut_fitxer")
    file_input = frame.locator("input[type='file'][name='qqfile']").first
    await file_input.wait_for(state="attached", timeout=20000)

    logging.info(f"[P3] Adjuntando archivo: {archivo.name}")
    await file_input.set_input_files(str(archivo.resolve()))

    success_text = frame.locator("#textSuccess").first
    await success_text.wait_for(state="visible", timeout=30000)
    texto = (await success_text.inner_text()).strip()
    if archivo.name.lower() not in texto.lower():
        raise RuntimeError(f"[P3] Upload no confirmado. textSuccess='{texto}'")

    logging.info("[P3] Upload confirmado, pulsando 'Continuar' del popup...")
    await frame.locator("#continuar").first.click()

    await modal.wait_for(state="hidden", timeout=15000)
    await page.wait_for_timeout(500)


async def _avanzar_a_presentacion_p3(page: Page) -> None:
    logging.info("[P3] Continuando al paso de presentación...")
    await page.locator("input[type='submit'][name='form0:j_id66'][value='Continuar']").first.click()
    await page.wait_for_load_state("domcontentloaded")

    boton_firma = page.locator("input[type='button'][value='Signar i Presentar']").first
    await boton_firma.wait_for(state="visible", timeout=20000)
    logging.info("[P3] Pantalla 'Signar i Presentar' detectada (no se pulsa en modo demo).")


async def rellenar_formulario_p3(page: Page, config: BaseOnlineConfig, data: BaseOnlineReposicionData) -> None:
    logging.info("[P3] Rellenando formulario de Recurso de Reposición...")

    # 1. Inputs radio: tipo de objeto
    tipus_objecte = _normalizar_tipus_objecte(data.tipus_objecte)
    radio_selector = {
        "IBI": config.p3_radio_ibi,
        "IVTM": config.p3_radio_ivtm,
        "EXPEDIENTE EJECUTIVO": config.p3_radio_executiu,
        "OTROS": config.p3_radio_altres,
    }[tipus_objecte]
    logging.info(f"[P3] Seleccionando tipo de objeto: {tipus_objecte}")
    await page.locator(radio_selector).first.click()

    # 2. Dades específiques
    logging.info("[P3] Introduciendo datos específicos...")
    await page.locator(config.p3_textarea_dades).first.fill(data.dades_especifiques)

    # 3. Tipo de solicitud (value del <select>)
    logging.info(f"[P3] Seleccionando tipo de solicitud: value={data.tipus_solicitud_value}")
    await page.locator(config.p3_select_tipus).first.select_option(value=str(data.tipus_solicitud_value))

    # 4. Exposición
    logging.info("[P3] Introduciendo exposición...")
    await page.locator(config.p3_textarea_exposo).first.fill(data.exposo)

    # 5. Solicitud
    logging.info("[P3] Introduciendo solicitud...")
    await page.locator(config.p3_textarea_solicito).first.fill(data.solicito)

    # 6. Botón Continuar
    logging.info("[P3] Pulsando el botón de continuar...")
    await page.locator(config.p3_button_continuar).first.click()

    await page.wait_for_load_state("domcontentloaded")
    logging.info(f"[P3] Paso 1 completado. URL actual: {page.url}")

    # 7. Subida de documentos (popup + iframe)
    await _subir_documento_p3(page, data.archivo_adjunto)

    # 7b. Continuar (paso Documentos -> Presentar solicitud)
    await _avanzar_a_presentacion_p3(page)
