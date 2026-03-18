from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from core import pdf_bundle


def _load_pdf_writer():
    try:
        from pypdf import PdfWriter  # type: ignore

        return PdfWriter
    except Exception:
        from PyPDF2 import PdfWriter  # type: ignore

        return PdfWriter


def _make_pdf(path: Path, *, pages: int) -> Path:
    writer_cls = _load_pdf_writer()
    writer = writer_cls()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_bundle_documents_to_single_pdf_writes_manifest_and_page_ranges(tmp_path: Path) -> None:
    first = _make_pdf(tmp_path / "recurso.pdf", pages=2)
    second = _make_pdf(tmp_path / "autorizacion.pdf", pages=1)

    out = pdf_bundle.bundle_documents_to_single_pdf_for_palma(
        [first, second],
        id_recurso=123,
        output_dir=tmp_path / "out",
    )

    manifest_path = out.with_suffix(f"{out.suffix}.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert out.exists()
    assert manifest["bundle_page_count"] == 3
    assert manifest["source_count"] == 2
    assert [item["name"] for item in manifest["sources"]] == ["recurso.pdf", "autorizacion.pdf"]
    assert [(item["page_start"], item["page_end"]) for item in manifest["sources"]] == [(1, 2), (3, 3)]


def test_bundle_documents_with_size_limit_writes_manifest_for_merged_output(tmp_path: Path) -> None:
    files = [_make_pdf(tmp_path / f"doc_{idx}.pdf", pages=1) for idx in range(6)]

    out_files = pdf_bundle.bundle_documents_with_size_limit(
        files,
        id_recurso=456,
        output_dir=tmp_path / "bundles",
        max_bundle_size_bytes=5 * 1024 * 1024,
    )

    bundle_files = [path for path in out_files if path.name.endswith(".pdf") and "_bundle_" in path.name]
    assert len(bundle_files) == 1

    manifest_path = bundle_files[0].with_suffix(f"{bundle_files[0].suffix}.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["bundle_page_count"] == 6
    assert manifest["source_count"] == 6


def test_bundle_documents_to_single_pdf_raises_when_output_page_count_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _BrokenMerger:
        def append(self, _path: str) -> None:
            return None

        def write(self, fh) -> None:
            writer_cls = _load_pdf_writer()
            writer = writer_cls()
            writer.add_blank_page(width=72, height=72)
            writer.write(fh)

        def close(self) -> None:
            return None

    first = _make_pdf(tmp_path / "one.pdf", pages=1)
    second = _make_pdf(tmp_path / "two.pdf", pages=1)

    monkeypatch.setattr(pdf_bundle, "_load_pdf_backend", lambda: ("merger", _BrokenMerger))
    monkeypatch.setattr(pdf_bundle, "_bundle_with_pdftk", lambda files, out_path: False)

    with pytest.raises(RuntimeError, match="Bundle PDF inconsistente"):
        pdf_bundle.bundle_documents_to_single_pdf_for_palma(
            [first, second],
            id_recurso=789,
            output_dir=tmp_path / "broken",
        )


def test_bundle_documents_to_single_pdf_converts_supported_images_before_merge(tmp_path: Path) -> None:
    pdf_path = _make_pdf(tmp_path / "recurso.pdf", pages=1)
    image_path = tmp_path / "dni.png"
    Image.new("RGB", (24, 24), color="white").save(image_path, format="PNG")

    out = pdf_bundle.bundle_documents_to_single_pdf_for_palma(
        [pdf_path, image_path],
        id_recurso=321,
        output_dir=tmp_path / "out",
    )

    manifest_path = out.with_suffix(f"{out.suffix}.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert out.exists()
    assert manifest["bundle_page_count"] == 2
    assert manifest["source_count"] == 2


def test_bundle_documents_to_single_pdf_non_strict_ignores_invalid_fake_pdf(tmp_path: Path) -> None:
    valid_pdf = _make_pdf(tmp_path / "recurso.pdf", pages=1)
    fake_pdf = tmp_path / "Escritura EMPRESA.pdf"
    fake_pdf.write_bytes(b"rtfd\x00\x00\x00\x00")

    out = pdf_bundle.bundle_documents_to_single_pdf_for_palma(
        [valid_pdf, fake_pdf],
        id_recurso=654,
        output_dir=tmp_path / "out",
        strict=False,
    )

    assert out.exists()
    assert out.name == "recurso.pdf"
