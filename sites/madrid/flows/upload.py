"""
Flujo de subida de documentos (adjuntos) para Madrid Ayuntamiento.

Reglas del trámite:
- Máximo 13 documentos.
- Máximo 15 MB en total.
- Máximo 10 MB por documento.
- Extensiones permitidas según el formulario.
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)

MAX_DOCUMENTOS = 13
MAX_TOTAL_BYTES = 15 * 1024 * 1024
MAX_POR_DOC_BYTES = 10 * 1024 * 1024

EXTENSIONES_PERMITIDAS = {
    "accdb",
    "bmp",
    "csig",
    "css",
    "csv",
    "dgn",
    "doc",
    "docx",
    "dot",
    "dsig",
    "dwg",
    "dxf",
    "gif",
    "gml",
    "gzip",
    "htm",
    "html",
    "iee",
    "ifc",
    "jpeg",
    "jpg",
    "mdb",
    "mht",
    "mhtml",
    "nwc",
    "odg",
    "odp",
    "ods",
    "odt",
    "pdf",
    "png",
    "pps",
    "ppt",
    "pptx",
    "p7s",
    "rar",
    "rtf",
    "rvt",
    "shp",
    "sig",
    "svg",
    "tar",
    "tif",
    "tiff",
    "txt",
    "xhtml",
    "xls",
    "xlsx",
    "xlt",
    "xml",
    "xsig",
    "zip",
}


def _selector_input_archivo(idx: int) -> str:
    return (
        "input[type='file']"
        f"[name='formDesigner:_id21:2:_id28:{idx}:_id31:0:_id35:0:_id679']"
    )


def _selector_boton_mas(idx: int) -> str:
    return f"input[id='formDesigner:_id21:2:_id28:{idx}:_id684'].anadirRepetible"


def _normalizar_extension(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _validar_archivos(archivos: list[Path]) -> None:
    if not archivos:
        return

    if len(archivos) > MAX_DOCUMENTOS:
        raise ValueError(f"Demasiados documentos: {len(archivos)} (máx {MAX_DOCUMENTOS}).")

    total = 0
    for archivo in archivos:
        if not archivo.exists():
            raise FileNotFoundError(f"No existe el archivo: {archivo}")

        ext = _normalizar_extension(archivo)
        if ext not in EXTENSIONES_PERMITIDAS:
            raise ValueError(f"Extensión no permitida: .{ext} ({archivo.name})")

        size = archivo.stat().st_size
        if size > MAX_POR_DOC_BYTES:
            raise ValueError(f"Archivo demasiado grande (>10MB): {archivo.name} ({size} bytes)")

        total += size

    if total > MAX_TOTAL_BYTES:
        raise ValueError(f"Tamaño total demasiado grande (>15MB): {total} bytes")


async def ejecutar_upload_madrid(page: Page, config: MadridConfig, archivos: list[Path]) -> Page:
    """
    Sube adjuntos en la pantalla posterior al formulario.

    - Para cada archivo i:
      - set_input_files() sobre el input con name que incluye `_id28:i:...:_id679`
      - click en el botón "más" (`duplica_repetir`) para crear el siguiente input (excepto el último)
    - Finalmente, pulsar "Continuar" para avanzar a la pantalla de firma (que NO se ejecuta).
    """
    _validar_archivos(archivos)
    if not archivos:
        logger.info("Sin adjuntos, saltando subida de documentos")
        return page

    logger.info(f"ADJUNTOS: subiendo {len(archivos)} documento(s)")

    await page.wait_for_selector(_selector_input_archivo(0), state="attached", timeout=config.default_timeout)

    for idx, archivo in enumerate(archivos):
        selector_input = _selector_input_archivo(idx)
        await page.wait_for_selector(selector_input, state="visible", timeout=config.default_timeout)

        await page.set_input_files(selector_input, str(archivo))
        logger.info(f"  Adjuntado [{idx + 1}/{len(archivos)}]: {archivo.name}")

        if idx < len(archivos) - 1:
            selector_mas = _selector_boton_mas(idx)
            await page.wait_for_selector(selector_mas, state="visible", timeout=config.default_timeout)
            await page.click(selector_mas)

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except PlaywrightTimeoutError:
                pass

            await page.wait_for_selector(
                _selector_input_archivo(idx + 1),
                state="attached",
                timeout=config.default_timeout,
            )

    await page.wait_for_selector(config.adjuntos_continuar_selector, state="visible", timeout=config.default_timeout)
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.adjuntos_continuar_selector)

    logger.info("Adjuntos subidos; pantalla de firma alcanzada (no se ejecuta la firma en modo demo)")
    return page

