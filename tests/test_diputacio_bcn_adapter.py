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
        self.last_limit: int | None = None

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int):
        del site_id, config
        self.last_limit = int(limit or 0)
        return [_FakeResource(metadata=row) for row in self._rows[: self.last_limit]]


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
    assert "%AJUNTAMENT DE BADALONA%" in merged
    assert "%AJUNTAMENT DE GRANOLLERS%" in merged


def test_merge_query_organisme_does_not_duplicate_patterns() -> None:
    base = (
        "%AJUNTAMENT DE SABADELL%|"
        "%ORGANISME DE GESTI%TRIBUT%ORGT%DIPUTACI%BARCELONA%|"
        "%ORGANISMO DE GESTION TRIBUT%ORGT%DIPUTACION DE BARCELONA%|"
        "%AJUNTAMENT DE BADALONA%|"
        "%AJUNTAMENT DE GRANOLLERS%"
    )
    merged = DiputacioBcnAdapter._merge_query_organisme(base)
    assert merged.count("%ORGANISME DE GESTI%TRIBUT%ORGT%DIPUTACI%BARCELONA%") == 1
    assert merged.count("%ORGANISMO DE GESTION TRIBUT%ORGT%DIPUTACION DE BARCELONA%") == 1
    assert merged.count("%AJUNTAMENT DE BADALONA%") == 1
    assert merged.count("%AJUNTAMENT DE GRANOLLERS%") == 1


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
        authenticated_user="Daniel Gonzalez",
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
        authenticated_user="Daniel Gonzalez",
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


def test_fetch_candidates_accepts_identificacion_phase() -> None:
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
    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 200003
    assert discards == []


