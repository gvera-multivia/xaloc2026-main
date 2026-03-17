from __future__ import annotations

import asyncio

import sites.adapters.valencia as valencia_adapter_mod
from core.worker_execution.task_orchestrator import _validate_valencia_preconditions
from sites.adapters.valencia import ValenciaAdapter
from sites.valencia.controller import ValenciaController
from sites.valencia.flows.common import get_matricula


async def _fake_docs_builder(*_args, **_kwargs) -> list[str]:
    return []


def test_valencia_controller_syncs_dot_plate_into_payload() -> None:
    controller = ValenciaController()

    mapped = controller.map_data(
        {
            "idRecurso": 77,
            "idExp": 88,
            "expediente": "MU 2025 81 10058239 2",
            "fase_procedimiento": "Sancion",
            "plate_number": "???",
            "matricula": "",
            "matricula2": " ",
            "matricula3": None,
        }
    )

    target = controller.create_target(**mapped)

    assert mapped["matricula"] == "."
    assert mapped["payload"]["matricula"] == "."
    assert mapped["payload"]["plate_number"] == "."
    assert target.matricula == "."
    assert target.payload["matricula"] == "."
    assert target.payload["plate_number"] == "."


def test_valencia_get_matricula_returns_dot_when_all_fallbacks_fail() -> None:
    assert get_matricula(".", "", None) == "."
    assert get_matricula(".", "1234ABC", "") == "1234ABC"


def test_valencia_adapter_keeps_mu_sa_40_payload_valid_without_plate(monkeypatch) -> None:
    adapter = ValenciaAdapter()
    monkeypatch.setattr(valencia_adapter_mod, "get_required_client_documents", _fake_docs_builder)
    monkeypatch.setattr(valencia_adapter_mod, "build_sqlserver_connection_string", lambda: "unused")

    discards: list[dict] = []
    payloads = asyncio.run(
        adapter.build_payloads(
            [
                {
                    "idRecurso": 3502,
                    "idExp": 4502,
                    "numclient": 9502,
                    "Expedient": "MU 2025 81 10058239 2",
                    "FaseProcedimiento": "Sancion",
                    "cliente_tipo": 1,
                    "cliente_nif": "12345678Z",
                    "cliente_nombre": "JUAN",
                    "cliente_apellido1": "PEREZ",
                    "cliente_apellido2": "LOPEZ",
                    "SujetoRecurso": "JUAN PEREZ",
                    "conduc_nom": "JUAN PEREZ",
                    "conduc_dni": "12345678Z",
                    "rs_matricula": "",
                    "exp_matricula": "",
                    "pub_matricula": "",
                    "adjuntos": [],
                }
            ],
            on_discard=discards.append,
        )
    )

    assert discards == []
    assert len(payloads) == 1
    assert payloads[0]["tramite_code"] == "MU.SA.40"
    assert payloads[0]["matricula"] == "."
    assert payloads[0]["plate_number"] == "."


def test_valencia_preconditions_accept_dot_plate_for_mu_sa_40() -> None:
    payload = {
        "idRecurso": 3503,
        "expediente": "MU 2025 81 10058239 2",
        "tramite_code": "MU.SA.40",
        "matricula": "",
        "matricula2": "",
        "matricula3": "",
    }

    result = _validate_valencia_preconditions(payload)

    assert result is None
    assert payload["matricula"] == "."
    assert payload["plate_number"] == "."
