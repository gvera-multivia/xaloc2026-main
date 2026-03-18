from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from PIL import Image


def _is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except Exception:
        return False


def _is_convertible_image_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            header = fh.read(16)
    except Exception:
        return False
    return header.startswith(b"\xff\xd8\xff") or header.startswith(b"\x89PNG\r\n\x1a\n")


def _convert_image_to_pdf(src: Path, *, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{src.stem}.converted.pdf"
    with Image.open(src) as image:
        if image.mode in {"RGBA", "P"}:
            image = image.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.save(out_path, format="PDF", resolution=100.0)
    if not _is_pdf_file(out_path):
        raise RuntimeError(f"No se pudo convertir la imagen a PDF: {src}")
    return out_path


def _normalize_merge_inputs(files: list[Path], *, output_dir: Path) -> tuple[list[Path], list[str]]:
    normalized: list[Path] = []
    unsupported: list[str] = []
    converted_dir = output_dir / "_converted_inputs"
    for path in files:
        if _is_pdf_file(path):
            normalized.append(path)
            continue
        if _is_convertible_image_file(path):
            normalized.append(_convert_image_to_pdf(path, output_dir=converted_dir))
            continue
        unsupported.append(str(path))
    return normalized, unsupported


def _load_pdf_backend():
    """
    Retorna un backend de merge compatible con distintas versiones:
    - pypdf antiguos: PdfMerger
    - pypdf recientes: PdfWriter.append
    - fallback legacy: PyPDF2.PdfMerger
    """
    try:
        from pypdf import PdfMerger  # type: ignore

        return ("merger", PdfMerger)
    except Exception:
        pass

    try:
        from pypdf import PdfWriter  # type: ignore

        if hasattr(PdfWriter, "append"):
            return ("writer", PdfWriter)
    except Exception:
        pass

    try:
        from PyPDF2 import PdfMerger  # type: ignore

        return ("merger", PdfMerger)
    except Exception as e:
        raise RuntimeError(
            "No hay backend PDF disponible. Instala 'pypdf' (recomendado) o 'PyPDF2'."
        ) from e


def _load_pdf_reader():
    try:
        from pypdf import PdfReader  # type: ignore

        return PdfReader
    except Exception:
        pass

    try:
        from PyPDF2 import PdfReader  # type: ignore

        return PdfReader
    except Exception as e:
        raise RuntimeError(
            "No hay lector PDF disponible. Instala 'pypdf' (recomendado) o 'PyPDF2'."
        ) from e


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_pdf_page_count(path: Path) -> int:
    reader_cls = _load_pdf_reader()
    with path.open("rb") as fh:
        reader = reader_cls(fh)
        return int(len(reader.pages))


def _describe_pdf_inputs(files: list[Path]) -> list[dict[str, int | str]]:
    described: list[dict[str, int | str]] = []
    page_cursor = 1
    for pdf in files:
        page_count = _read_pdf_page_count(pdf)
        start_page = page_cursor
        end_page = page_cursor + page_count - 1
        described.append(
            {
                "path": str(pdf),
                "name": pdf.name,
                "size_bytes": int(pdf.stat().st_size),
                "sha256": _sha256_file(pdf),
                "page_count": page_count,
                "page_start": start_page,
                "page_end": end_page,
            }
        )
        page_cursor = end_page + 1
    return described


def _write_bundle_manifest(
    *,
    out_path: Path,
    source_info: list[dict[str, int | str]],
    output_page_count: int,
) -> Path:
    manifest_path = out_path.with_suffix(f"{out_path.suffix}.manifest.json")
    manifest = {
        "bundle_path": str(out_path),
        "bundle_name": out_path.name,
        "bundle_size_bytes": int(out_path.stat().st_size),
        "bundle_sha256": _sha256_file(out_path),
        "bundle_page_count": output_page_count,
        "source_count": len(source_info),
        "sources": source_info,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return manifest_path


def _verify_bundle_integrity(files: list[Path], out_path: Path) -> Path:
    if not out_path.exists() or not _is_pdf_file(out_path):
        raise RuntimeError(f"No se genero un PDF valido tras la fusion: {out_path}")

    source_info = _describe_pdf_inputs(files)
    expected_pages = sum(int(item["page_count"]) for item in source_info)
    output_pages = _read_pdf_page_count(out_path)
    if output_pages != expected_pages:
        raise RuntimeError(
            "Bundle PDF inconsistente: "
            f"esperadas={expected_pages} paginas, obtenidas={output_pages}, output={out_path}"
        )

    return _write_bundle_manifest(
        out_path=out_path,
        source_info=source_info,
        output_page_count=output_pages,
    )


def _bundle_with_pdftk(files: list[Path], out_path: Path) -> bool:
    pdftk = Path(r"C:\Program Files (x86)\PDFtk\bin\pdftk.exe")
    if not pdftk.exists():
        return False
    cmd = [str(pdftk), *[str(p) for p in files], "cat", "output", str(out_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception:
        return False
    return out_path.exists() and _is_pdf_file(out_path)


def bundle_documents_to_single_pdf_for_palma(
    files: list[Path],
    *,
    id_recurso: int | str | None,
    output_dir: Path = Path("tmp/ayunta_palma"),
    strict: bool = True,
) -> Path:
    """
    Fusiona todos los PDFs de entrada en un unico PDF.

    Nota: se mantiene el nombre historico de la funcion para compatibilidad,
    pero puede reutilizarse en otros sites.
    """
    normalized = [Path(p) for p in (files or []) if p]
    if not normalized:
        raise ValueError("No hay archivos para fusionar.")

    missing = [str(p) for p in normalized if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Archivos no encontrados para fusionar: {', '.join(missing)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    normalized, unsupported = _normalize_merge_inputs(normalized, output_dir=output_dir)
    if unsupported and strict:
        raise ValueError("Solo se pueden fusionar PDFs: " + ", ".join(unsupported))
    if not normalized:
        if unsupported:
            raise ValueError("No hay PDFs validos para fusionar. Ignorados: " + ", ".join(unsupported))
        raise ValueError("No hay archivos para fusionar.")

    if len(normalized) == 1:
        return normalized[0]

    rid = str(id_recurso or "unknown").strip()
    safe_rid = re.sub(r"[^A-Za-z0-9._-]+", "_", rid) or "unknown"
    out_path = output_dir / f"{safe_rid}_bundle.pdf"

    try:
        backend_kind, backend_cls = _load_pdf_backend()
        merger = backend_cls()
        try:
            for pdf in normalized:
                merger.append(str(pdf))
            with out_path.open("wb") as out_fh:
                merger.write(out_fh)
        finally:
            if backend_kind == "merger" and hasattr(merger, "close"):
                merger.close()
    except Exception:
        if not _bundle_with_pdftk(normalized, out_path):
            raise

    _verify_bundle_integrity(normalized, out_path)
    return out_path


def _merge_pdf_files(files: list[Path], out_path: Path) -> Path:
    backend_kind, backend_cls = _load_pdf_backend()
    merger = backend_cls()
    try:
        for pdf in files:
            merger.append(str(pdf))
        with out_path.open("wb") as out_fh:
            merger.write(out_fh)
    finally:
        if backend_kind == "merger" and hasattr(merger, "close"):
            merger.close()
    _verify_bundle_integrity(files, out_path)
    return out_path


def bundle_documents_with_size_limit(
    files: list[Path],
    *,
    id_recurso: int | str | None,
    output_dir: Path = Path("tmp/atc_registro_bundles"),
    max_bundle_size_bytes: int = 10 * 1024 * 1024,
) -> list[Path]:
    """
    Genera bundles PDF para reducir numero de adjuntos y mantener cada bundle por debajo de max_bundle_size_bytes.
    Solo fusiona PDFs; cualquier no-PDF se mantiene individual.
    """
    normalized = [Path(p) for p in (files or []) if p]
    if not normalized:
        return []

    existing: list[Path] = [p for p in normalized if p.exists()]
    pdfs = [p for p in existing if _is_pdf_file(p)]
    non_pdfs = [p for p in existing if p not in pdfs]

    if len(existing) <= 5:
        return existing

    output_dir.mkdir(parents=True, exist_ok=True)
    rid = str(id_recurso or "unknown").strip()
    safe_rid = re.sub(r"[^A-Za-z0-9._-]+", "_", rid) or "unknown"

    budget = max(256 * 1024, int(max_bundle_size_bytes * 0.93))
    bundles: list[list[Path]] = []
    current: list[Path] = []
    current_size = 0

    for pdf in pdfs:
        size = int(pdf.stat().st_size)
        if not current:
            current = [pdf]
            current_size = size
            continue
        if current_size + size <= budget:
            current.append(pdf)
            current_size += size
        else:
            bundles.append(current)
            current = [pdf]
            current_size = size
    if current:
        bundles.append(current)

    out_files: list[Path] = []
    for idx, group in enumerate(bundles, start=1):
        if len(group) == 1:
            out_files.append(group[0])
            continue
        out_path = output_dir / f"{safe_rid}_bundle_{idx}.pdf"
        try:
            out_files.append(_merge_pdf_files(group, out_path))
        except Exception:
            out_files.extend(group)

    out_files.extend(non_pdfs)
    return out_files
