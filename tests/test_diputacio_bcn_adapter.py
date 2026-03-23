from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sites.adapters.diputacio_bcn import DiputacioBcnAdapter


@dataclass
class _FakeResource:
    metadata: dict


class _FakeRepo:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int):
        del site_id, config, limit
        return [_FakeResource(metadata=row) for row in self._rows]


def test_has_direct_non_orgt_route_for_barcelona() -> None:
    organisme_urls = {
        "AJUNTAMENT DE BARCELONA": {
            "https://seuelectronica.ajuntament.barcelona.cat/APPS/portaltramits/formulari/ptbidcond/T142/init/ca/PTCIU.html"
        }
    }

    assert DiputacioBcnAdapter._has_direct_non_orgt_route("AJUNTAMENT DE BARCELONA", organisme_urls) is True


def test_has_direct_non_orgt_route_for_terrassa() -> None:
    organisme_urls = {
        "AYUNTAMIENTO DE TERRASSA": {
            "https://aoberta.terrassa.cat/tramits/fitxa.jsp?id=3821"
        }
    }

    assert DiputacioBcnAdapter._has_direct_non_orgt_route("AYUNTAMIENTO DE TERRASSA", organisme_urls) is True


def test_has_direct_non_orgt_route_is_false_for_orgt_only() -> None:
    organisme_urls = {
        "AJUNTAMENT DE SABADELL": {DiputacioBcnAdapter.ORGT_IDENTIFICACIO_URL}
    }

    assert DiputacioBcnAdapter._has_direct_non_orgt_route("AJUNTAMENT DE SABADELL", organisme_urls) is False


def test_has_direct_non_orgt_route_is_false_when_unknown() -> None:
    organisme_urls = {}

    assert DiputacioBcnAdapter._has_direct_non_orgt_route("ORGANISME DESCONEGUT", organisme_urls) is False


def test_is_orgt_diba_alias_accepts_orgt_officina_multes() -> None:
    value = "ORGANISME DE GESTIÓ TRIBUTÀRIA (ORGT) - OFICINA DE MULTES DIPUTACIÓ DE BARCELONA"
    assert DiputacioBcnAdapter._is_orgt_diba_alias(value) is True


def test_is_orgt_diba_alias_accepts_orgt_diputacion_variant() -> None:
    value = "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA"
    assert DiputacioBcnAdapter._is_orgt_diba_alias(value) is True


def test_is_orgt_diba_alias_rejects_non_diba_orgt() -> None:
    value = "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE OTRO SITIO"
    assert DiputacioBcnAdapter._is_orgt_diba_alias(value) is False


def test_merge_query_organisme_adds_orgt_diba_patterns() -> None:
    merged = DiputacioBcnAdapter._merge_query_organisme("%AJUNTAMENT DE SABADELL%|%AYUNTAMIENTO DE CASTELLDEFELS%")
    assert "%AJUNTAMENT DE SABADELL%" in merged
    assert "%AYUNTAMIENTO DE CASTELLDEFELS%" in merged
    assert "%ORGANISME DE GESTI%TRIBUT%ORGT%DIPUTACI%BARCELONA%" in merged
    assert "%ORGANISMO DE GESTION TRIBUT%ORGT%DIPUTACION DE BARCELONA%" in merged


def test_merge_query_organisme_does_not_duplicate_patterns() -> None:
    base = (
        "%AJUNTAMENT DE SABADELL%|"
        "%ORGANISME DE GESTI%TRIBUT%ORGT%DIPUTACI%BARCELONA%|"
        "%ORGANISMO DE GESTION TRIBUT%ORGT%DIPUTACION DE BARCELONA%"
    )
    merged = DiputacioBcnAdapter._merge_query_organisme(base)
    assert merged.count("%ORGANISME DE GESTI%TRIBUT%ORGT%DIPUTACI%BARCELONA%") == 1
    assert merged.count("%ORGANISMO DE GESTION TRIBUT%ORGT%DIPUTACION DE BARCELONA%") == 1


