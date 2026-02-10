from __future__ import annotations

import logging

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineP2Data
from sites.base_online.flows.common import rellenar_contacto
from sites.base_online.flows.firma_y_justificante import firmar_presentar_y_descargar_justificante
from sites.base_online.flows.upload import subir_archivos_por_modal

DELAY_MS = 500


async def ejecutar_p2(page: Page, data: BaseOnlineP2Data, *, payload: dict) -> None:
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
    butlleti_value = (
        (data.butlleti or "").strip()
        or str(payload.get("num_butlleti") or "").strip()
        or str(payload.get("expediente") or "").strip()
    )
    tiene_butlleti = bool(butlleti_value)
    if not (tiene_expediente or tiene_butlleti):
        raise ValueError("P2: es obligatorio indicar Num. Expedient o Num. Butlleti.")

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
        locator_butlleti = page.locator("#form\\:butlleti").first
        await locator_butlleti.fill(butlleti_value)
        await page.wait_for_timeout(DELAY_MS)
        # Some JSF variants do not persist fill() unless input/change events are dispatched.
        await page.evaluate(
            """([selector, value]) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                el.value = value;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }""",
            ["#form\\:butlleti", butlleti_value],
        )
        await page.wait_for_timeout(DELAY_MS)
        logging.info("[P2] Butlleti informado: %s", butlleti_value)

    await page.locator("#form\\:exposo").first.fill(data.exposo or "")
    await page.wait_for_timeout(DELAY_MS)
    await page.locator("#form\\:solicito").first.fill(data.solicito or "")
    await page.wait_for_timeout(DELAY_MS)

    await page.locator("input[type='submit'][name='form:j_id24'][value='Continuar']").first.click()
    await page.wait_for_timeout(DELAY_MS)
    await page.wait_for_load_state("domcontentloaded")

    logging.info("[P2] Subiendo documentos (paso 3)...")
    archivos = list(data.archivos_adjuntos or [])
    if not archivos:
        raise ValueError("P2: falta 'archivos_adjuntos' (al menos 1 archivo).")
    await subir_archivos_por_modal(page, archivos)

    await page.locator("input[type='submit'][name='form:j_id29'][value='Continuar']").first.click()
    await page.wait_for_timeout(DELAY_MS)
    await page.wait_for_load_state("domcontentloaded")

    logging.info("[P2] Preparando firma y presentacion...")
    await firmar_presentar_y_descargar_justificante(page, payload=payload)
