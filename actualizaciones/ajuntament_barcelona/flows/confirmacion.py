from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AjuntamentBarcelonaConfig
    from ..data_models import AjuntamentBarcelonaTarget


logger = logging.getLogger("xaloc_automation.ajuntament_barcelona")


async def run_confirmacion(
    page: "Page",
    config: "AjuntamentBarcelonaConfig",
    datos: "AjuntamentBarcelonaTarget",
) -> "Page":
    logger.info("ajuntament_barcelona.confirmacion START")
    await page.wait_for_load_state("domcontentloaded")

    download_link = page.get_by_role(
        "link",
        name=re.compile(
            r"Certificat negatiu de deute|Certificado negativo de deuda", re.IGNORECASE
        ),
    ).first

    try:
        await download_link.wait_for(state="visible", timeout=5000)
    except Exception:
        # Fallback: navegar directamente a la URL de confirmacion segun idioma detectado.
        current_url = page.url.lower()
        target_url = (
            config.url_confirm_es if "/es/" in current_url else config.url_confirm_ca
        )
        await page.goto(target_url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")
        download_link = page.get_by_role(
            "link",
            name=re.compile(
                r"Certificat negatiu de deute|Certificado negativo de deuda",
                re.IGNORECASE,
            ),
        ).first

    async with page.expect_download() as dl_info:
        await download_link.click()
    download = await dl_info.value

    downloads_dir = Path("actualizaciones/ajuntament_barcelona/downloads")
    downloads_dir.mkdir(parents=True, exist_ok=True)
    filename = download.suggested_filename or "ajuntament_barcelona_documento.pdf"
    destination = downloads_dir / filename
    await download.save_as(str(destination))
    logger.info("ajuntament_barcelona.confirmacion download_saved=%s", destination)

    if isinstance(datos.payload, dict):
        datos.payload["ajuntament_barcelona_download_pdf_path"] = str(destination)

    logger.info("ajuntament_barcelona.confirmacion done")
    return page
