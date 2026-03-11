from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from core.client_documentation import client_identity_from_payload
from core.client_paths import (
    ClientIdentity,
    get_ruta_recursos_telematicos,
    resolve_client_docs_base_path,
)

logger = logging.getLogger(__name__)


def sanitize_filename_component(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r'[<>:"|?*\x00-\x1F]', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(". ")
    return text or "UNKNOWN"


def build_receipt_filename(*, expediente: str, template: str = "JUSTIFICANTE - {expediente}.pdf") -> str:
    safe_expediente = sanitize_filename_component(expediente)
    return template.format(expediente=safe_expediente)


def build_non_overwrite_path(destino_dir: Path, filename: str) -> Path:
    base = Path(filename).stem
    ext = Path(filename).suffix or ".pdf"
    candidate = destino_dir / f"{base}{ext}"
    if not candidate.exists():
        return candidate

    ts = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
    candidate = destino_dir / f"{base} ({ts}){ext}"
    seq = 1
    while candidate.exists():
        seq += 1
        candidate = destino_dir / f"{base} ({ts})_{seq}{ext}"
    return candidate


def resolve_receipt_dir_for_client(
    *,
    client: ClientIdentity,
    fase_procedimiento: str | None = None,
    base_path: str | Path | None = None,
) -> Path:
    resolved_base_path = base_path or resolve_client_docs_base_path()
    return get_ruta_recursos_telematicos(
        client=client,
        base_path=resolved_base_path,
        fase_procedimiento=fase_procedimiento,
    )


def resolve_receipt_dir_from_payload(
    *,
    payload: dict,
    fase_procedimiento: str | None = None,
    base_path: str | Path | None = None,
) -> Path:
    client = client_identity_from_payload(payload)
    fase = fase_procedimiento
    if fase is None:
        fase = str(payload.get("fase_procedimiento") or payload.get("FaseProcedimiento") or "").strip() or None
    return resolve_receipt_dir_for_client(
        client=client,
        fase_procedimiento=fase,
        base_path=base_path,
    )


def save_receipt_from_tmp(
    *,
    tmp_path: Path,
    destino_dir: Path,
    filename: str,
) -> Path:
    destino_dir.mkdir(parents=True, exist_ok=True)
    final_path = build_non_overwrite_path(destino_dir, filename)
    shutil.copy2(tmp_path, final_path)
    tmp_path.unlink(missing_ok=True)
    logger.info("Justificante guardado en: %s", final_path)
    return final_path