def test_extract_explicit_organismes_from_query_ignores_internal_wildcards() -> None:
    query = (
        "%AJUNTAMENT DE SABADELL%|"
        "%ORGANISME DE GESTI%TRIBUT%ORGT%DIPUTACI%BARCELONA%|"
        "%ORGANISMO DE GESTION TRIBUT%ORGT%DIPUTACION DE BARCELONA%"
    )
    extracted = DiputacioBcnAdapter._extract_explicit_organismes_from_query(query)
    assert "AJUNTAMENT DE SABADELL" in extracted
    assert len(extracted) == 1


def test_fetch_candidates_allows_orgt_alias_even_if_not_in_allowed_catalog() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 103216,
                "Expedient": "541699/25",
                "Organisme": "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE SABADELL%"},
        conn_str="dummy",
        authenticated_user="Guillen Vera",
        limit=50,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 103216


def test_fetch_candidates_allows_organisme_from_query_when_catalog_empty() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 103217,
                "Expedient": "541700/25",
                "Organisme": "AJUNTAMENT L'HOSPITALET DE LLOBREGAT",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT  L´HOSPITALET DE LLOBREGAT%"},
        conn_str="dummy",
        authenticated_user="Guillen Vera",
        limit=50,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 103217


def _make_adapter_with_allowed(organismes: set[str]) -> DiputacioBcnAdapter:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: organismes  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]
    return adapter


def test_fetch_candidates_allows_apremio_phase() -> None:
    adapter = _make_adapter_with_allowed({"AJUNTAMENT DE SABADELL"})
    repo = _FakeRepo(
        [
            {
                "idRecurso": 200001,
                "Expedient": "AP-001/25",
                "Organisme": "AJUNTAMENT DE SABADELL",
                "FaseProcedimiento": "apremio",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE SABADELL%"},
        conn_str="dummy",
        authenticated_user="test",
        limit=50,
        resource_repo=repo,
    )
    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 200001


def test_fetch_candidates_allows_embargo_phase() -> None:
    adapter = _make_adapter_with_allowed({"AJUNTAMENT DE SABADELL"})
    repo = _FakeRepo(
        [
            {
                "idRecurso": 200002,
                "Expedient": "EM-002/25",
                "Organisme": "AJUNTAMENT DE SABADELL",
                "FaseProcedimiento": "embargo",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE SABADELL%"},
        conn_str="dummy",
        authenticated_user="test",
        limit=50,
        resource_repo=repo,
    )
    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 200002


def test_fetch_candidates_still_blocks_identificacion_phase() -> None:
    adapter = _make_adapter_with_allowed({"AJUNTAMENT DE SABADELL"})
    discards: list[dict] = []
    repo = _FakeRepo(
        [
            {
                "idRecurso": 200003,
                "Expedient": "ID-003/25",
                "Organisme": "AJUNTAMENT DE SABADELL",
                "FaseProcedimiento": "identificacion",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE SABADELL%"},
        conn_str="dummy",
        authenticated_user="test",
        limit=50,
        resource_repo=repo,
        on_discard=lambda d: discards.append(d),
    )
    assert len(candidates) == 0
    assert len(discards) == 1


def test_extract_municipio_from_organisme_returns_empty_for_orgt_diba_alias() -> None:
    value = "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA"
    assert DiputacioBcnAdapter._extract_municipio_from_organisme(value) == ""


def test_build_payloads_prefers_client_municipio_over_organisme() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555001,
                    "idExp": 777001,
                    "numclient": 999001,
                    "automatic_id": 12345,
                    "Expedient": "541999/25",
                    "Organisme": "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "JUAN PEREZ",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "JUAN",
                    "Apellido1": "PEREZ",
                    "Apellido2": "LOPEZ",
                    "Nombrefiscal": "",
                    "cliente_municipio": "SABADELL",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["municipio"] == "SABADELL"
    assert payloads[0]["codmuni"] == "186"
