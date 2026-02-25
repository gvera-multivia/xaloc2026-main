from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from playwright.async_api import Page

from core.pdf_bundle import bundle_documents_to_single_pdf_for_palma

DELAY_MS = 1000
BASE_MAX_UPLOAD_BYTES = int((os.getenv("BASE_ONLINE_MAX_UPLOAD_BYTES") or str(9 * 1024 * 1024)).strip())
BASE_UPLOAD_SAFETY_BYTES = int((os.getenv("BASE_ONLINE_UPLOAD_SAFETY_BYTES") or str(256 * 1024)).strip())
BASE_PARTITION_TARGET_BYTES = max(1, BASE_MAX_UPLOAD_BYTES - BASE_UPLOAD_SAFETY_BYTES)


def _is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except Exception:
        return False


def _bundle_files_if_needed(
    archivos: list[Path],
    *,
    max_archivos: int,
    output_dir: Path = Path("tmp/base_online/bundles"),
) -> list[Path]:
    def _size(path: Path) -> int:
        try:
            return int(path.stat().st_size)
        except Exception:
            return 0

    def _find_gs() -> str | None:
        for exe in ("gs", "gswin64c", "gswin32c"):
            found = shutil.which(exe)
            if found:
                return found
        return None

    def _compress_pdf_gs(src: Path, *, profile: str = "/ebook") -> Path | None:
        gs = _find_gs()
        if not gs:
            return None
        out = src.with_name(f"{src.stem}.compressed{src.suffix}")
        cmd = [
            gs,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={profile}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={str(out)}",
            str(src),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            if out.exists() and _is_pdf_file(out):
                return out
        except Exception as e:
            logging.warning("Compresion Ghostscript fallida para %s (%s): %s", src.name, profile, e)
        return None

    def _first_fit_partition(items: list[Path], *, max_bins: int, capacity_bytes: int) -> list[list[Path]] | None:
        bins: list[tuple[list[Path], int]] = []
        sorted_items = sorted(items, key=lambda p: _size(p), reverse=True)
        for item in sorted_items:
            item_size = _size(item)
            if item_size > BASE_MAX_UPLOAD_BYTES:
                return None
            placed = False
            for idx, (bucket, used) in enumerate(bins):
                if used + item_size <= capacity_bytes:
                    bucket.append(item)
                    bins[idx] = (bucket, used + item_size)
                    placed = True
                    break
            if placed:
                continue
            if len(bins) >= max_bins:
                return None
            bins.append(([item], item_size))
        return [bucket for bucket, _ in bins]

    normalized = [Path(p) for p in archivos if p]
    if not normalized:
        return []

    # Compresion previa de PDFs individuales que ya exceden 10MB
    prepared: list[Path] = []
    for p in normalized:
        if _size(p) <= BASE_MAX_UPLOAD_BYTES:
            prepared.append(p)
            continue
        if not _is_pdf_file(p):
            raise ValueError(
                f"Archivo supera {BASE_MAX_UPLOAD_BYTES} bytes y no es PDF (no se puede comprimir): {p}"
            )
        compressed = _compress_pdf_gs(p, profile="/ebook") or _compress_pdf_gs(p, profile="/screen")
        if compressed and _size(compressed) <= BASE_MAX_UPLOAD_BYTES:
            logging.info(
                "PDF comprimido para cumplir limite BASE: %s (%s -> %s bytes)",
                p.name,
                _size(p),
                _size(compressed),
            )
            prepared.append(compressed)
        else:
            raise ValueError(
                f"No se pudo reducir por debajo de 10MB el archivo {p.name} "
                f"(tamano={_size(p)} bytes)."
            )

    if len(prepared) <= max_archivos and all(_size(p) <= BASE_MAX_UPLOAD_BYTES for p in prepared):
        return prepared

    non_pdf = [str(p) for p in prepared if not _is_pdf_file(p)]
    if non_pdf:
        raise ValueError(
            f"BASE admite max {max_archivos} adjuntos y hay {len(prepared)}. "
            f"No se puede auto-fusionar porque hay no-PDF: {', '.join(non_pdf)}"
        )

    partitions = _first_fit_partition(
        prepared,
        max_bins=max_archivos,
        capacity_bytes=BASE_PARTITION_TARGET_BYTES,
    )
    if partitions is None:
        partitions = _first_fit_partition(
            prepared,
            max_bins=max_archivos,
            capacity_bytes=BASE_MAX_UPLOAD_BYTES,
        )
    if partitions is None:
        raise ValueError(
            f"No se puede repartir {len(prepared)} documentos en {max_archivos} adjuntos cumpliendo 10MB por archivo."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for idx, group in enumerate(partitions, start=1):
        if len(group) == 1:
            outputs.append(group[0])
            continue
        out_path = bundle_documents_to_single_pdf_for_palma(
            group,
            id_recurso=f"base_online_part_{idx}",
            output_dir=output_dir,
        )
        outputs.append(out_path)

    # Si algun bundle supero 10MB por overhead, intento comprimirlo.
    normalized_outputs: list[Path] = []
    for out in outputs:
        out_size = _size(out)
        if out_size <= BASE_MAX_UPLOAD_BYTES:
            normalized_outputs.append(out)
            continue
        compressed = _compress_pdf_gs(out, profile="/ebook") or _compress_pdf_gs(out, profile="/screen")
        if compressed and _size(compressed) <= BASE_MAX_UPLOAD_BYTES:
            logging.info(
                "Bundle comprimido para cumplir limite BASE: %s (%s -> %s bytes)",
                out.name,
                out_size,
                _size(compressed),
            )
            normalized_outputs.append(compressed)
        else:
            raise ValueError(
                f"Bundle supera 10MB y no se pudo comprimir: {out.name} ({out_size} bytes)"
            )

    logging.info(
        "Preparados %s adjuntos para BASE (max=%s, limite=%s bytes): %s",
        len(normalized_outputs),
        max_archivos,
        BASE_MAX_UPLOAD_BYTES,
        ", ".join(f"{p.name} ({_size(p)}B)" for p in normalized_outputs),
    )
    return normalized_outputs


async def subir_archivos_por_modal(
    page: Page,
    archivos: list[Path],
    *,
    max_archivos: int = 5,
    boton_abrir_regex: str = r"Carregar\s+fitxer",
) -> None:
    """
    Subida de archivos via modal + iframe (patron usado en BASE: P1/P2/P3).

    Flujo:
    - Click "Carregar fitxer"
    - Modal #fitxer visible con iframe #contingut_fitxer
    - input[type=file][name=qqfile] + boton #penjar_fitxers
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

        boton_abrir = page.get_by_role("button", name=re.compile(boton_abrir_regex, re.IGNORECASE)).first
        await boton_abrir.wait_for(state="visible", timeout=10000)
        await boton_abrir.click()
        await page.wait_for_timeout(DELAY_MS)

        modal = page.locator("#fitxer").first
        await modal.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(DELAY_MS)

        frame = page.frame_locator("#contingut_fitxer").first
        file_input = frame.locator("input[type='file'][name='qqfile']").first

        await file_input.wait_for(state="attached", timeout=20000)
        await page.wait_for_timeout(DELAY_MS)

        logging.info(f"Estableciendo archivo en el input: {archivo.name}")
        await file_input.set_input_files(str(archivo.resolve()))

        await page.wait_for_timeout(int(DELAY_MS * 1.5))

        boton_carregar = frame.locator("#penjar_fitxers").first
        if await boton_carregar.count() > 0:
            logging.info("Click en boton 'Penjar' / 'Carregar'...")
            await boton_carregar.click()
            await page.wait_for_timeout(DELAY_MS)

        logging.info("Esperando que aparezca el mensaje de exito (#textSuccess)...")
        success_text = frame.locator("#textSuccess").first

        try:
            await frame.locator("#textSuccess", has_text=archivo.name).wait_for(state="visible", timeout=30000)
        except Exception:
            logging.warning(
                "No se detecto el nombre '%s' en #textSuccess, esperando visibilidad generica.",
                archivo.name,
            )
            await success_text.wait_for(state="visible", timeout=15000)

        texto = (await success_text.inner_text()).strip()
        logging.info("Resultado subida: %s", texto)

        if archivo.name.lower() not in texto.lower():
            raise RuntimeError(f"Upload no confirmado para {archivo.name}. Se recibio: '{texto}'")

        await page.wait_for_timeout(DELAY_MS)
        logging.info("Click en 'Continuar' para cerrar el modal.")
        await frame.locator("#continuar").first.click()

        await page.wait_for_timeout(DELAY_MS)
        await modal.wait_for(state="hidden", timeout=15000)
        await page.wait_for_timeout(DELAY_MS)
