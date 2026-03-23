from __future__ import annotations

from pathlib import Path

import core.redsara_registry_reference as registry_ref


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


def _make_fake_reader(*texts: str):
    class _Reader:
        def __init__(self, _fh) -> None:
            self.pages = [_FakePage(text) for text in texts]

    return _Reader


def test_parse_regage_from_pdf_prefers_label(monkeypatch, tmp_path: Path) -> None:
    pdf = tmp_path / "receipt.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        registry_ref,
        "_load_pdf_reader",
        lambda: _make_fake_reader("Numero de registro: REGAGE26e00029762263"),
    )

    parsed = registry_ref.parse_regage_from_receipt_pdf(pdf)

    assert parsed == "REGAGE26E00029762263"


def test_parse_regage_from_pdf_uses_global_regex_fallback(monkeypatch, tmp_path: Path) -> None:
    pdf = tmp_path / "receipt.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        registry_ref,
        "_load_pdf_reader",
        lambda: _make_fake_reader("Texto OCR R E G A G E 2 6 e 0 0 0 2 9 7 6 2 2 6 3"),
    )

    parsed = registry_ref.parse_regage_from_receipt_pdf(pdf)

    assert parsed == "REGAGE26E00029762263"


def test_persist_receipt_dedupe_returns_existing_when_hash_matches(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    src.write_bytes(b"same-bytes")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = dest_dir / "JUSTIFICANTE.pdf"
    existing.write_bytes(b"same-bytes")

    saved = registry_ref.persist_redsara_receipt_with_dedupe(
        source_path=src,
        destination_dir=dest_dir,
        filename="JUSTIFICANTE.pdf",
    )

    assert saved == existing
    assert len(list(dest_dir.glob("JUSTIFICANTE*.pdf"))) == 1


def test_persist_receipt_dedupe_creates_retry_when_hash_differs(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    src.write_bytes(b"new-bytes")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = dest_dir / "JUSTIFICANTE.pdf"
    existing.write_bytes(b"old-bytes")

    saved = registry_ref.persist_redsara_receipt_with_dedupe(
        source_path=src,
        destination_dir=dest_dir,
        filename="JUSTIFICANTE.pdf",
    )

    assert saved is not None
    assert saved != existing
    assert saved.name.startswith("JUSTIFICANTE (REINTENTO")
