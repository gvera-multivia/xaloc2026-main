from __future__ import annotations

import json
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
    filename = download.suggested_filename or "atc_documento.pdf"
    destination = downloads_dir / filename
    await download.save_as(str(destination))
    logger.info("atc.confirmacion download_saved=%s", destination)

    if isinstance(datos.payload, dict):
        datos.payload["atc_download_pdf_path"] = str(destination)

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
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        if isinstance(datos.payload, dict):
            datos.payload["atc_pdf_text_path"] = str(txt_path)
            datos.payload["atc_pdf_meta_path"] = str(meta_path)
            datos.payload["atc_pdf_text_preview"] = full_text[:500]

        logger.info("atc.confirmacion pdfplumber_ok txt=%s meta=%s", txt_path, meta_path)
    except Exception as exc:
        logger.warning("atc.confirmacion pdfplumber_error=%s", exc)
    return page
