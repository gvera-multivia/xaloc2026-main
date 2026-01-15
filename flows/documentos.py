"""
Flujo de subida de documentos (adjuntos)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Sequence, Union

from playwright.async_api import Page, TimeoutError


def _normalizar_archivos(archivos: Union[None, Path, Sequence[Path]]) -> List[Path]:
    if archivos is None:
        return []
    if isinstance(archivos, Path):
        return [archivos]
    return [a for a in archivos if a is not None]


def _validar_extension(archivo: Path) -> None:
    ext = archivo.suffix.lower().lstrip(".")
    if ext not in {"jpg", "jpeg", "pdf"}:
        raise ValueError(f"Extensión no permitida: {archivo.name} (solo jpg, jpeg, pdf)")


async def _subir_en_popup(popup: Page, archivo: Path) -> None:
    input_file = popup.locator("#fichero, input[type='file']").first
    await input_file.wait_for(state="visible", timeout=20000)
    await input_file.set_input_files(archivo)

    posibles_botones = [
        popup.get_by_role("button", name="Adjuntar"),
        popup.get_by_role("button", name="Aceptar"),
        popup.get_by_role("button", name="Enviar"),
        popup.get_by_role("button", name="Subir"),
        popup.locator("input[type='submit']"),
        popup.locator("button[type='submit']"),
    ]
    for boton in posibles_botones:
        try:
            if await boton.count() > 0:
                await boton.first.click(timeout=1500)
                break
        except Exception:
            continue

    await popup.wait_for_load_state("networkidle")


async def subir_documento(page: Page, archivo: Union[None, Path, Sequence[Path]]) -> None:
    """
    Sube uno o varios documentos adjuntos al trámite.

    Args:
        page: Página de Playwright (STA)
        archivo: `Path` o lista de `Path` (opcional)
    """

    archivos = _normalizar_archivos(archivo)
    if not archivos:
        logging.info("Sin archivos para adjuntar, saltando...")
        return

    for a in archivos:
        if not a.exists():
            raise FileNotFoundError(str(a))
        _validar_extension(a)

    for a in archivos:
        logging.info(f"Subiendo: {a.name}")

        docs_link = page.locator("a.docs").first
        popup: Optional[Page] = None
        try:
            async with page.expect_popup(timeout=7000) as popup_info:
                await docs_link.click()
            popup = await popup_info.value
        except TimeoutError:
            popup = None

        if popup is None:
            await page.wait_for_timeout(500)
            await _subir_en_popup(page, a)
        else:
            await popup.wait_for_load_state("domcontentloaded")
            await _subir_en_popup(popup, a)
            try:
                await popup.wait_for_event("close", timeout=15000)
            except TimeoutError:
                await popup.close()

        await page.wait_for_timeout(1000)
        await page.wait_for_load_state("networkidle")

    logging.info("Documentos subidos")

