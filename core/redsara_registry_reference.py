from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from core.client_documentation import client_identity_from_payload
from core.client_paths import get_ruta_recursos_telematicos, resolve_client_docs_base_path
from core.justificantes_storage import sanitize_filename_component

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_REGAGE_GLOBAL_RE = re.compile(
    r"R\s*E\s*G\s*A\s*G\s*E(?:[\s\-\u2010-\u2015\u00ad\u200b-\u200f\u2060\ufeff]*[0-9A-Za-z]){6,}",
    re.IGNORECASE,
)
_REGAGE_LABEL_RE = re.compile(
    r"n[úu]mero\s+de\s+registro\s*:\s*([^\n\r]+)",
    re.IGNORECASE,
)


def _load_pdf_reader():
    try:
        from pypdf import PdfReader  # type: ignore

        return PdfReader
    except Exception:
        from PyPDF2 import PdfReader  # type: ignore

        return PdfReader


def _normalize_text(raw: str) -> str:
    text = str(raw or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("\u00ad", "")
    text = _ZERO_WIDTH_RE.sub("", text)
    return text


def _normalize_registry_candidate(raw: str) -> str | None:
    compact = _normalize_text(raw).upper()
    compact = re.sub(r"[^A-Z0-9]", "", compact)
    if not compact.startswith("REGAGE"):
        return None
    if len(compact) < 12:
        return None
    return compact


def _extract_regage_from_text(text: str) -> str | None:
    normalized = _normalize_text(text)
    by_label = _REGAGE_LABEL_RE.search(normalized)
    if by_label:
        candidate = _normalize_registry_candidate(by_label.group(1))
        if candidate:
            return candidate

    for match in _REGAGE_GLOBAL_RE.finditer(normalized):
        candidate = _normalize_registry_candidate(match.group(0))
        if candidate:
            return candidate
    return None


def parse_regage_from_receipt_pdf(path: str | Path) -> str | None:
    pdf_path = Path(path)
    if not pdf_path.exists() or not pdf_path.is_file():
        return None

    reader_cls = _load_pdf_reader()
    try:
        with pdf_path.open("rb") as fh:
            reader = reader_cls(fh)
            chunks: list[str] = []
            for page in getattr(reader, "pages", []):
                try:
                    chunks.append(str(page.extract_text() or ""))
                except Exception:
                    continue
    except Exception:
        return None

    return _extract_regage_from_text("\n".join(chunks))


def build_followup_reference(*, previous_registry_number: str | None, expediente: str) -> tuple[str, str]:
    reg = str(previous_registry_number or "").strip()
    if reg:
        return f"registro previo con numero {reg}", "regage"
    exp = sanitize_filename_component(expediente or "UNKNOWN")
    return f"expediente {exp}", "expediente_fallback"


def build_redsara_receipt_filename(
    *,
    expediente: str,
    reg_ref: str,
    batch_index: int,
    total_batches: int,
) -> str:
    exp = sanitize_filename_component(expediente or "UNKNOWN")
    reg = sanitize_filename_component(reg_ref or f"SIN-REG-{exp}")
    return f"JUSTIFICANTE - {exp} - {reg} - PARTE {int(batch_index)} de {int(total_batches)}.pdf"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_non_overwrite_retry(path: Path) -> Path:
    if not path.exists():
        return path
    idx = 2
    while True:
        candidate = path.with_name(f"{path.stem} (REINTENTO {idx}){path.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def resolve_redsara_receipt_dir(payload: dict) -> Path | None:
    if not payload:
        return None
    try:
        client = client_identity_from_payload(payload)
        return get_ruta_recursos_telematicos(
            client=client,
            base_path=resolve_client_docs_base_path(),
            fase_procedimiento=payload.get("FaseProcedimiento") or payload.get("fase_procedimiento"),
        )
    except Exception:
        return None


def persist_redsara_receipt_with_dedupe(
    *,
    source_path: str | Path,
    destination_dir: Path,
    filename: str,
) -> Path | None:
    src = Path(source_path)
    if not src.exists() or not src.is_file():
        return None

    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / filename
    if target.exists():
        try:
            if _file_sha256(src) == _file_sha256(target):
                return target
        except Exception:
            pass
        target = _resolve_non_overwrite_retry(target)

    shutil.copy2(src, target)
    return target
