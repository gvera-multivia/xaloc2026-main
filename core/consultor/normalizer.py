from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.address_defaults import get_default_country_es_ascii
from .contracts import CanonicalResourceV1


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def normalize_resource_row(*, site_id: str, row: dict[str, Any]) -> CanonicalResourceV1:
    raw = dict(row or {})

    resource = {
        "id": raw.get("idRecurso"),
        "exp_id": raw.get("idExp"),
        "expedient": _clean(raw.get("Expedient")),
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

    vehicle_plate = _first_non_empty(
        raw.get("rs_matricula"),
        raw.get("exp_matricula"),
        raw.get("pub_matricula"),
        raw.get("matricula"),
    )
    if _clean(raw.get("rs_matricula")):
        plate_source = "rs_matricula"
    elif _clean(raw.get("exp_matricula")):
        plate_source = "exp_matricula"
    elif _clean(raw.get("pub_matricula")):
        plate_source = "pub_matricula"
    elif _clean(raw.get("matricula")):
        plate_source = "matricula"
    else:
        plate_source = "none"

    vehicle = {
        "plate": {"value": vehicle_plate, "source": plate_source},
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
