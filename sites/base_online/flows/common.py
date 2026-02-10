from __future__ import annotations

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineP1ContactData

DELAY_MS = 500


async def rellenar_contacto(page: Page, contacto: BaseOnlineP1ContactData) -> None:
    if not (contacto.telefon_mobil or contacto.telefon_fix):
        raise ValueError("Es obligatorio informar al menos un telefono (movil o fijo).")

    telefon_principal = (contacto.telefon_fix or contacto.telefon_mobil or "").strip()
    telefon_alternatiu = None
    if contacto.telefon_fix and contacto.telefon_mobil:
        telefon_alternatiu = contacto.telefon_mobil.strip()

    if telefon_principal:
        locator_telefon = page.locator("#form\\:telefon").first
        if await locator_telefon.count() > 0:
            await locator_telefon.fill(telefon_principal)
            await page.wait_for_timeout(DELAY_MS)

    if telefon_alternatiu:
        locator_alt = page.locator("#form\\:telefon-alternatiu").first
        if await locator_alt.count() > 0:
            await locator_alt.fill(telefon_alternatiu)
            await page.wait_for_timeout(DELAY_MS)

    if contacto.correu is not None:
        await page.locator("#form\\:mail_interessat").first.fill(contacto.correu)
        await page.wait_for_timeout(DELAY_MS)
