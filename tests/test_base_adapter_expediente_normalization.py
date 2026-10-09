from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from core.domain import ResourceDomain
from sites.adapters.base import BaseOnlineAdapter


@pytest.fixture
def adapter(monkeypatch):
    adapter = BaseOnlineAdapter()
    monkeypatch.setattr(adapter._groq_guardian, "classify_batch", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "core.client_docs_service.get_required_client_documents", AsyncMock(return_value=[])
    )
    monkeypatch.setattr("sites.adapters.base.build_sqlserver_connection_string", lambda: "unused")
    return adapter


@pytest.fixture
def candidate():
    return {
        "idRecurso": 139938,
        "idExp": 881498,
        "Expedient": "43185- 2026/12279- GIM",
        "Organisme": "BASE GESTION INGRESOS",
        "TExp": 3,
        "Estado": 0,
        "numclient": 12001,
        "UsuarioAsignado": "",
        "FaseProcedimiento": "Identificacion",
        "SujetoRecurso": "CLIENTE TEST",
        "matricula": "1234ABC",
        "FAlta": "2026-10-08",
        "cliente_nif": "12345678Z",
        "cliente_nombre": "CLIENTE",
        "cliente_apellido1": "TEST",
        "conduc_dni": "12345678Z",
        "conduc_nom": "CONDUCTOR TEST",
        "conduc_adr": "CALLE MAYOR 10",
        "conduc_codpost": "08001",
        "conduc_pobl": "BARCELONA",
        "conduc_prov": "BARCELONA",
    }


class _Repository:
    def __init__(self, candidate):
        self.candidate = candidate

    def get_pending_resources(self, *, site_id, config, limit):
        return [ResourceDomain.from_row(site_id=site_id, row=deepcopy(self.candidate))]


@pytest.mark.parametrize(
    "raw, canonical, expected_parts",
    [
        ("43185- 2026/12279- GIM", "43185-2026/12279-GIM", ("43185", "2026", "12279")),
        (" \t43185-\u00a02026 / 12279- gim\n", "43185-2026/12279-GIM", ("43185", "2026", "12279")),
        ("43038- 2026 /2710", "43038-2026/2710", ("43038", "2026", "2710")),
        ("43185- 202635924- gim", "43185-202635924-GIM", ("43185", "2026", "35924")),
        ("43155- 2026 -205- GIM", "43155-2026-205-GIM", ("43155", "2026", "205")),
        ("43185-2026/12279-GIM", "43185-2026/12279-GIM", ("43185", "2026", "12279")),
    ],
)
def test_hydrated_p1_expediente_matches_initial_candidate(adapter, candidate, raw, canonical, expected_parts):
    candidate["Expedient"] = raw
    discarded = []
    selected = adapter.fetch_candidates(
        config={"regex_expediente": BaseOnlineAdapter.DEFAULT_REGEX_EXPEDIENTE},
        conn_str="unused",
        authenticated_user=None,
        limit=1,
        resource_repo=_Repository(candidate),
        on_discard=discarded.append,
    )
    assert len(selected) == 1
    assert selected[0]["Expedient"] == canonical

    # Full SQL hydration restores the original spelling after initial selection.
    hydrated = {**selected[0], **deepcopy(candidate)}
    before = deepcopy(hydrated)
    payloads = asyncio.run(adapter.build_payloads([hydrated], on_discard=discarded.append))
    assert discarded == []
    assert len(payloads) == 1
    assert hydrated == before
    payload = payloads[0]
    assert payload["protocol"] == "P1"
    assert payload["expediente"] == canonical
    assert payload["num_butlleti"] == canonical
    assert tuple(payload[key] for key in ("expediente_id_ens", "expediente_any", "expediente_num")) == expected_parts

    canonical_payload = asyncio.run(adapter.build_payloads([{**hydrated, "Expedient": canonical}]))[0]
    payload.pop("claimed_at")
    canonical_payload.pop("claimed_at")
    assert payload == canonical_payload


@pytest.mark.parametrize(
    "expediente",
    [
        "43185- 2026/12A79- GIM",
        "4318- 2026/12279- GIM",
        "43185- 202/12279- GIM",
        "43185- 2026/122790- GIM",
        "43185-- 2026/12279- GIM",
        "1- 2026/12345- EXE",
        "1- 2026/12345- ECC",
    ],
)
def test_normalization_keeps_invalid_p1_expedientes_discarded(adapter, candidate, expediente):
    candidate["Expedient"] = expediente
    discarded = []
    assert asyncio.run(adapter.build_payloads([candidate], on_discard=discarded.append)) == []
    assert len(discarded) == 1
    assert discarded[0]["tipo_incidencia"] == "SITE_RULE_DISCARDED"
    assert discarded[0]["motivo"] == "P1 solo admite expedientes base validos (con o sin -GIM)"


@pytest.mark.parametrize("missing", ["conduc_dni", "conduc_nom", "conduc_codpost"])
def test_valid_expediente_still_requires_p1_driver_data(adapter, candidate, missing):
    candidate[missing] = ""
    discarded = []
    assert asyncio.run(adapter.build_payloads([candidate], on_discard=discarded.append)) == []
    assert len(discarded) == 1
    assert discarded[0]["tipo_incidencia"] == "SITE_RULE_DISCARDED"
    assert "expedientes base validos" not in discarded[0]["motivo"]


@pytest.mark.parametrize("phase, protocol", [("Alegaciones", "P2"), ("Embargo", "P3")])
def test_normalized_expediente_preserves_other_protocol_fields(adapter, candidate, phase, protocol):
    candidate["FaseProcedimiento"] = phase
    original = deepcopy(candidate)
    payloads = asyncio.run(adapter.build_payloads([candidate]))
    canonical_payloads = asyncio.run(
        adapter.build_payloads([{**candidate, "Expedient": "43185-2026/12279-GIM"}])
    )
    assert len(payloads) == len(canonical_payloads) == 1
    assert payloads[0]["protocol"] == protocol
    assert candidate == original
    payloads[0].pop("claimed_at")
    canonical_payloads[0].pop("claimed_at")
    assert payloads == canonical_payloads
