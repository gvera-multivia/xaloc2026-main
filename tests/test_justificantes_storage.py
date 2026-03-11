from __future__ import annotations

from pathlib import Path

from core.justificantes_storage import (
    build_non_overwrite_path,
    build_receipt_filename,
    sanitize_filename_component,
    save_receipt_from_tmp,
)


def test_sanitize_filename_component_strips_invalid_chars() -> None:
    value = r'  2026/1234\ABC:*?"<>|  '
    assert sanitize_filename_component(value) == "2026-1234-ABC_______"


def test_build_receipt_filename_uses_template() -> None:
    filename = build_receipt_filename(
        expediente="2026/1234-MUL",
        template="JUSTIFICANTE {expediente}.pdf",
    )
    assert filename == "JUSTIFICANTE 2026-1234-MUL.pdf"


def test_build_non_overwrite_path_returns_new_name_when_exists(tmp_path: Path) -> None:
    destino_dir = tmp_path / "dest"
    destino_dir.mkdir(parents=True, exist_ok=True)
    first = destino_dir / "JUSTIFICANTE 2026-1.pdf"
    first.write_bytes(b"x")

    second = build_non_overwrite_path(destino_dir, first.name)
    assert second != first
    assert second.parent == destino_dir
    assert second.suffix == ".pdf"


def test_save_receipt_from_tmp_copies_and_removes_tmp(tmp_path: Path) -> None:
    tmp_pdf = tmp_path / "tmp.pdf"
    tmp_pdf.write_bytes(b"%PDF-1.7 test")
    destino_dir = tmp_path / "cliente" / "RECURSOS TELEMATICOS"

    saved = save_receipt_from_tmp(
        tmp_path=tmp_pdf,
        destino_dir=destino_dir,
        filename="JUSTIFICANTE - 2026-1.pdf",
    )

    assert saved.exists()
    assert saved.read_bytes() == b"%PDF-1.7 test"
    assert not tmp_pdf.exists()
