from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from core.consultor.normalizer import normalize_resource_row
from core.consultor.service import ConsultorResourceRepositoryAdapter, ConsultorService
from core.domain import ResourceDomain
from sites.adapters.base import BaseOnlineAdapter
from sites.adapters.madrid import MadridAdapter
from sites.adapters.redsara import RedsaraAdapter
from sites.adapters.terrassa import TerrassaAdapter
from sites.adapters.valencia import ValenciaAdapter
from sites.adapters.xaloc_girona import XalocAdapter
import sites.adapters.base as base_mod
import sites.adapters.redsara as redsara_mod
import sites.adapters.terrassa as terrassa_mod
import sites.adapters.valencia as valencia_mod
import core.client_docs_service as client_docs_service_mod


class _LegacyRepo:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int) -> list[ResourceDomain]:
        return [ResourceDomain.from_row(site_id=site_id, row=row) for row in self.rows[: int(limit)]]


class _ConfigCaptureRepo:
    def __init__(self):
        self.last_config: dict[str, Any] | None = None

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int) -> list[ResourceDomain]:
        self.last_config = dict(config or {})
        return []


async def _fake_classify_batch(*, items: list[dict], context_by_id: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in items:
        rid = str(item.get("idRecurso") or "").strip()
        if not rid:
            continue
        out[rid] = {
            "tipo_via": "CALLE",
            "calle": "MAYOR",
            "numero": "10",
            "escalera": "",
            "planta": "",
            "puerta": "",
        }
    return out


async def _fake_docs_builder(*_args: Any, **_kwargs: Any) -> list[str]:
    return []


def _normalize_payload_for_compare(payload: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(payload)
    out.pop("claimed_at", None)
    return out


def _assert_site_payload_parity(
    *,
    adapter: Any,
    site_id: str,
    config: dict[str, Any],
    row: dict[str, Any],
) -> None:
    legacy_repo = _LegacyRepo([row])
    consultor_service = ConsultorService(conn_str="unused", repository=legacy_repo)
    consultor_repo = ConsultorResourceRepositoryAdapter(consultor_service)

    legacy_candidates = adapter.fetch_candidates(
        config=config,
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=legacy_repo,
    )
    consultor_candidates = adapter.fetch_candidates(
        config=config,
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=consultor_repo,
    )

    legacy_payloads = asyncio.run(adapter.build_payloads(legacy_candidates))
    consultor_payloads = asyncio.run(adapter.build_payloads(consultor_candidates))

    assert len(legacy_payloads) == 1, f"{site_id}: expected exactly one legacy payload"
    assert len(consultor_payloads) == 1, f"{site_id}: expected exactly one consultor payload"
    assert _normalize_payload_for_compare(legacy_payloads[0]) == _normalize_payload_for_compare(consultor_payloads[0])


def test_madrid_payload_parity_legacy_vs_consultor(monkeypatch) -> None:
    adapter = MadridAdapter()
    monkeypatch.setattr(adapter._groq_guardian, "classify_batch", _fake_classify_batch)

    row = {
        "idRecurso": 3001,
        "idExp": 4001,
        "Expedient": "935/12345678.9",
        "Organisme": "SUBDIRECCION GNAL GESTION MULTAS DE MADRID",
        "TExp": 2,
        "Estado": 0,
        "numclient": 9001,
        "SujetoRecurso": "JUAN PEREZ",
        "FaseProcedimiento": "Identificacion",
        "UsuarioAsignado": "",
        "notas": "",
        "rs_matricula": "1234ABC",
        "matricula": "",
        "pub_publicacion": "",
        "cif": "",
        "cliente_tipo": 1,
        "cliente_nif": "12345678Z",
        "cliente_nif_empresa": "",
        "cliente_nombre": "JUAN",
        "cliente_apellido1": "PEREZ",
        "cliente_apellido2": "LOPEZ",
        "cliente_razon_social": "",
        "cliente_provincia": "MADRID",
        "cliente_municipio": "MADRID",
        "cliente_domicilio": "CALLE MAYOR",
        "cliente_numero": "10",
        "cliente_escalera": "",
        "cliente_planta": "",
        "cliente_puerta": "",
        "cliente_cp": "28001",
        "cliente_email": "juan@example.com",
        "cliente_tel1": "910000000",
        "cliente_tel2": "",
        "cliente_movil": "600000000",
        "adjuntos": [{"id": 21, "filename": "madrid.pdf"}],
    }

    _assert_site_payload_parity(
        adapter=adapter,
        site_id="madrid",
        config={"regex_expediente": MadridAdapter.DEFAULT_REGEX_EXPEDIENTE},
        row=row,
    )


def test_madrid_fetch_candidates_accepts_hyphen_prefixed_expediente() -> None:
    adapter = MadridAdapter()
    row = {
        "idRecurso": 110493,
        "idExp": 4002,
        "Expedient": "935-155274083.6",
        "Organisme": "SUBDIRECCION GNAL GESTION MULTAS DE MADRID",
        "TExp": 2,
        "Estado": 0,
        "numclient": 9002,
        "SujetoRecurso": "JUAN PEREZ",
        "FaseProcedimiento": "Sancion",
        "UsuarioAsignado": "",
        "adjuntos": [],
    }
    legacy_repo = _LegacyRepo([row])
    discarded: list[dict[str, Any]] = []

    candidates = adapter.fetch_candidates(
        config={"regex_expediente": MadridAdapter.DEFAULT_REGEX_EXPEDIENTE},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=legacy_repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert len(candidates) == 1
    assert candidates[0]["Expedient"] == "935-155274083.6"
    assert discarded == []


def test_madrid_parse_expediente_normalizes_hyphen_prefix_to_canonical_slash() -> None:
    parts = MadridAdapter._parse_expediente("935-155334109.3", fase_raw="Sancion", es_empresa=False)

    assert parts["expediente_completo"] == "935/155334109.3"
    assert parts["expediente_tipo"] == "opcion1"
    assert parts["expediente_nnn"] == "935"
    assert parts["expediente_eeeeeeeee"] == "155334109"
    assert parts["expediente_d"] == "3"


def test_madrid_fetch_candidates_expands_query_organisme_for_ayuntamiento() -> None:
    adapter = MadridAdapter()
    repo = _ConfigCaptureRepo()

    adapter.fetch_candidates(
        config={"query_organisme": "%SUBDIRECCION GNAL GESTION MULTAS DE MADRID%"},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=repo,
    )

    assert repo.last_config is not None
    assert repo.last_config["query_organisme"] == (
        "%SUBDIRECCION GNAL GESTION MULTAS DE MADRID%|%AYUNTAMIENTO DE MADRID%"
    )


def test_base_online_payload_parity_legacy_vs_consultor(monkeypatch) -> None:
    adapter = BaseOnlineAdapter()
    monkeypatch.setattr(adapter._groq_guardian, "classify_batch", _fake_classify_batch)
    monkeypatch.setattr(client_docs_service_mod, "get_required_client_documents", _fake_docs_builder)
    monkeypatch.setattr(base_mod, "build_sqlserver_connection_string", lambda: "unused")

    row = {
        "idRecurso": 3101,
        "idExp": 4101,
        "Expedient": "12345-2024/1234-GIM",
        "Organisme": "BASE GESTION INGRESOS",
        "TExp": 2,
        "Estado": 0,
        "numclient": 9101,
        "SujetoRecurso": "ACME SL",
        "FaseProcedimiento": "Alegaciones",
        "UsuarioAsignado": "",
        "FAlta": "2026-01-01",
        "dia_denuncia": "2026-01-01",
        "matricula": "4567DEF",
        "cif": "B12345678",
        "conduc_nom": "JUAN PEREZ",
        "conduc_dni": "12345678Z",
        "conduc_adr": "CALLE MAYOR",
        "conduc_codpost": "08001",
        "conduc_pobl": "BARCELONA",
        "conduc_prov": "BARCELONA",
        "cliente_nif": "B12345678",
        "cliente_nombre": "ACME",
        "cliente_apellido1": "",
        "cliente_apellido2": "",
        "cliente_razon_social": "ACME SL",
        "cliente_provincia": "BARCELONA",
        "cliente_municipio": "BARCELONA",
        "cliente_domicilio": "CALLE MAYOR",
        "cliente_numero": "10",
        "cliente_escalera": "",
        "cliente_planta": "",
        "cliente_puerta": "",
        "cliente_cp": "08001",
        "cliente_email": "info@acme.test",
        "cliente_tel1": "930000000",
        "cliente_tel2": "",
        "cliente_movil": "600000001",
        "adjuntos": [{"id": 22, "filename": "base.pdf"}],
    }

    _assert_site_payload_parity(
        adapter=adapter,
        site_id="base_online",
        config={"regex_expediente": BaseOnlineAdapter.DEFAULT_REGEX_EXPEDIENTE},
        row=row,
    )


def test_base_online_fetch_candidates_accepts_no_gim_with_legacy_regex() -> None:
    adapter = BaseOnlineAdapter()
    legacy_regex_without_plain_branch = (
        r"^(\d{5}-\d{4}[/\-]\d{1,5}-GIM|\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{7}|\d-\d{4}[/\-]\d{4,6}-(EXE|ECC))$"
    )
    row = {
        "idRecurso": 103275,
        "idExp": 5001,
        "Expedient": "43038-2026/2710",
        "Organisme": "BASE GESTION INGRESOS",
        "TExp": 2,
        "Estado": 0,
        "numclient": 12345,
        "SujetoRecurso": "CLIENTE TEST",
        "FaseProcedimiento": "Alegaciones",
        "UsuarioAsignado": "",
    }
    legacy_repo = _LegacyRepo([row])
    discarded: list[dict[str, Any]] = []

    candidates = adapter.fetch_candidates(
        config={"regex_expediente": legacy_regex_without_plain_branch},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=legacy_repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert len(candidates) == 1
    assert candidates[0]["Expedient"] == "43038-2026/2710"
    assert discarded == []


def test_base_online_fetch_candidates_upgrades_legacy_pg_regex_for_short_gim() -> None:
    adapter = BaseOnlineAdapter()
    legacy_pg_regex = (
        r"^\s*(\d{5}-\d{4}[/\-]\d{4,5}-GIM|\d{5}-\d{4}/\d{1,5}|\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{6,7}|\d-\d{4}[/\-]\d{4,6}-(EXE|ECC))\s*$"
    )
    row = {
        "idRecurso": 104261,
        "idExp": 5002,
        "Expedient": "43155-2026-205-GIM",
        "Organisme": "BASE GESTION INGRESOS",
        "TExp": 2,
        "Estado": 0,
        "numclient": 12346,
        "SujetoRecurso": "CLIENTE TEST",
        "FaseProcedimiento": "Alegaciones",
        "UsuarioAsignado": "",
    }
    legacy_repo = _LegacyRepo([row])
    discarded: list[dict[str, Any]] = []

    candidates = adapter.fetch_candidates(
        config={"regex_expediente": legacy_pg_regex},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=legacy_repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert len(candidates) == 1
    assert candidates[0]["Expedient"] == "43155-2026-205-GIM"
    assert discarded == []


def test_base_online_build_payloads_p1_accepts_no_gim_and_parses_parts(monkeypatch) -> None:
    adapter = BaseOnlineAdapter()
    monkeypatch.setattr(adapter._groq_guardian, "classify_batch", _fake_classify_batch)
    monkeypatch.setattr(client_docs_service_mod, "get_required_client_documents", _fake_docs_builder)
    monkeypatch.setattr(base_mod, "build_sqlserver_connection_string", lambda: "unused")

    candidate = {
        "idRecurso": 103275,
        "idExp": 5101,
        "numclient": 12001,
        "Expedient": "43038-2026/2710",
        "FaseProcedimiento": "Identificacion",
        "SujetoRecurso": "CONDUCTOR TEST",
        "matricula": "1234ABC",
        "dia_denuncia": "2026-03-23",
        "FAlta": "2026-03-23",
        "cif": "",
        "cliente_nif": "47236831Y",
        "conduc_dni": "47236831Y",
        "conduc_nom": "ALBERT ROSSON PICO",
        "conduc_adr": "CALLE MAYOR",
        "conduc_codpost": "08001",
        "conduc_pobl": "BARCELONA",
        "conduc_prov": "BARCELONA",
        "cliente_nombre": "ALBERT",
        "cliente_apellido1": "ROSSON",
        "cliente_apellido2": "PICO",
        "cliente_razon_social": "",
        "cliente_escalera": "",
        "cliente_planta": "",
        "cliente_puerta": "",
    }
    discarded: list[dict[str, Any]] = []

    payloads = asyncio.run(adapter.build_payloads([candidate], on_discard=lambda item: discarded.append(item)))

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["protocol"] == "P1"
    assert payload["expediente"] == "43038-2026/2710"
    assert payload["expediente_id_ens"] == "43038"
    assert payload["expediente_any"] == "2026"
    assert payload["expediente_num"] == "2710"
    assert payload["num_butlleti"] == "43038-2026/2710"
    assert discarded == []


def test_redsara_payload_parity_legacy_vs_consultor(monkeypatch) -> None:
    adapter = RedsaraAdapter()
    monkeypatch.setattr(redsara_mod, "get_required_client_documents", _fake_docs_builder)
    monkeypatch.setattr(redsara_mod, "build_sqlserver_connection_string", lambda: "unused")

    row = {
        "idRecurso": 3201,
        "idExp": 4201,
        "Expedient": "888249540",
        "Organisme": "AYUNTAMIENTO DE MOSTOLES",
        "TExp": 2,
        "Estado": 0,
        "numclient": 9201,
        "SujetoRecurso": "ACME SL",
        "FaseProcedimiento": "Alegaciones",
        "UsuarioAsignado": "",
        "cliente_tipo": 2,
        "cif": "B12345678",
        "cliente_nif": "",
        "cliente_nif_empresa": "B12345678",
        "cliente_nombre": "",
        "cliente_apellido1": "",
        "cliente_apellido2": "",
        "cliente_razon_social": "ACME SL",
        "cliente_domicilio": "CALLE MAYOR",
        "cliente_cp": "28931",
        "cliente_municipio": "MOSTOLES",
        "cliente_provincia": "MADRID",
        "cliente_email": "info@acme.test",
        "cliente_tel1": "910000001",
        "cliente_tel2": "",
        "cliente_movil": "600000002",
        "adjuntos": [{"id": 23, "filename": "redsara.pdf"}],
    }

    _assert_site_payload_parity(
        adapter=adapter,
        site_id="redsara",
        config={},
        row=row,
    )


def test_terrassa_payload_parity_legacy_vs_consultor(monkeypatch) -> None:
    adapter = TerrassaAdapter()
    monkeypatch.setattr(terrassa_mod, "get_required_client_documents", _fake_docs_builder)
    monkeypatch.setattr(terrassa_mod, "build_sqlserver_connection_string", lambda: "unused")

    row = {
        "idRecurso": 3301,
        "idExp": 4301,
        "Expedient": "1234/2024",
        "Organisme": "AYUNTAMIENTO DE TERRASSA",
        "TExp": 2,
        "Estado": 0,
        "numclient": 9301,
        "SujetoRecurso": "JUAN PEREZ",
        "FaseProcedimiento": "Alegaciones",
        "UsuarioAsignado": "",
        "FAlta": "2026-02-01",
        "cliente_tipo": 1,
        "cliente_nif": "12345678Z",
        "cliente_nif_empresa": "",
        "cliente_nombre": "JUAN",
        "cliente_apellido1": "PEREZ",
        "cliente_apellido2": "LOPEZ",
        "cliente_razon_social": "",
        "rs_matricula": "7890GHI",
        "exp_matricula": "",
        "pub_matricula": "",
        "pub_publicacion": "",
        "adjuntos": [{"id": 24, "filename": "terrassa.pdf"}],
    }

    _assert_site_payload_parity(
        adapter=adapter,
        site_id="terrassa",
        config={},
        row=row,
    )


def test_xaloc_girona_payload_parity_legacy_vs_consultor(monkeypatch) -> None:
    adapter = XalocAdapter()

    row = {
        "idRecurso": 3401,
        "idExp": 4401,
        "Expedient": "2026/12345-MUL",
        "Organisme": "XALOC GIRONA",
        "TExp": 2,
        "Estado": 0,
        "numclient": 9401,
        "SujetoRecurso": "ACME SL",
        "FaseProcedimiento": "Alegaciones",
        "FUsuarioCompletado": None,
        "UsuarioAsignado": "",
        "matricula": "1111JKL",
        "cif": "B12345678",
        "nifempresa": "B12345678",
        "Empresa": "ACME SL",
        "Nombrefiscal": "ACME SL",
        "cliente_tipo": 2,
        "cliente_nif": "",
        "cliente_nombre": "",
        "cliente_apellido1": "",
        "cliente_apellido2": "",
        "adjuntos": [{"id": 25, "filename": "xaloc.pdf"}],
    }

    _assert_site_payload_parity(
        adapter=adapter,
        site_id="xaloc_girona",
        config={"query_organisme": "%XALOC%"},
        row=row,
    )


def test_xaloc_girona_fetch_candidates_accepts_new_alphanumeric_and_13digit_formats() -> None:
    adapter = XalocAdapter()
    rows = [
        {
            "idRecurso": 3411,
            "idExp": 4411,
            "Expedient": "2026-O-00000141",
            "Organisme": "XALOC GIRONA",
            "TExp": 2,
            "Estado": 0,
            "numclient": 9411,
            "SujetoRecurso": "CLIENTE A",
            "FaseProcedimiento": "Alegaciones",
            "FUsuarioCompletado": None,
            "UsuarioAsignado": "",
        },
        {
            "idRecurso": 3412,
            "idExp": 4412,
            "Expedient": "0448640179907",
            "Organisme": "XALOC GIRONA",
            "TExp": 2,
            "Estado": 0,
            "numclient": 9412,
            "SujetoRecurso": "CLIENTE B",
            "FaseProcedimiento": "Alegaciones",
            "FUsuarioCompletado": None,
            "UsuarioAsignado": "",
        },
        {
            "idRecurso": 3413,
            "idExp": 4413,
            "Expedient": "2026-Z-00464013",
            "Organisme": "XALOC GIRONA",
            "TExp": 2,
            "Estado": 0,
            "numclient": 9413,
            "SujetoRecurso": "CLIENTE C",
            "FaseProcedimiento": "Alegaciones",
            "FUsuarioCompletado": None,
            "UsuarioAsignado": "",
        },
    ]
    legacy_repo = _LegacyRepo(rows)
    discarded: list[dict[str, Any]] = []

    candidates = adapter.fetch_candidates(
        config={"query_organisme": "%XALOC%"},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=legacy_repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert [item["Expedient"] for item in candidates] == [
        "2026-O-00000141",
        "0448640179907",
        "2026-Z-00464013",
    ]
    assert discarded == []


def test_valencia_payload_parity_legacy_vs_consultor(monkeypatch) -> None:
    adapter = ValenciaAdapter()
    monkeypatch.setattr(valencia_mod, "get_required_client_documents", _fake_docs_builder)
    monkeypatch.setattr(valencia_mod, "build_sqlserver_connection_string", lambda: "unused")

    row = {
        "idRecurso": 3501,
        "idExp": 4501,
        "Expedient": "MU 2025 81 10058239  2",
        "Organisme": "AJUNTAMENT DE VALENCIA",
        "TExp": 2,
        "Estado": 0,
        "numclient": 9501,
        "SujetoRecurso": "JUAN PEREZ",
        "FaseProcedimiento": "Denuncia",
        "UsuarioAsignado": "",
        "cliente_tipo": 1,
        "cliente_nif": "12345678Z",
        "cliente_nif_empresa": "",
        "cliente_nombre": "JUAN",
        "cliente_apellido1": "PEREZ",
        "cliente_apellido2": "LOPEZ",
        "cliente_razon_social": "",
        "conduc_nom": "JUAN PEREZ",
        "conduc_dni": "12345678Z",
        "conduc_codpost": "46001",
        "conduc_adr": "CALLE MAYOR 10",
        "rs_matricula": "1234ABC",
        "exp_matricula": "",
        "pub_matricula": "",
        "adjuntos": [{"id": 26, "filename": "valencia.pdf"}],
    }

    _assert_site_payload_parity(
        adapter=adapter,
        site_id="valencia",
        config={},
        row=row,
    )


def test_consultor_normalizer_resolves_plate_from_publication_text() -> None:
    canonical = normalize_resource_row(
        site_id="diputacio_bcn",
        row={
            "idRecurso": 1,
            "Expedient": "542006/25",
            "Organisme": "AJUNTAMENT DE BADALONA",
            "FaseProcedimiento": "denuncia",
            "pub_publicacion": "Matricula 1234BCD. Aviso de denuncia.",
            "matricula": "",
            "rs_matricula": "",
            "exp_matricula": "",
            "pub_matricula": "",
        },
    )

    assert canonical.vehicle["plate"]["value"] == "1234BCD"
    assert canonical.vehicle["plate"]["source"] == "pub_publicacion"
