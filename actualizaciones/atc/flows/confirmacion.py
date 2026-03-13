from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AtcConfig
    from ..data_models import AtcTarget


logger = logging.getLogger("xaloc_automation.atc")


async def run_confirmacion(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    _ = (config, datos)
    logger.info("atc.confirmacion START")
    await page.wait_for_load_state("domcontentloaded")

    view_button = page.get_by_role(
        "button",
        name=re.compile(r"Visualizar documento|Visualitza document", re.IGNORECASE),
    ).first

    async with page.expect_download() as dl_info:
        await view_button.click()
    download = await dl_info.value

    downloads_dir = Path("actualizaciones/atc/downloads")
    downloads_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(download.suggested_filename or "Certificado_atc.pdf").suffix or ".pdf"
    destination = downloads_dir / f"Certificado_atc{ext}"
    await download.save_as(str(destination))
    logger.info("atc.confirmacion download_saved=%s", destination)

    if isinstance(datos.payload, dict):
        datos.payload["atc_download_pdf_path"] = str(destination)

    return page
