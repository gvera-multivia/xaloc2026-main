from __future__ import annotations

import logging

from playwright.async_api import Page

from sites.base_online.data_models import BaseOnlineTarget

DELAY_MS = 500


_PROTOCOL_TO_URL = {
    "P1": "https://www.baseonline.cat/pst/flow/formulari?tramit=M250",
    "P2": "https://www.baseonline.cat/pst/flow/formulari?tramit=M203",
    "P3": "https://www.baseonline.cat/gir-ciutada/flow/recursTelematic",
}


async def navegar_a_rama(page: Page, target: BaseOnlineTarget) -> None:
    protocol = (target.protocol or "").upper().strip()
    if protocol not in _PROTOCOL_TO_URL:
        raise ValueError(f"Protocolo inválido: {target.protocol}. Usa P1, P2 o P3.")

    url_destino = _PROTOCOL_TO_URL[protocol]
    logging.info(f"Navegando directamente a rama {protocol}: {url_destino}")
    
    # Navegación directa para evitar problemas con menús desplegables ocultos
    await page.goto(url_destino, wait_until="domcontentloaded")
    await page.wait_for_timeout(DELAY_MS)
    
    # Verificación simple para confirmar que no estamos en una página de error
    logging.info(f"Rama {protocol} cargada. URL actual: {page.url}")
