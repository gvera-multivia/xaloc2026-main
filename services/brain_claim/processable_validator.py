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


def _canonical_get(candidate: dict[str, Any], path: str) -> Any:
    node: Any = candidate.get("__canonical_v1") if isinstance(candidate, dict) else None
    if not isinstance(node, dict):
        return None
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _pick(candidate: dict[str, Any], *keys: str, canonical_path: str | None = None) -> Any:
    for key in keys:
        value = candidate.get(key)
        if value not in (None, "", []):
            return value
    if canonical_path:
        value = _canonical_get(candidate, canonical_path)
        if value not in (None, "", []):
            return value
    return None


def validate_candidate(
    *,
    site_id: str,
    candidate: dict[str, Any],
    runtime_store: Any,
    admin_store: Any,
    is_blocked: bool | None = None,
    is_resource_paused: bool | None = None,
) -> ValidationResult:
    rid_raw = _pick(candidate, "idRecurso", canonical_path="resource.id")
    try:
        rid = int(rid_raw)
    except Exception:
        return ValidationResult(False, "RESOURCE_INVALID", "Recurso sin idRecurso valido.")

    site = _clean_str(site_id)
    expediente = _clean_str(_pick(candidate, "Expedient", "expediente", canonical_path="resource.expedient"))
    if not expediente:
        return ValidationResult(False, "REF_MISSING", "Falta referencia/expediente.")

    if is_blocked is None:
        try:
            is_blocked = bool(admin_store.is_resource_blocked(site_id=site, resource_id=rid))
        except Exception:
            is_blocked = False
    if is_blocked:
        return ValidationResult(False, "RESOURCE_BLOCKED", "Recurso bloqueado por blacklist.")

    if is_resource_paused is None:
        try:
            is_resource_paused = bool(runtime_store.is_resource_processing_paused(site_id=site, resource_id=rid))
        except Exception:
            is_resource_paused = False
    if is_resource_paused:
        return ValidationResult(False, "RESOURCE_PAUSED", "Recurso pausado temporalmente.")

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
            return ValidationResult(False, "DEADLINE_EXPIRED", "Fecha limite vencida.")

    if site == "madrid":
        direccion = _clean_str(_pick(candidate, "cliente_domicilio", canonical_path="client.address.street_name"))
        if not direccion:
            return ValidationResult(False, "ADDR_MISSING", "Falta direccion para Madrid.")
        doc = (
            _clean_str(_pick(candidate, "cliente_nif", canonical_path="client.document.nif"))
            or _clean_str(_pick(candidate, "cliente_nif_empresa", "cif", canonical_path="client.document.cif"))
        )
        if not doc:
            return ValidationResult(False, "DOC_MISSING", "Falta NIF/NIE/CIF para Madrid.")

    if site == "base_online":
        protocolo = _infer_protocol_for_base(
            _clean_str(_pick(candidate, "FaseProcedimiento", "fase_procedimiento", canonical_path="resource.phase"))
        )
        if protocolo == "P1":
            if not _clean_str(_pick(candidate, "conduc_adr", canonical_path="client.address.street_name")):
                return ValidationResult(False, "ADDR_MISSING", "P1 sin direccion de conductor.")
            if not _clean_str(_pick(candidate, "conduc_dni", canonical_path="client.document.nif")):
                return ValidationResult(False, "DOC_MISSING", "P1 sin documento del conductor.")
            if not _clean_str(_pick(candidate, "conduc_nom", "SujetoRecurso", canonical_path="resource.subject_name")):
                return ValidationResult(False, "DOC_MISSING", "P1 sin nombre del conductor.")

    return ValidationResult(True, None, None)
