from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AtcConfig
    from ..data_models import AtcTarget


logger = logging.getLogger("xaloc_automation.atc")


async def run_formulario(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    _ = (config, datos)

    logger.info("atc.formulario START")
    await page.wait_for_load_state("domcontentloaded")

    start_link = page.get_by_role(
        "link",
        name=re.compile(r"Inicia el tr.*mit|Iniciar tr.*mit", re.IGNORECASE),
    ).first

    popup_page = None
    try:
        async with page.expect_popup(timeout=8000) as popup_info:
            await start_link.click()
        popup_page = await popup_info.value
        logger.info("atc.formulario popup opened")
    except Exception:
        logger.info("atc.formulario popup not detected, fallback same tab")
        await start_link.click()

    active_page = popup_page or page
    await active_page.wait_for_load_state("domcontentloaded")
    await active_page.wait_for_load_state("networkidle")
    logger.info("atc.formulario active url=%s", active_page.url)
    return active_page