def test_fetch_candidates_discards_when_assigned_to_other_user() -> None:
    adapter = _make_adapter_with_allowed({"AYUNTAMIENTO DE IGUALADA"})
    discards: list[dict] = []
    repo = _FakeRepo(
        [
            {
                "idRecurso": 200004,
                "Expedient": "IG-004/26",
                "Organisme": "AYUNTAMIENTO DE IGUALADA",
                "FaseProcedimiento": "denuncia",
                "Estado": 1,
                "UsuarioAsignado": "Ainoa Gan",
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AYUNTAMIENTO DE IGUALADA%"},
        conn_str="dummy",
        authenticated_user="Daniel Gonzalez",
        limit=50,
        resource_repo=repo,
        on_discard=lambda d: discards.append(d),
    )
    assert len(candidates) == 0
    assert len(discards) == 1
    assert discards[0]["tipo_incidencia"] == "RESOURCE_ASSIGNED_TO_OTHER_USER"


def test_fetch_candidates_keeps_orgt_barcelona_city_as_diputacio_candidate() -> None:
    """ORGT con cliente de Barcelona ya NO se redirige a RedSara; queda en Diputacio BCN."""
    adapter = _make_adapter_with_allowed(set())
    repo = _FakeRepo(
        [
            {
                "idRecurso": 200005,
                "Expedient": "0187374314",
                "Organisme": "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
                "cliente_municipio": "BARCELONA",
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%ORGT%"},
        conn_str="dummy",
        authenticated_user="test",
        limit=50,
        resource_repo=repo,
    )
    # Ya no se redirige a RedSara: el recurso se mantiene como candidato de Diputacio BCN.
    assert len(candidates) == 1
    assert candidates[0]["idRecurso"] == 200005



def test_extract_municipio_from_organisme_returns_empty_for_orgt_diba_alias() -> None:
    value = "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA"
    assert DiputacioBcnAdapter._extract_municipio_from_organisme(value) == ""


def test_build_payloads_prefers_organisme_municipio_when_resolvable() -> None:
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
                    "Organisme": "AYUNTAMIENTO DE IGUALADA",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "JUAN PEREZ",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "JUAN",
                    "Apellido1": "PEREZ",
                    "Apellido2": "LOPEZ",
                    "Nombrefiscal": "",
                    "cliente_municipio": "CALZADA DE CALATRAVA",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["municipio"] == "IGUALADA"
    assert payloads[0]["codmuni"] == "101"


def test_build_payloads_prefers_organisme_hospitalet_over_wrong_client_municipio() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555002,
                    "idExp": 777002,
                    "numclient": 999002,
                    "automatic_id": 12346,
                    "Expedient": "542000/25",
                    "Organisme": "AJUNTAMENT DE HOSPITALET DE LLOBREGAT",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "MARIA PEREZ",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "MARIA",
                    "Apellido1": "PEREZ",
                    "Apellido2": "LOPEZ",
                    "Nombrefiscal": "",
                    "cliente_municipio": "BARCELONA",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["municipio"] == "HOSPITALET DE LLOBREGAT"
    assert payloads[0]["codmuni"] == "100"


def test_build_payloads_prefers_organisme_manresa_over_client_badalona() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555009,
                    "idExp": 777009,
                    "numclient": 999009,
                    "automatic_id": 12353,
                    "Expedient": "542007/25",
                    "Organisme": "AJUNTAMENT DE MANRESA",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "CARLA SERRA",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "CARLA",
                    "Apellido1": "SERRA",
                    "Apellido2": "PUJOL",
                    "Nombrefiscal": "",
                    "cliente_municipio": "BADALONA",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["municipio"] == "MANRESA"
    assert payloads[0]["codmuni"] == "113"


def test_build_payloads_prefers_organisme_caldes_de_estrac() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555010,
                    "idExp": 777010,
                    "numclient": 999010,
                    "automatic_id": 12354,
                    "Expedient": "2600000533",
                    "Organisme": "AJUNTAMENT DE CALDES DE ESTRAC",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "CARLA SERRA",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "CARLA",
                    "Apellido1": "SERRA",
                    "Apellido2": "PUJOL",
                    "Nombrefiscal": "",
                    "cliente_municipio": "BADALONA",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["municipio"] == "CALDES DE ESTRAC"
    assert payloads[0]["codmuni"] == "032"


def test_build_payloads_prefers_organisme_santa_coloma_de_gramanet_typo() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555011,
                    "idExp": 777011,
                    "numclient": 999011,
                    "automatic_id": 12355,
                    "Expedient": "26015819",
                    "Organisme": "AJUNTAMENT DE SANTA COLOMA DE GRAMANET",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "CARLA SERRA",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "CARLA",
                    "Apellido1": "SERRA",
                    "Apellido2": "PUJOL",
                    "Nombrefiscal": "",
                    "cliente_municipio": "BADALONA",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["municipio"] == "SANTA COLOMA DE GRAMANET"
    assert payloads[0]["codmuni"] == "245"


def test_build_payloads_prefers_organisme_granollers() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555012,
                    "idExp": 777012,
                    "numclient": 999012,
                    "automatic_id": 12356,
                    "Expedient": "202600006564",
                    "Organisme": "AJUNTAMENT DE GRANOLLERS",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "CARLA SERRA",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "CARLA",
                    "Apellido1": "SERRA",
                    "Apellido2": "PUJOL",
                    "Nombrefiscal": "",
                    "cliente_municipio": "BADALONA",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["municipio"] == "GRANOLLERS"
    assert payloads[0]["codmuni"] == "096"


def test_fetch_candidates_allows_manresa_when_explicitly_configured() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 200006,
                "Expedient": "1751795",
                "Organisme": "AJUNTAMENT DE MANRESA",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE MANRESA%"},
        conn_str="dummy",
        authenticated_user="Daniel Gonzalez",
        limit=50,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 200006


def test_fetch_candidates_allows_caldes_de_estrac_when_explicitly_configured() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 111622,
                "Expedient": "2600000533",
                "Organisme": "AJUNTAMENT DE CALDES DE ESTRAC",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE CALDES DE ESTRAC%"},
        conn_str="dummy",
        authenticated_user="Daniel Gonzalez",
        limit=50,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 111622


def test_fetch_candidates_allows_santa_coloma_de_gramanet_when_explicitly_configured() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 112415,
                "Expedient": "26015819",
                "Organisme": "AJUNTAMENT DE SANTA COLOMA DE GRAMANET",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE SANTA COLOMA DE GRAMANET%"},
        conn_str="dummy",
        authenticated_user="Daniel Gonzalez",
        limit=50,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 112415


def test_fetch_candidates_allows_granollers_when_explicitly_configured() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 123071,
                "Expedient": "202600006564",
                "Organisme": "AJUNTAMENT DE GRANOLLERS",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE GRANOLLERS%"},
        conn_str="dummy",
        authenticated_user="Daniel Gonzalez",
        limit=50,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 123071


def test_fetch_candidates_allows_badalona_when_config_is_stale() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 123591,
                "Expedient": "0020421834",
                "Organisme": "AJUNTAMENT DE BADALONA",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE SABADELL%"},
        conn_str="dummy",
        authenticated_user="Daniel Gonzalez",
        limit=50,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 123591


def test_fetch_candidates_allows_badalona_identificacion() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 123591,
                "Expedient": "0020421834",
                "Organisme": "AJUNTAMENT DE BADALONA",
                "SujetoRecurso": "ABEL BERNALDEZ PERALTA",
                "FaseProcedimiento": "identificacion",
                "Estado": 0,
                "UsuarioAsignado": None,
            }
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT DE BADALONA%"},
        conn_str="dummy",
        authenticated_user="Daniel Gonzalez",
        limit=50,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 123591
    assert candidates[0]["FaseProcedimiento"] == "identificacion"


def test_fetch_candidates_overscans_before_applying_adapter_filters() -> None:
    adapter = DiputacioBcnAdapter()
    adapter._load_allowed_organismes = lambda _conn: set()  # type: ignore[method-assign]
    adapter._load_organisme_urls = lambda _conn: {}  # type: ignore[method-assign]

    repo = _FakeRepo(
        [
            {
                "idRecurso": 100001,
                "Expedient": "NO-SOPORTADO",
                "Organisme": "AJUNTAMENT NO SUPORTAT",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            },
            {
                "idRecurso": 123591,
                "Expedient": "0020421834",
                "Organisme": "AJUNTAMENT DE BADALONA",
                "FaseProcedimiento": "denuncia",
                "Estado": 0,
                "UsuarioAsignado": None,
            },
        ]
    )
    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%AJUNTAMENT%"},
        conn_str="dummy",
        authenticated_user="Daniel Gonzalez",
        limit=1,
        resource_repo=repo,
    )

    assert repo.last_limit and repo.last_limit > 1
    assert len(candidates) == 1
    assert int(candidates[0]["idRecurso"]) == 123591


def test_build_payloads_uses_client_municipio_for_orgt_alias() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555003,
                    "idExp": 777003,
                    "numclient": 999003,
                    "automatic_id": 12347,
                    "Expedient": "542001/25",
                    "Organisme": "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "JOAN PEREZ",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "JOAN",
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


def test_build_payloads_uses_notas_for_orgt_when_municipio_unresolvable() -> None:
    """Cuando cliente_municipio es BARCELONA (irresoluble para ORGT) se usa exp_notas."""
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555005,
                    "idExp": 777005,
                    "numclient": 999005,
                    "automatic_id": 12349,
                    "Expedient": "542003/25",
                    "Organisme": "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "MARC PUIG",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "MARC",
                    "Apellido1": "PUIG",
                    "Apellido2": "",
                    "Nombrefiscal": "",
                    "cliente_municipio": "BARCELONA",
                    "exp_notas": "25-0117905 55289676E 3452-KJD 10/12/2025 12:00 L'HOSPITALET DE LLOBREGAT 80,00 94.02 RGC 000",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["municipio"] == "HOSPITALET DE LLOBREGAT"
    assert payloads[0]["codmuni"] == "100"


def test_build_payloads_random_fallback_when_no_municipio_resolvable_for_orgt() -> None:
    """Cuando ninguna via resuelve municipio, el payload usa un fallback aleatorio (no descarta)."""
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555006,
                    "idExp": 777006,
                    "numclient": 999006,
                    "automatic_id": 12350,
                    "Expedient": "542004/25",
                    "Organisme": "ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "ANNA ROCA",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "ANNA",
                    "Apellido1": "ROCA",
                    "Apellido2": "",
                    "Nombrefiscal": "",
                    "cliente_municipio": "BARCELONA",  # irresoluble para ORGT
                    "exp_notas": "",  # sin notas utiles
                    "adjuntos": [],
                }
            ]
        )
    )

    # El recurso NO debe descartarse; debe tener algun codmuni del catalogo.
    assert len(payloads) == 1
    codmuni = payloads[0]["codmuni"]
    assert codmuni != ""
    # El codmuni debe ser un valor conocido del catalogo
    from sites.diputacio_bcn.municipio_codes import KNOWN_CODES
    assert codmuni in KNOWN_CODES


