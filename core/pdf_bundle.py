from __future__ import annotations

import subprocess
import re
from pathlib import Path


def _is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except Exception:
        return False


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
) -> Path:
    """
    Fusiona todos los PDFs de entrada en un único PDF.

    Nota: se mantiene el nombre histórico de la función para compatibilidad,
    pero puede reutilizarse en otros sites.
    """
    normalized = [Path(p) for p in (files or []) if p]
    if not normalized:
        raise ValueError("No hay archivos para fusionar.")

    missing = [str(p) for p in normalized if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Archivos no encontrados para fusionar: {', '.join(missing)}")

    non_pdf = [str(p) for p in normalized if not _is_pdf_file(p)]
    if non_pdf:
        raise ValueError("Solo se pueden fusionar PDFs: " + ", ".join(non_pdf))

    if len(normalized) == 1:
        return normalized[0]

    output_dir.mkdir(parents=True, exist_ok=True)
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

    if not out_path.exists() or not _is_pdf_file(out_path):
        raise RuntimeError(f"No se generó un PDF válido tras la fusión: {out_path}")

    return out_path
