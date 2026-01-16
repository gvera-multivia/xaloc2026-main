"""
Flujo para el formulario de Recurso de Reposición (P3) - paso 1/3.
"""

from __future__ import annotations

import logging

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


async def rellenar_formulario_p3(page: Page, config: BaseOnlineConfig, data: BaseOnlineReposicionData) -> None:
    logging.info("[P3] Rellenando formulario de Recurso de Reposición (paso 1/3)...")

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
    logging.info(f"[P3] Formulario enviado. URL actual: {page.url}")

