from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AtcConfig
    from ..data_models import AtcTarget


logger = logging.getLogger("xaloc_automation.atc")


async def run_login(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    _ = datos
    logger.info("atc.login goto=%s", config.url_base)
    page.set_default_timeout(config.default_timeout)
    page.set_default_navigation_timeout(config.navigation_timeout)
    await page.goto(config.url_base, wait_until="domcontentloaded")
    await page.wait_for_load_state("networkidle")

    # Cookie banner (codegen: "Acéptalas todas")
    try:
        await page.get_by_role(
            "button", name=re.compile(r"Ac[ée]ptalas todas|Aceptar todas|Accepta-les totes", re.IGNORECASE)
        ).first.click(timeout=5000)
        logger.info("atc.login cookies accepted")
    except Exception:
        logger.info("atc.login cookies button not found")

    logger.info("atc.login done")
    return page
