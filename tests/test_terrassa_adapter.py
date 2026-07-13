from __future__ import annotations

import asyncio
from typing import Any

from core.domain import ResourceDomain
from sites.adapters.terrassa import TerrassaAdapter
import sites.adapters.terrassa as terrassa_mod


class _LegacyRepo:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def get_pending_resources(self, *, site_id: str, config: dict, limit: int) -> list[ResourceDomain]:
        return [ResourceDomain.from_row(site_id=site_id, row=row) for row in self.rows[: int(limit)]]


async def _fake_docs_builder(*_args: Any, **_kwargs: Any) -> list[str]:
    return []


def _base_row() -> dict[str, Any]:
    return {
        "idRecurso": 1,
        "idExp": 2,
        "Expedient": "1234/2024",
        "Organisme": "AYUNTAMIENTO DE TERRASSA",
        "TExp": 2,
        "Estado": 0,
        "numclient": 3,
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
        "adjuntos": [],
    }


def test_terrassa_fetch_candidates_accepts_murc_shapes() -> None:
    adapter = TerrassaAdapter()
    rows = [
        {**_base_row(), "idRecurso": 101, "Expedient": "MURC-731/2025"},
        {**_base_row(), "idRecurso": 102, "Expedient": "MURC-1194/2025"},
    ]
    repo = _LegacyRepo(rows)
    discarded: list[dict[str, Any]] = []

    candidates = adapter.fetch_candidates(
        config={},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert [c["idRecurso"] for c in candidates] == [101, 102]
    assert candidates[0]["Expedient"] == "MURC-731/2025"
    assert candidates[1]["Expedient"] == "MURC-1194/2025"
    assert discarded == []


def test_terrassa_fetch_candidates_accepts_sadm_shapes() -> None:
    adapter = TerrassaAdapter()
    rows = [
        {**_base_row(), "idRecurso": 105, "Expedient": "SADM2025159"},
    ]
    repo = _LegacyRepo(rows)
    discarded: list[dict[str, Any]] = []

    candidates = adapter.fetch_candidates(
        config={},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert len(candidates) == 1
    assert candidates[0]["idRecurso"] == 105
    assert candidates[0]["Expedient"] == "SADM2025159"
    assert discarded == []


def test_terrassa_fetch_candidates_accepts_p_plus_nine_digits() -> None:
    adapter = TerrassaAdapter()
    rows = [
        {**_base_row(), "idRecurso": 106, "Expedient": "P260996560"},
    ]
    repo = _LegacyRepo(rows)
    discarded: list[dict[str, Any]] = []

    candidates = adapter.fetch_candidates(
        config={},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert len(candidates) == 1
    assert candidates[0]["idRecurso"] == 106
    assert candidates[0]["Expedient"] == "P260996560"
    assert discarded == []


def test_terrassa_fetch_candidates_accepts_pc_plus_eight_digits() -> None:
    adapter = TerrassaAdapter()
    rows = [
        {**_base_row(), "idRecurso": 107, "Expedient": "PC61003408"},
    ]
    repo = _LegacyRepo(rows)
    discarded: list[dict[str, Any]] = []

    candidates = adapter.fetch_candidates(
        config={},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=repo,
        on_discard=lambda item: discarded.append(item),
    )

    assert len(candidates) == 1
    assert candidates[0]["idRecurso"] == 107
    assert candidates[0]["Expedient"] == "PC61003408"
    assert discarded == []


def test_terrassa_fetch_candidates_trims_trailing_reference_expediente() -> None:
    adapter = TerrassaAdapter()
    row = {**_base_row(), "idRecurso": 103, "Expedient": "RD50285579 MURC-01271/2026"}
    repo = _LegacyRepo([row])

    candidates = adapter.fetch_candidates(
        config={},
        conn_str="unused",
        authenticated_user=None,
        limit=10,
        resource_repo=repo,
    )

    assert len(candidates) == 1
    assert candidates[0]["Expedient"] == "RD50285579"


def test_terrassa_build_payloads_uses_normalized_expediente(monkeypatch) -> None:
    adapter = TerrassaAdapter()
    monkeypatch.setattr(terrassa_mod, "get_required_client_documents", _fake_docs_builder)
    monkeypatch.setattr(terrassa_mod, "build_sqlserver_connection_string", lambda: "unused")

    candidate = {**_base_row(), "idRecurso": 104, "Expedient": "RD50285579 MURC-01271/2026"}
    payloads = asyncio.run(adapter.build_payloads([candidate]))

    assert len(payloads) == 1
    assert payloads[0]["expediente"] == "RD50285579"
