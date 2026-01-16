from __future__ import annotations

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineP1ContactData


async def rellenar_contacto(page: Page, contacto: BaseOnlineP1ContactData) -> None:
    if not (contacto.telefon_mobil or contacto.telefon_fix):
        raise ValueError("Es obligatorio informar al menos un teléfono (móvil o fijo).")

    if contacto.telefon_mobil:
        await page.locator("#form\\:telefon-alternatiu").first.fill(contacto.telefon_mobil)
    if contacto.telefon_fix:
        await page.locator("#form\\:telefon").first.fill(contacto.telefon_fix)
    if contacto.correu is not None:
        await page.locator("#form\\:mail_interessat").first.fill(contacto.correu)

