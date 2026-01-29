from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.async_api import Page

DELAY_MS = 500


async def subir_archivos_por_modal(
    page: Page,
    archivos: list[Path],
    *,
    max_archivos: int = 1,
    boton_abrir_regex: str = r"Carregar\s+fitxer",
) -> None:
    """
    Subida de archivos vía modal + iframe (patrón usado en BASE: P1/P2/P3).

    Flujo:
    - Click "Carregar fitxer"
    - Modal #fitxer visible con iframe #contingut_fitxer
    - input[type=file][name=qqfile] + botón #penjar_fitxers
    - esperar #textSuccess
    - click #continuar y esperar que el modal se cierre
    """

    archivos_a_subir = [a for a in archivos if a][: max(0, max_archivos)]
    if not archivos_a_subir:
        logging.info("No hay archivos para subir.")
        return

    for idx, archivo in enumerate(archivos_a_subir, start=1):
        if not archivo.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {archivo}")

        logging.info(f"Subiendo archivo {idx}/{len(archivos_a_subir)}: {archivo}")

        await page.get_by_role("button", name=re.compile(boton_abrir_regex, re.IGNORECASE)).first.click()
        await page.wait_for_timeout(DELAY_MS)

        modal = page.locator("#fitxer").first
        await modal.wait_for(state="visible", timeout=15000)

        frame = page.frame_locator("#contingut_fitxer").first
        file_input = frame.locator("input[type='file'][name='qqfile']").first
        await file_input.wait_for(state="attached", timeout=20000)
        await file_input.set_input_files(str(archivo.resolve()))
        await page.wait_for_timeout(DELAY_MS)

        boton_carregar = frame.locator("#penjar_fitxers").first
        if await boton_carregar.count() > 0:
            await boton_carregar.click()
            await page.wait_for_timeout(DELAY_MS)

        success_text = frame.locator("#textSuccess").first
        await success_text.wait_for(state="visible", timeout=30000)
        texto = (await success_text.inner_text()).strip()
        if archivo.name.lower() not in texto.lower():
            raise RuntimeError(f"Upload no confirmado. textSuccess='{texto}'")

        await frame.locator("#continuar").first.click()
        await page.wait_for_timeout(DELAY_MS)
        await modal.wait_for(state="hidden", timeout=15000)
        await page.wait_for_timeout(DELAY_MS)
