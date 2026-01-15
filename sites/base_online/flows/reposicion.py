"""
Flujo para el formulario de Recurso de Reposición (P3).
"""

from __future__ import annotations

import logging
from playwright.async_api import Page
from sites.base_online.config import BaseOnlineConfig


async def rellenar_formulario_p3(page: Page, config: BaseOnlineConfig) -> None:
    logging.info("[P3] Rellenando formulario de Recurso de Reposición...")

    # 1. Seleccionar tipo de objeto (ej. IVTM)
    logging.info("[P3] Seleccionando tipo de objeto: IVTM")
    await page.locator(config.p3_radio_ivtm).click()

    # 2. Datos específicos
    logging.info("[P3] Introduciendo datos específicos...")
    await page.locator(config.p3_textarea_dades).fill("1234-ABC (Matrícula de prueba)")

    # 3. Tipo de solicitud (ej. Recurs de reposició - value "1")
    logging.info("[P3] Seleccionando tipo de solicitud: Recurs de reposició")
    await page.locator(config.p3_select_tipus).select_option("1")

    # 4. Exposición
    logging.info("[P3] Introduciendo exposición...")
    await page.locator(config.p3_textarea_exposo).fill("Exposición de motivos de prueba para el recurso.")

    # 5. Solicitud
    logging.info("[P3] Introduciendo solicitud...")
    await page.locator(config.p3_textarea_solicito).fill("Solicitud de prueba para el recurso.")

    # 6. Botón de continuar
    logging.info("[P3] Pulsando el botón de continuar...")
    await page.locator(config.p3_button_continuar).click()

    await page.wait_for_load_state("domcontentloaded")
    logging.info(f"[P3] Formulario enviado. URL actual: {page.url}")
