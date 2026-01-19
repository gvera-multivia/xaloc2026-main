"""
Flujo para el formulario de Recurso de Reposición (P3).
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Page

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineReposicionData
from sites.base_online.flows.upload import subir_archivos_por_modal


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


async def _avanzar_a_presentacion_p3(page: Page) -> None:
    logging.info("[P3] Continuando al paso de presentación...")
    await page.locator("input[type='submit'][name='form0:j_id66'][value='Continuar']").first.click()
    await page.wait_for_timeout(500)
    await page.wait_for_load_state("domcontentloaded")

    boton_firma = page.locator("input[type='button'][value='Signar i Presentar']").first
    await boton_firma.wait_for(state="visible", timeout=20000)
    logging.info("[P3] Pantalla 'Signar i Presentar' detectada (no se pulsa en modo demo).")


async def rellenar_formulario_p3(page: Page, config: BaseOnlineConfig, data: BaseOnlineReposicionData) -> None:
    logging.info("[P3] Rellenando formulario de Recurso de Reposición...")
    delay_ms = getattr(config, "delay_ms", 500)

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
    await page.wait_for_timeout(delay_ms)

    # 2. Dades específiques
    logging.info("[P3] Introduciendo datos específicos...")
    await page.locator(config.p3_textarea_dades).first.fill(data.dades_especifiques)
    await page.wait_for_timeout(delay_ms)

    # 3. Tipo de solicitud
    logging.info(f"[P3] Seleccionando tipo de solicitud: value={data.tipus_solicitud_value}")
    await page.locator(config.p3_select_tipus).first.select_option(value=str(data.tipus_solicitud_value))
    await page.wait_for_timeout(delay_ms)

    # 4. Exposición
    logging.info("[P3] Introduciendo exposición...")
    await page.locator(config.p3_textarea_exposo).first.fill(data.exposo)
    await page.wait_for_timeout(delay_ms)

    # 5. Solicitud
    logging.info("[P3] Introduciendo solicitud...")
    await page.locator(config.p3_textarea_solicito).first.fill(data.solicito)
    await page.wait_for_timeout(delay_ms)

    # 6. Botón Continuar (Página 1 -> Página Documentos)
    logging.info("[P3] Pulsando el botón de continuar...")
    await page.locator(config.p3_button_continuar).first.click()
    await page.wait_for_timeout(delay_ms)
    await page.wait_for_load_state("domcontentloaded")

    # 7. Subida de documentos (modal + iframe)
    archivos = data.archivos_adjuntos or []
    archivos_paths: list[Path] = list(archivos)
    await subir_archivos_por_modal(page, archivos_paths, max_archivos=1)

    # 8. Confirmación (llegar hasta la pantalla de firma)
    await _avanzar_a_presentacion_p3(page)
