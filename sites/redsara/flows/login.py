from __future__ import annotations

from playwright.async_api import Page

from sites.redsara.config import RedSaraConfig
from sites.redsara.flows.certificado import aceptar_certificado_clave_si_aparece


async def ejecutar_login_redsara(page: Page, config: RedSaraConfig) -> Page:
    await page.goto(config.url_base, wait_until="domcontentloaded")
    await page.locator(config.selectors.nuevo_registro_link).first.click()
    await aceptar_certificado_clave_si_aparece(page, config, timeout=config.flow_timeouts.medium_wait)
    await page.wait_for_url("**/nuevo-registro**", timeout=config.flow_timeouts.long_wait)
    return page