def test_build_payloads_resolves_uppercase_matricula_fallback() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555007,
                    "idExp": 777007,
                    "numclient": 999007,
                    "automatic_id": 12351,
                    "Expedient": "542005/25",
                    "Organisme": "AJUNTAMENT DE BADALONA",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "MARTA SERRA",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "MARTA",
                    "Apellido1": "SERRA",
                    "Apellido2": "",
                    "Nombrefiscal": "",
                    "municipio": "BADALONA",
                    "Matricula": "1234BCD",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["matricula"] == "1234BCD"


def test_build_payloads_resolves_matricula_from_pub_publicacion_text() -> None:
    adapter = DiputacioBcnAdapter()
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 555008,
                    "idExp": 777008,
                    "numclient": 999008,
                    "automatic_id": 12352,
                    "Expedient": "542006/25",
                    "Organisme": "AJUNTAMENT DE BADALONA",
                    "FaseProcedimiento": "denuncia",
                    "SujetoRecurso": "MARTA SERRA",
                    "tipodecliente": "1",
                    "nif": "12345678Z",
                    "nifempresa": "",
                    "Nombre": "MARTA",
                    "Apellido1": "SERRA",
                    "Apellido2": "",
                    "Nombrefiscal": "",
                    "municipio": "BADALONA",
                    "pub_publicacion": "Sancion de trafico. Matricula 1234BCD. Notificacion.",
                    "adjuntos": [],
                }
            ]
        )
    )

    assert len(payloads) == 1
    assert payloads[0]["matricula"] == "1234BCD"
