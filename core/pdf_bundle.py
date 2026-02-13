from __future__ import annotations

from pathlib import Path

from pypdf import PdfMerger


def _is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except Exception:
        return False


def bundle_documents_to_single_pdf_for_palma(
    files: list[Path],
    *,
    id_recurso: int | str | None,
    output_dir: Path = Path("tmp/ayunta_palma"),
) -> Path:
    """
    Fusiona todos los PDFs de entrada en un único PDF listo para subir a Palma.
    """
    normalized = [Path(p) for p in (files or []) if p]
    if not normalized:
        raise ValueError("No hay archivos para fusionar en ayunta_palma.")

    missing = [str(p) for p in normalized if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Archivos no encontrados para ayunta_palma: {', '.join(missing)}")

    non_pdf = [str(p) for p in normalized if not _is_pdf_file(p)]
    if non_pdf:
        raise ValueError(
            "ayunta_palma solo admite un PDF final y se detectaron adjuntos no PDF: "
            + ", ".join(non_pdf)
        )

    if len(normalized) == 1:
        return normalized[0]

    merger = PdfMerger()
    try:
        for pdf in normalized:
            merger.append(str(pdf))

        output_dir.mkdir(parents=True, exist_ok=True)
        rid = str(id_recurso or "unknown").strip()
        out_path = output_dir / f"ayunta_palma_{rid}_bundle.pdf"
        with out_path.open("wb") as out_fh:
            merger.write(out_fh)
    finally:
        merger.close()

    if not out_path.exists() or not _is_pdf_file(out_path):
        raise RuntimeError(f"No se generó un PDF válido tras la fusión: {out_path}")

    return out_path
