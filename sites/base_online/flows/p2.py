from __future__ import annotations

import logging

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineP2Data
from sites.base_online.flows.common import rellenar_contacto


async def ejecutar_p2(page: Page, data: BaseOnlineP2Data) -> None:
    logging.info("[P2] Rellenando formulario de alegaciones (paso 1)...")

    await page.locator("#form\\:nif").first.fill(data.nif)
    await page.locator("#form\\:rao_social").first.fill(data.rao_social)

    await rellenar_contacto(page, data.contacte)

    await page.locator("input[type='submit'][name='form:j_id20'][value='Continuar']").first.click()
    await page.wait_for_load_state("domcontentloaded")

