from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AtcConfig
    from ..data_models import AtcTarget


logger = logging.getLogger("xaloc_automation.atc")


async def run_documentos(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    _ = (config, datos)
    logger.info("atc.documentos START")

    cert_btn = page.get_by_test_id("certificate-btn")
    if await cert_btn.count():
        logger.info("atc.documentos certificate-btn present, clicking")
        await cert_btn.first.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_load_state("networkidle")
    else:
        logger.info("atc.documentos certificate-btn not present, assuming already authenticated")

    await page.locator("#MainContent_CertificatDeuteControl_dpdTipusCertificat").select_option("GEN02")

    check_button = page.get_by_role(
        "button",
        name=re.compile(r"Comprobar|Comprova", re.IGNORECASE),
    ).first
    await check_button.click()

    await page.wait_for_load_state("networkidle")
    logger.info("atc.documentos done")
    return page
