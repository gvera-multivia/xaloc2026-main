from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from playwright.async_api import Page

DELAY_MS = 1000


def _is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except Exception:
        return False


def _load_pdf_merger():
    try:
        from pypdf import PdfMerger  # type: ignore

        return PdfMerger()
    except Exception:
        pass
    try:
        from PyPDF2 import PdfMerger  # type: ignore

        return PdfMerger()
    except Exception as e:
        raise RuntimeError("No hay backend PDF para fusionar adjuntos (pypdf/PyPDF2).") from e


def _bundle_files_if_needed(
    archivos: list[Path],
    *,
    max_archivos: int,
    output_dir: Path = Path("tmp/base_online/bundles"),
) -> list[Path]:
    if len(archivos) <= max_archivos:
        return archivos

    non_pdf = [str(p) for p in archivos if not _is_pdf_file(p)]
    if non_pdf:
        raise ValueError(
            f"BASE admite max {max_archivos} adjuntos y hay {len(archivos)}. "
            f"No se puede auto-fusionar porque hay no-PDF: {', '.join(non_pdf)}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"base_online_bundle_{int(time.time())}.pdf"

    merger = _load_pdf_merger()
    try:
        for pdf in archivos:
            merger.append(str(pdf))
        with out_path.open("wb") as fh:
            merger.write(fh)
    finally:
        try:
            merger.close()
        except Exception:
            pass

    if not out_path.exists() or not _is_pdf_file(out_path):
        raise RuntimeError(f"No se genero bundle PDF valido: {out_path}")

    logging.info(
        "Detectados %s adjuntos (> %s). Se fusionan en bundle unico: %s",
        len(archivos),
        max_archivos,
        out_path.name,
    )
    return [out_path]


async def subir_archivos_por_modal(
    page: Page,
    archivos: list[Path],
    *,
    max_archivos: int = 5,
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

    archivos_a_subir = [a for a in archivos if a]
    archivos_a_subir = _bundle_files_if_needed(archivos_a_subir, max_archivos=max_archivos)
    if not archivos_a_subir:
        logging.info("No hay archivos para subir.")
        return

    for idx, archivo in enumerate(archivos_a_subir, start=1):
        if not archivo.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {archivo}")

        logging.info(f"Subiendo archivo {idx}/{len(archivos_a_subir)}: {archivo.name}")

        # Asegurarse de que el botón de abrir está listo
        boton_abrir = page.get_by_role("button", name=re.compile(boton_abrir_regex, re.IGNORECASE)).first
        await boton_abrir.wait_for(state="visible", timeout=10000)
        await boton_abrir.click()
        await page.wait_for_timeout(DELAY_MS)

        modal = page.locator("#fitxer").first
        await modal.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(DELAY_MS)

        frame = page.frame_locator("#contingut_fitxer").first
        file_input = frame.locator("input[type='file'][name='qqfile']").first
        
        # Esperar al input y asegurar que el frame ha cargado algo
        await file_input.wait_for(state="attached", timeout=20000)
        await page.wait_for_timeout(DELAY_MS)

        logging.info(f"Estableciendo archivo en el input: {archivo.name}")
        await file_input.set_input_files(str(archivo.resolve()))
        
        # Retardo extra tras seleccionar para que la web procese el evento
        await page.wait_for_timeout(DELAY_MS * 1.5)

        boton_carregar = frame.locator("#penjar_fitxers").first
        if await boton_carregar.count() > 0:
            logging.info("Click en boton 'Penjar' / 'Carregar'...")
            await boton_carregar.click()
            await page.wait_for_timeout(DELAY_MS)

        logging.info("Esperando que aparezca el mensaje de exito (#textSuccess)...")
        success_text = frame.locator("#textSuccess").first
        
        # Esperar específicamente a que el texto contenga el nombre del archivo actual
        # para evitar confusiones con subidas previas si el iframe no se ha limpiado.
        try:
            # Intentamos esperar a que el texto del archivo aparezca
            await frame.locator("#textSuccess", has_text=archivo.name).wait_for(state="visible", timeout=30000)
        except Exception:
            logging.warning(f"No se detecto el nombre '{archivo.name}' en #textSuccess, esperando visibilidad generica.")
            await success_text.wait_for(state="visible", timeout=15000)

        texto = (await success_text.inner_text()).strip()
        logging.info(f"Resultado subida: {texto}")
        
        if archivo.name.lower() not in texto.lower():
            # Si el texto no coincide, lanzamos error para no seguir con un estado inconsistente
            raise RuntimeError(f"Upload no confirmado para {archivo.name}. Se recibió: '{texto}'")

        await page.wait_for_timeout(DELAY_MS)
        logging.info("Click en 'Continuar' para cerrar el modal.")
        await frame.locator("#continuar").first.click()
        
        await page.wait_for_timeout(DELAY_MS)
        await modal.wait_for(state="hidden", timeout=15000)
        await page.wait_for_timeout(DELAY_MS)
