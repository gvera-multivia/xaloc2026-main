from __future__ import annotations

import logging

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineTarget


_PROTOCOL_TO_LOCATOR = {
    "P1": "a[href*='tramit=M250']",
    "P2": "a[href*='tramit=M203']",
    "P3": "a[href*='/gir-ciutada/flow/recursTelematic']",
}


async def navegar_a_rama(page: Page, target: BaseOnlineTarget) -> None:
    protocol = (target.protocol or "").upper().strip()
    if protocol not in _PROTOCOL_TO_LOCATOR:
        raise ValueError(f"Protocolo inválido: {target.protocol}. Usa P1, P2 o P3.")

    logging.info(f"Seleccionando rama {protocol} desde Common Desktop...")
    selector = _PROTOCOL_TO_LOCATOR[protocol]
    enlace = page.locator(selector).first
    await enlace.wait_for(state="visible", timeout=20000)

    await enlace.click()
    await page.wait_for_load_state("domcontentloaded")
    logging.info(f"Rama {protocol} cargada: {page.url}")

