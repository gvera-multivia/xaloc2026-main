from __future__ import annotations

import json
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

    try:
        import pdfplumber  # type: ignore

        pages_text: list[str] = []
        with pdfplumber.open(str(destination)) as pdf:
            for p in pdf.pages:
                pages_text.append((p.extract_text() or "").strip())
        full_text = "\n\n".join(t for t in pages_text if t).strip()

        txt_path = destination.with_suffix(".txt")
        txt_path.write_text(full_text, encoding="utf-8")
        meta = {
            "pdf_path": str(destination),
            "txt_path": str(txt_path),
            "pages": len(pages_text),
            "chars": len(full_text),
        }
        meta_path = destination.with_suffix(".json")
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if isinstance(datos.payload, dict):
            datos.payload["ajuntament_barcelona_pdf_text_path"] = str(txt_path)
            datos.payload["ajuntament_barcelona_pdf_meta_path"] = str(meta_path)
            datos.payload["ajuntament_barcelona_pdf_text_preview"] = full_text[:500]
        logger.info(
            "ajuntament_barcelona.confirmacion pdfplumber_ok txt=%s meta=%s",
            txt_path,
            meta_path,
        )
    except Exception as exc:
        logger.warning("ajuntament_barcelona.confirmacion pdfplumber_error=%s", exc)

    logger.info("ajuntament_barcelona.confirmacion done")
    return page
