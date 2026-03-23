from __future__ import annotations

import asyncio
from copy import deepcopy

from core.consultor.service import ConsultorResourceRepositoryAdapter, ConsultorService
from core.domain import ResourceDomain
from sites.adapters.ayunta_palma import AyuntaPalmaAdapter


class _LegacyRepo:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int) -> list[ResourceDomain]:
        return [ResourceDomain.from_row(site_id=site_id, row=row) for row in self.rows[: int(limit)]]


class _CaptureConfigRepo:
    def __init__(self):
        self.last_config: dict | None = None

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int) -> list[ResourceDomain]:
        self.last_config = dict(config or {})
        return []


def _normalize_payload_for_compare(payload: dict) -> dict:
    out = deepcopy(payload)
    out.pop("claimed_at", None)
    return out


def test_ayunta_palma_payload_parity_legacy_vs_consultor() -> None:
    adapter = AyuntaPalmaAdapter()
    row = {
        "idRecurso": 2001,
        "idExp": 3001,
        "Expedient": "MU 90046663",
        "Organisme": "AYUNTAMIENTO DE PALMA DE MALLORCA",
        "TExp": 2,
        "Estado": 0,
        "numclient": 12345,
        "SujetoRecurso": "ACME SL",
        "FaseProcedimiento": "Alegaciones",
        "UsuarioAsignado": "",
        "cif": "B12345678",
        "matricula": "1234 ABC",
        "cliente_tipo": 2,
        "cliente_nif": "",
        "cliente_nif_empresa": "B12345678",
        "cliente_nombre": "",
        "cliente_apellido1": "",
        "cliente_apellido2": "",
        "cliente_razon_social": "ACME SL",
        "cliente_email": "info@example.com",
        "cliente_tel1": "971000000",
        "cliente_movil": "600000000",
        "adjuntos": [{"id": 11, "filename": "doc.pdf"}],
    }

    legacy_repo = _LegacyRepo([row])
    consultor_service = ConsultorService(conn_str="unused", repository=legacy_repo)
    consultor_repo = ConsultorResourceRepositoryAdapter(consultor_service)

    legacy_candidates = adapter.fetch_candidates(
        config={"regex_expediente": AyuntaPalmaAdapter.DEFAULT_REGEX_EXPEDIENTE},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=legacy_repo,
    )
    consultor_candidates = adapter.fetch_candidates(
        config={"regex_expediente": AyuntaPalmaAdapter.DEFAULT_REGEX_EXPEDIENTE},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=consultor_repo,
    )

    legacy_payloads = asyncio.run(adapter.build_payloads(legacy_candidates))
    consultor_payloads = asyncio.run(adapter.build_payloads(consultor_candidates))

    assert len(legacy_payloads) == 1
    assert len(consultor_payloads) == 1
    assert _normalize_payload_for_compare(legacy_payloads[0]) == _normalize_payload_for_compare(consultor_payloads[0])


def test_ayunta_palma_query_organisme_includes_mallorca_alias() -> None:
    adapter = AyuntaPalmaAdapter()
    repo = _CaptureConfigRepo()

    adapter.fetch_candidates(
        config={
            "query_organisme": "%AYUNTAMENT DE PALMA%",
            "regex_expediente": AyuntaPalmaAdapter.DEFAULT_REGEX_EXPEDIENTE,
        },
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=repo,
    )

    assert repo.last_config is not None
    query = str(repo.last_config.get("query_organisme") or "")
    assert "%AYUNTAMENT DE PALMA%" in query
    assert "%AYUNTAMIENTO DE MALLORCA%" in query


def test_ayunta_palma_build_payload_uses_tipodecliente_legacy_key() -> None:
    adapter = AyuntaPalmaAdapter()
    candidates = [
        {
            "idRecurso": 9001,
            "idExp": 99001,
            "numclient": 555,
            "Expedient": "MU90046663",
            "SujetoRecurso": "EMPRESA TEST SL",
            "FaseProcedimiento": "Alegaciones",
            "matricula": "1111AAA",
            "tipodecliente": 2,
            "cif": "B12345678",
            "cliente_razon_social": "EMPRESA TEST SL",
            "adjuntos": [],
        }
    ]

    payloads = asyncio.run(adapter.build_payloads(candidates))
    assert len(payloads) == 1
    assert payloads[0]["tipo_persona"] == "PersonaJuridica"
    assert payloads[0]["nif_empresa"] == "B12345678"
    assert payloads[0]["razon_social"] == "EMPRESA TEST SL"


def test_ayunta_palma_fetch_candidates_accepts_expediente_with_suffix_letter_on_legacy_regex() -> None:
    adapter = AyuntaPalmaAdapter()
    row = {
        "idRecurso": 103051,
        "idExp": 5001,
        "Expedient": "1428510R",
        "Organisme": "AYUNTAMIENTO DE PALMA DE MALLORCA",
        "TExp": 2,
        "Estado": 0,
        "numclient": 12345,
        "SujetoRecurso": "CLIENTE TEST",
        "FaseProcedimiento": "Alegaciones",
        "UsuarioAsignado": "",
    }
    legacy_repo = _LegacyRepo([row])
    discarded: list[dict] = []

    candidates = adapter.fetch_candidates(
        config={"regex_expediente": AyuntaPalmaAdapter.LEGACY_REGEX_EXPEDIENTE},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=legacy_repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert len(candidates) == 1
    assert candidates[0]["Expedient"] == "1428510R"
    assert discarded == []
