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


def test_fetch_candidates_discards_invalid_expediente_shape() -> None:
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
    assert out == []


def test_fetch_candidates_discards_identificacion_phase() -> None:
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
    assert out == []


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
