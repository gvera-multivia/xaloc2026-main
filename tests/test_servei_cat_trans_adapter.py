from __future__ import annotations

import os
import sys
import asyncio
from dataclasses import dataclass

sys.path.append(os.getcwd())

from sites.adapters.servei_cat_trans import ServeiCatTransAdapter


@dataclass
class _FakeResource:
    metadata: dict


class _FakeRepo:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int):
        del site_id, config, limit
        return [_FakeResource(metadata=row) for row in self._rows]


def _base_row() -> dict:
    return {
        "idRecurso": 1,
        "idExp": 10,
        "numclient": 100,
        "Expedient": "17/20328298-3",
        "Organisme": "SERVEI CATALA DE TRANSIT DE BARCELONA",
        "TExp": 2,
        "Estado": 0,
        "UsuarioAsignado": None,
        "FaseProcedimiento": "denuncia",
        "Procedim": "RECURSO DE REPOSICION",
        "SujetoRecurso": "TEST",
        "cliente_tipo": 1,
        "cliente_nif": "12345678Z",
        "cliente_nombre": "NOMBRE",
        "cliente_apellido1": "AP1",
        "cliente_apellido2": "AP2",
        "cl_calle": "Ronda General Mitre",
        "cl_numero": "169",
        "cl_cp": "08022",
        "cl_poblacion": "Barcelona",
        "cl_provincia": "Barcelona",
        "adjuntos": [],
    }


def test_fetch_candidates_accepts_valid_formats_slash_and_dash() -> None:
    adapter = ServeiCatTransAdapter()
    rows = [_base_row(), {**_base_row(), "idRecurso": 2, "Expedient": "17-20328298-3"}]
    repo = _FakeRepo(rows)
    out = adapter.fetch_candidates(
        config={"query_organisme": "%SERVEI CATALA DE TRANSIT DE%", "filtro_texp": "2,3", "regex_expediente": r"^\d{2}[-/]\d{8}-\d$"},
        conn_str="dummy",
        authenticated_user="user",
        limit=50,
        resource_repo=repo,
    )
    assert len(out) == 2


def test_fetch_candidates_discards_non_target_organisme() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["Organisme"] = "AJUNTAMENT DE BARCELONA"
    repo = _FakeRepo([row])
    out = adapter.fetch_candidates(
        config={"query_organisme": "%SERVEI CATALA DE TRANSIT DE%", "filtro_texp": "2,3", "regex_expediente": r"^\d{2}[-/]\d{8}-\d$"},
        conn_str="dummy",
        authenticated_user="user",
        limit=50,
        resource_repo=repo,
    )
    assert out == []


def test_fetch_candidates_normalizes_compact_expediente_shape() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["Expedient"] = "17203282983"
    repo = _FakeRepo([row])
    out = adapter.fetch_candidates(
        config={"query_organisme": "%SERVEI CATALA DE TRANSIT DE%", "filtro_texp": "2,3", "regex_expediente": r"^\d{2}[-/]\d{8}-\d$"},
        conn_str="dummy",
        authenticated_user="user",
        limit=50,
        resource_repo=repo,
    )
    assert len(out) == 1
    assert out[0]["Expedient"] == "17/20328298-3"


def test_fetch_candidates_accepts_identificacion_phase() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["FaseProcedimiento"] = "Identificació del conductor"
    repo = _FakeRepo([row])
    out = adapter.fetch_candidates(
        config={"query_organisme": "%SERVEI CATALA DE TRANSIT DE%", "filtro_texp": "2,3", "regex_expediente": r"^\d{2}[-/]\d{8}-\d$"},
        conn_str="dummy",
        authenticated_user="user",
        limit=50,
        resource_repo=repo,
    )
    assert len(out) == 1


def test_build_payloads_maps_expected_core_fields() -> None:
    adapter = ServeiCatTransAdapter()
    payloads = asyncio.run(adapter.build_payloads([_base_row()]))
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["expediente"] == "17/20328298-3"
    assert payload["procedim"] == "RECURSO DE REPOSICION"
    assert payload["fase_procedimiento"] == "denuncia"
    assert payload["tipodecliente"] == "1"
    assert payload["representado_calle_raw"] == "Ronda General Mitre"
    assert payload["representado_numero_raw"] == "169"
    assert payload["expongo"] != ""
    assert payload["solicito"] != ""


def test_build_payloads_representado_fallbacks_when_cl_fields_missing() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["cl_calle"] = ""
    row["cl_numero"] = ""
    row["cl_cp"] = ""
    row["cl_poblacion"] = ""
    row["cl_provincia"] = ""
    row["cliente_domicilio"] = "Av Diagonal"
    row["cliente_numero"] = "10"
    row["cliente_cp"] = "08019"
    row["cliente_municipio"] = "Barcelona"
    row["cliente_provincia"] = "Barcelona"
    payloads = asyncio.run(adapter.build_payloads([row]))

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["representado_calle_raw"] == "Av Diagonal"
    assert payload["representado_cp"] == "08019"
    assert payload["representado_poblacion"] == "Barcelona"


