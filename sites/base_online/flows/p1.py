from __future__ import annotations

import logging

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineP1Data


async def _rellenar_contacto(page: Page, data: BaseOnlineP1Data) -> None:
    contacto = data.contacte
    if not (contacto.telefon_mobil or contacto.telefon_fix):
        raise ValueError("P1: es obligatorio informar al menos un teléfono (móvil o fijo).")

    if contacto.telefon_mobil:
        await page.locator("#form\\:telefon-alternatiu").first.fill(contacto.telefon_mobil)
    if contacto.telefon_fix:
        await page.locator("#form\\:telefon").first.fill(contacto.telefon_fix)
    if contacto.correu is not None:
        await page.locator("#form\\:mail_interessat").first.fill(contacto.correu)

    await page.locator("input[type='submit'][name='form:j_id20'][value='Continuar']").first.click()
    await page.wait_for_load_state("domcontentloaded")


async def _rellenar_identificacion_conductor(page: Page, data: BaseOnlineP1Data) -> None:
    info = data.identificacio

    await page.locator("#form\\:clau_expedient_id_ens").first.fill(info.expedient_id_ens)
    await page.locator("#form\\:clau_expedient_any_exp").first.fill(info.expedient_any)
    await page.locator("#form\\:clau_expedient_num_exp").first.fill(info.expedient_num)

    await page.evaluate(
        "typeof actualitzarClauExpedientclau_expedient === 'function' && actualitzarClauExpedientclau_expedient()"
    )

    await page.locator("#form\\:num_butlleti").first.fill(info.num_butlleti)
    await page.locator("#form\\:data_denuncia").first.fill(info.data_denuncia)
    await page.locator("#form\\:matricula").first.fill(info.matricula)
    await page.locator("#form\\:identificacio").first.fill(info.identificacio)
    await page.locator("#form\\:llicencia_conduccio").first.fill(info.llicencia_conduccio)
    await page.locator("#form\\:nom_complet").first.fill(info.nom_complet)

    # La "adreça" tiene ID duplicado (textarea readonly + input hidden). Seteamos ambos por JS.
    await page.evaluate(
        """(value) => {
          const nodes = document.querySelectorAll('#form\\\\:adreca');
          for (const el of nodes) {
            try { el.removeAttribute('readonly'); } catch (e) {}
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }""",
        info.adreca,
    )

    logging.info("[P1] Formulario 2 rellenado; avanzando al siguiente paso...")
    await page.locator("input[type='submit'][name='form:j_id24'][value='Continuar']").first.click()
    await page.wait_for_load_state("domcontentloaded")


async def ejecutar_p1(page: Page, data: BaseOnlineP1Data) -> None:
    logging.info("[P1] Rellenando pantalla 1 (contacto)...")
    await _rellenar_contacto(page, data)
    logging.info("[P1] Rellenando pantalla 2 (identificación conductor)...")
    await _rellenar_identificacion_conductor(page, data)

