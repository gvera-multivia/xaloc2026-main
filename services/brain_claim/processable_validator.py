from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class ValidationResult:
    processable: bool
    error_code: str | None = None
    description: str | None = None


def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_text(value: Any) -> str:
    import unicodedata

    text = _clean_str(value).lower()
    if not text:
        return ""
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def _infer_protocol_for_base(fase: str) -> str:
    f = _normalize_text(fase)
    if "identificacion" in f:
        return "P1"
    if any(tag in f for tag in ("denuncia", "propuesta", "subsanacion", "alegacion", "alegaciones")):
        return "P2"
    return "P3"


def _parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = _clean_str(value)
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def validate_candidate(
    *,
    site_id: str,
    candidate: dict[str, Any],
    runtime_store: Any,
    admin_store: Any,
) -> ValidationResult:
    rid_raw = candidate.get("idRecurso")
    try:
        rid = int(rid_raw)
    except Exception:
        return ValidationResult(False, "RESOURCE_INVALID", "Recurso sin idRecurso válido.")

    site = _clean_str(site_id)
    expediente = _clean_str(candidate.get("Expedient"))
    if not expediente:
        return ValidationResult(False, "REF_MISSING", "Falta referencia/expediente.")

    try:
        if admin_store.is_resource_blocked(site_id=site, resource_id=rid):
            return ValidationResult(False, "RESOURCE_BLOCKED", "Recurso bloqueado por blacklist.")
    except Exception:
        pass

    try:
        if runtime_store.is_resource_processing_paused(site_id=site, resource_id=rid):
            return ValidationResult(False, "RESOURCE_PAUSED", "Recurso pausado temporalmente.")
    except Exception:
        pass

    # Deadline guard: only if known date fields exist.
    deadline_fields = (
        "fecha_limite",
        "FechaLimite",
        "FPlazo",
        "fecha_vencimiento",
        "vencimiento",
    )
    deadline = None
    for field in deadline_fields:
        parsed = _parse_date(candidate.get(field))
        if parsed is not None:
            deadline = parsed
            break
    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline < datetime.now(timezone.utc):
            return ValidationResult(False, "DEADLINE_EXPIRED", "Fecha límite vencida.")

    if site == "madrid":
        direccion = _clean_str(candidate.get("cliente_domicilio"))
        if not direccion:
            return ValidationResult(False, "ADDR_MISSING", "Falta dirección para Madrid.")
        doc = (
            _clean_str(candidate.get("cliente_nif"))
            or _clean_str(candidate.get("cliente_nif_empresa"))
            or _clean_str(candidate.get("cif"))
        )
        if not doc:
            return ValidationResult(False, "DOC_MISSING", "Falta NIF/NIE/CIF para Madrid.")

    if site == "base_online":
        protocolo = _infer_protocol_for_base(_clean_str(candidate.get("FaseProcedimiento")))
        if protocolo == "P1":
            if not _clean_str(candidate.get("conduc_adr")):
                return ValidationResult(False, "ADDR_MISSING", "P1 sin dirección de conductor.")
            if not _clean_str(candidate.get("conduc_dni")):
                return ValidationResult(False, "DOC_MISSING", "P1 sin documento del conductor.")
            if not _clean_str(candidate.get("conduc_nom")):
                return ValidationResult(False, "DOC_MISSING", "P1 sin nombre del conductor.")

    return ValidationResult(True, None, None)