def test_build_payloads_identificacion_sets_tramite_and_identificado_fields() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["FaseProcedimiento"] = "IdentificaciÃ³ del conductor"
    row["ConducNom"] = "PEP"
    row["ConducApellido1"] = "PROVES"
    row["ConducDni"] = "12345678Z"
    row["ConducAdr"] = "Carrer Major"
    row["ConducNumero"] = "12"
    row["ConducCodpost"] = "08001"
    row["ConducPobl"] = "Barcelona"
    row["ConducProv"] = "Barcelona"

    payloads = asyncio.run(adapter.build_payloads([row]))

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["tramite_tipo"] == "identificacion"
    assert payload["identificado_tipo_persona"] == "fisica"
    assert payload["identificado_nombre"] == "PEP"
    assert payload["identificado_nif"] == "12345678Z"
    assert payload["identificado_calle_raw"] == "Carrer Major"
    assert payload["identificado_numero_raw"] == "12"


def test_build_payloads_identificacion_passport_sets_pais_emisor() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["FaseProcedimiento"] = "IdentificaciÃƒÂ³ del conductor"
    row["ConducNom"] = "MOHAMED"
    row["ConducApellido1"] = "AIT"
    row["ConducDni"] = "G1234567"
    row["ConducPais"] = "Marruecos"

    payloads = asyncio.run(adapter.build_payloads([row]))

    assert len(payloads) == 1
    assert payloads[0]["identificado_nif"] == "G1234567"
    assert payloads[0]["identificado_pais_emisor"] == "Marruecos"


def test_build_payloads_identificacion_passport_requires_pais_emisor() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["FaseProcedimiento"] = "IdentificaciÃƒÂ³ del conductor"
    row["ConducNom"] = "MOHAMED"
    row["ConducApellido1"] = "AIT"
    row["ConducDni"] = "G1234567"
    row["ConducPais"] = ""
    discards: list[dict] = []

    payloads = asyncio.run(adapter.build_payloads([row], on_discard=discards.append))

    assert payloads == []
    assert any(
        d.get("tipo_incidencia") == "SITE_RULE_DISCARDED"
        and "pasaporte/documento extranjero sin ConducPais" in str(d.get("motivo"))
        for d in discards
    )


def test_build_payloads_identificacion_splits_last_token_into_apellido1_when_missing() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["FaseProcedimiento"] = "IdentificaciÃƒÂ³ del conductor"
    row["ConducNom"] = "NICOLAS ARIEL EZEQUIEL RUIZ"
    row["ConducApellido1"] = ""
    row["ConducApellido2"] = ""
    row["ConducDni"] = "12345678Z"

    payloads = asyncio.run(adapter.build_payloads([row]))

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["identificado_nombre"] == "NICOLAS ARIEL EZEQUIEL"
    assert payload["identificado_apellido1"] == "RUIZ"
    assert payload["identificado_apellido2"] == ""


def test_build_payloads_identificacion_same_person_inherits_client_identity_and_address_when_sparse() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["FaseProcedimiento"] = "IdentificaciÃƒÂ³ del conductor"
    row["cliente_nombre"] = "MARTA CINTA"
    row["cliente_apellido1"] = "ORTEGA"
    row["cliente_apellido2"] = "GUIMONS"
    row["cliente_nif"] = "40947574X"
    row["cl_calle"] = "SANT RAMON DE PENYAFORT"
    row["cl_numero"] = "124-1"
    row["cl_cp"] = "08031"
    row["cl_poblacion"] = "Barcelona"
    row["cl_provincia"] = "Barcelona"
    row["ConducNom"] = "MARTA CINTA ORTEGA"
    row["ConducApellido1"] = ""
    row["ConducApellido2"] = ""
    row["ConducDni"] = "40947574X"
    row["ConducAdr"] = ""
    row["ConducNumero"] = ""
    row["ConducCodpost"] = ""
    row["ConducPobl"] = ""
    row["ConducProv"] = ""

    payloads = asyncio.run(adapter.build_payloads([row]))

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["identificado_nombre"] == "MARTA CINTA"
    assert payload["identificado_apellido1"] == "ORTEGA"
    assert payload["identificado_apellido2"] == "GUIMONS"
    assert payload["identificado_cp"] == "08031"
    assert payload["identificado_municipio"] == "Barcelona"
    assert payload["identificado_provincia"] == "Barcelona"


def test_build_payloads_identificacion_pf_requires_document_and_name() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["FaseProcedimiento"] = "IdentificaciÃ³ del conductor"
    row["ConducNom"] = ""
    row["ConducDni"] = ""
    discards: list[dict] = []

    payloads = asyncio.run(adapter.build_payloads([row], on_discard=discards.append))

    assert payloads == []
    assert any(
        d.get("tipo_incidencia") == "SITE_RULE_DISCARDED"
        and "Identificacion fisica sin documento o nombre del identificado" in str(d.get("motivo"))
        for d in discards
    )


def test_build_payloads_identificacion_pj_requires_nif_empresa_and_razon_social() -> None:
    adapter = ServeiCatTransAdapter()
    row = _base_row()
    row["FaseProcedimiento"] = "IdentificaciÃ³ del conductor"
    row["identificado_tipo_persona"] = "juridica"
    row["ConducCif"] = ""
    row["ConducRazonSocial"] = ""
    discards: list[dict] = []

    payloads = asyncio.run(adapter.build_payloads([row], on_discard=discards.append))

    assert payloads == []
    assert any(
        d.get("tipo_incidencia") == "SITE_RULE_DISCARDED"
        and "Identificacion juridica sin nif_empresa o razon_social del identificado" in str(d.get("motivo"))
        for d in discards
    )
