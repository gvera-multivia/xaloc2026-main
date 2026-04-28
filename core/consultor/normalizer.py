from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from core.address_defaults import get_default_country_es_ascii
from core.validation.validators import normalize_plate_with_fallback
from .contracts import CanonicalResourceV1


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _normalize_plate_candidate(value: Any) -> str:
    raw = _clean(value)
    if not raw or raw in {".", "-", "N/A", "NA", "NULL", "NONE"}:
        return ""
    normalized = normalize_plate_with_fallback(raw)
    return "" if normalized == "." else normalized


def _resolve_vehicle_plate(raw: dict[str, Any]) -> tuple[str, str]:
    for key in ("rs_matricula", "exp_matricula", "pub_matricula", "matricula", "Matricula"):
        normalized = _normalize_plate_candidate(raw.get(key))
        if normalized:
            return normalized, key

    pub_text = _clean(raw.get("pub_publicacion")).upper()
    if pub_text:
        match = re.search(r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4,6}(?:[\s-]*[A-Z]{1,3})?)\b", pub_text)
        if match:
            normalized = _normalize_plate_candidate(match.group(1))
            if normalized:
                return normalized, "pub_publicacion"

    return ".", "none"


def normalize_resource_row(*, site_id: str, row: dict[str, Any]) -> CanonicalResourceV1:
    raw = dict(row or {})

    resource = {
        "id": raw.get("idRecurso"),
        "exp_id": raw.get("idExp"),
        "expedient": _clean(raw.get("Expedient")),
        "procedure": _clean(raw.get("Procedim")),
        "publication_csv": _first_non_empty(raw.get("ExpedientePublicacion"), raw.get("pub_publicacion")),
        "organism": _clean(raw.get("Organisme")),
        "texp": raw.get("TExp"),
        "state": raw.get("Estado"),
        "assigned_user": _clean(raw.get("UsuarioAsignado")),
        "completed_at": raw.get("FUsuarioCompletado"),
        "phase": _clean(raw.get("FaseProcedimiento")),
        "numclient": raw.get("numclient"),
        "subject_name": _clean(raw.get("SujetoRecurso")),
    }

    client = {
        "type": raw.get("cliente_tipo"),
        "document": {
            "primary": _first_non_empty(raw.get("cif"), raw.get("cliente_nif_empresa"), raw.get("cliente_nif")),
            "nif": _clean(raw.get("cliente_nif")),
            "cif": _first_non_empty(raw.get("cif"), raw.get("cliente_nif_empresa")),
        },
        "name": {
            "first": _clean(raw.get("cliente_nombre")),
            "last1": _clean(raw.get("cliente_apellido1")),
            "last2": _clean(raw.get("cliente_apellido2")),
            "business": _first_non_empty(raw.get("cliente_razon_social"), raw.get("Nombrefiscal"), raw.get("Empresa")),
        },
        "contact": {
            "email": _clean(raw.get("cliente_email")),
            "phone1": _clean(raw.get("cliente_tel1")),
            "phone2": _clean(raw.get("cliente_tel2")),
            "mobile": _clean(raw.get("cliente_movil")),
        },
        "address": {
            "street_type": _clean(raw.get("address_sigla")),
            "street_name": _first_non_empty(raw.get("cliente_domicilio"), raw.get("conduc_adr")),
            "number": _clean(raw.get("cliente_numero")),
            "stair": _clean(raw.get("cliente_escalera")),
            "floor": _clean(raw.get("cliente_planta")),
            "door": _clean(raw.get("cliente_puerta")),
            "zip": _first_non_empty(raw.get("cliente_cp"), raw.get("conduc_codpost")),
            "city": _first_non_empty(raw.get("cliente_municipio"), raw.get("conduc_pobl")),
            "province": _first_non_empty(raw.get("cliente_provincia"), raw.get("conduc_prov")),
            "country": get_default_country_es_ascii(),
        },
    }

    normalized_plate, plate_source = _resolve_vehicle_plate(raw)

    vehicle = {
        "plate": {"value": normalized_plate, "source": plate_source},
        "incident_date": _first_non_empty(raw.get("dia_denuncia"), raw.get("FAlta")),
        "publication_text": _clean(raw.get("pub_publicacion")),
    }

    attachments = list(raw.get("adjuntos") or [])
    if not attachments:
        adj_id = raw.get("adjunto_id")
        if adj_id:
            filename = _clean(raw.get("adjunto_filename"))
            if filename:
                attachments = [{"id": int(adj_id), "filename": filename}]

    meta = {
        "schema_version": "v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "site_id": site_id,
    }

    return CanonicalResourceV1(
        site_id=site_id,
        resource=resource,
        client=client,
        vehicle=vehicle,
        attachments=attachments,
        meta=meta,
    )
