from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .common import click_and_wait, click_role_and_wait

if TYPE_CHECKING:
    from playwright.async_api import Page

    from ..config import ValenciaConfig
    from ..data_models import ValenciaTarget


async def _select_procedure(page: "Page", datos: "ValenciaTarget", config: "ValenciaConfig") -> None:
    url = config.url_mu_de_30
    if datos.tramite_code == "MU.DE.50":
        url = config.url_mu_de_50
    elif datos.tramite_code == "MU.SA.40":
        url = config.url_mu_sa_40

    await page.goto(url)
    await page.wait_for_load_state("networkidle")


async def run_login(page: "Page", config: "ValenciaConfig", datos: "ValenciaTarget") -> "Page":
    await _select_procedure(page, datos, config)
    await click_and_wait(page, config.iniciar_tramite_selector)

    if datos.tramite_code in {"MU.DE.30", "MU.DE.50"}:
        await click_role_and_wait(page, role="button", name_pattern=r"Seg\u00fcent|Seguent|Siguiente")

    await click_role_and_wait(page, role="button", name_pattern=r"Accedir amb certificat|Acceder con certificado")
    await click_role_and_wait(page, role="button", name_pattern=r"Entitat|Entidad")

    try:
        await page.get_by_role(
            "link",
            name=re.compile(r"Nou tr\u00e0mit|Nou tramit|Nuevo tr\u00e1mite|Nuevo tramite", re.IGNORECASE),
        ).first.click(timeout=5000)
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass

    if datos.tramite_code == "MU.DE.50":
        await click_and_wait(page, 'input[type="radio"][value="MU.DE.50_002"]')
        await click_role_and_wait(page, role="button", name_pattern=r"Seg\u00fcent|Seguent|Siguiente")

    await click_and_wait(page, '[id="formRepresentacion:radioButtonRepresentacionEntidad:1"]')
    await click_role_and_wait(page, role="button", name_pattern=r"Seg\u00fcent|Seguent|Siguiente")

    iniciar = page.get_by_role("button", name="Iniciar")
    await iniciar.wait_for(state="visible")
    await iniciar.click()
    await page.wait_for_load_state("networkidle")
    return page
