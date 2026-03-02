from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Page

from sites.redsara.config import RedSaraConfig
from sites.redsara.data_models import RedSaraTarget


def _collect_files(datos: RedSaraTarget) -> list[Path]:
    files: list[Path] = []

    recent_pdf = datos.recurso.recent_pdf or {}
    recent_pdf_path = recent_pdf.get("path")
    if isinstance(recent_pdf_path, str) and recent_pdf_path.strip():
        files.append(Path(recent_pdf_path))

    files.extend(datos.archivos_adjuntos)

    unique: list[Path] = []
    seen: set[str] = set()
    for f in files:
        key = str(f.resolve()) if f.exists() else str(f)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


async def subir_documentacion_redsara(page: Page, config: RedSaraConfig, datos: RedSaraTarget) -> Page:
    archivos = _collect_files(datos)
    existentes = [p for p in archivos if p.exists()]
    if not existentes:
        raise FileNotFoundError("redsara: no hay archivos existentes para subir en documentacion.")

    input_file = page.locator(config.selectors.attachments_input)
    await input_file.wait_for(state="attached", timeout=config.flow_timeouts.medium_wait)
    await input_file.set_input_files([str(p) for p in existentes])
    logging.info("redsara: subidos %s archivo(s)", len(existentes))

    await page.get_by_role("button", name="Siguiente").click()
    return page


async def confirmar_y_firmar_redsara(page: Page, config: RedSaraConfig) -> Page:
    await page.locator(config.selectors.final_checkbox_terms).first.wait_for(
        state="visible",
        timeout=config.flow_timeouts.long_wait,
    )
    await page.locator(config.selectors.final_checkbox_terms).first.click(force=True)
    await asyncio.sleep(0.7)

    boton_firma = page.locator(config.selectors.firmar_registrar_btn)
    await boton_firma.wait_for(state="visible", timeout=config.flow_timeouts.long_wait)
    await boton_firma.scroll_into_view_if_needed()
    await boton_firma.click(force=True)
    return page
