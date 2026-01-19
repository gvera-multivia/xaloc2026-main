from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineP2Data
from sites.base_online.flows.common import rellenar_contacto
from sites.base_online.flows.upload import subir_archivos_por_modal

DELAY_MS = 500


async def ejecutar_p2(page: Page, data: BaseOnlineP2Data) -> None:
    logging.info("[P2] Rellenando formulario de alegaciones (paso 1)...")

    await page.locator("#form\\:nif").first.fill(data.nif)
    await page.wait_for_timeout(DELAY_MS)
    await page.locator("#form\\:rao_social").first.fill(data.rao_social)
    await page.wait_for_timeout(DELAY_MS)

    await rellenar_contacto(page, data.contacte)

    await page.locator("input[type='submit'][name='form:j_id20'][value='Continuar']").first.click()
    await page.wait_for_timeout(DELAY_MS)
    await page.wait_for_load_state("domcontentloaded")

    logging.info("[P2] Aportando alegaciones (paso 2)...")
    tiene_expediente = bool(data.expedient_id_ens or data.expedient_any or data.expedient_num)
    tiene_butlleti = bool(data.butlleti and data.butlleti.strip())
    if not (tiene_expediente or tiene_butlleti):
        raise ValueError("P2: es obligatorio indicar Núm. Expedient o Núm. Butlletí.")

    if tiene_expediente:
        await page.locator("#form\\:clau_expedient_id_ens").first.fill(data.expedient_id_ens or "")
        await page.wait_for_timeout(DELAY_MS)
        await page.locator("#form\\:clau_expedient_any_exp").first.fill(data.expedient_any or "")
        await page.wait_for_timeout(DELAY_MS)
        await page.locator("#form\\:clau_expedient_num_exp").first.fill(data.expedient_num or "")
        await page.wait_for_timeout(DELAY_MS)
        await page.evaluate(
            "typeof actualitzarClauExpedientclau_expedient === 'function' && actualitzarClauExpedientclau_expedient()"
        )
        await page.wait_for_timeout(DELAY_MS)

    if tiene_butlleti:
        await page.locator("#form\\:butlleti").first.fill(data.butlleti or "")
        await page.wait_for_timeout(DELAY_MS)

    await page.locator("#form\\:exposo").first.fill(data.exposo or "")
    await page.wait_for_timeout(DELAY_MS)
    await page.locator("#form\\:solicito").first.fill(data.solicito or "")
    await page.wait_for_timeout(DELAY_MS)

    await page.locator("input[type='submit'][name='form:j_id24'][value='Continuar']").first.click()
    await page.wait_for_timeout(DELAY_MS)
    await page.wait_for_load_state("domcontentloaded")

    logging.info("[P2] Subiendo documentos (paso 3)...")
    archivos = data.archivos_adjuntos or [Path("pdfs-prueba/test1.pdf")]
    await subir_archivos_por_modal(page, list(archivos), max_archivos=1)

    await page.locator("input[type='submit'][name='form:j_id29'][value='Continuar']").first.click()
    await page.wait_for_timeout(DELAY_MS)
    await page.wait_for_load_state("domcontentloaded")

    boton_firma = page.locator("input[type='button'][value='Signar i Presentar']").first
    if await boton_firma.count() > 0:
        logging.info("[P2] Pantalla 'Signar i Presentar' detectada (no se pulsa en modo demo).")
