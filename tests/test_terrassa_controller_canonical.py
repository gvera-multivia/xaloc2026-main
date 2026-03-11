from __future__ import annotations

from sites.terrassa.controller import TerrassaController


def test_map_data_prefers_canonical_when_legacy_missing() -> None:
    controller = TerrassaController()
    payload = {
        "__canonical_v1": {
            "resource": {
                "id": 101,
                "exp_id": 202,
                "numclient": 303,
                "expedient": "TR-2026-0001",
                "phase": "Alegaciones",
                "subject_name": "ACME SL",
            },
            "client": {
                "type": 2,
                "document": {"nif": "", "cif": "B12345678"},
                "name": {"first": "", "last1": "", "last2": "", "business": "ACME SL"},
            },
            "vehicle": {
                "plate": {"value": "1234ABC"},
            },
        },
        "motivos": "Texto alegaciones",
        "solicita": "Texto observaciones",
        "archivos": ["doc1.pdf"],
    }

    mapped = controller.map_data(payload)
    assert mapped["idRecurso"] == 101
    assert mapped["idExp"] == 202
    assert mapped["numclient"] == 303
    assert mapped["expediente"] == "TR-2026-0001"
    assert mapped["is_company"] is True
    assert mapped["document_number"] == "B12345678"
    assert mapped["nombre"] == "ACME SL"
    assert mapped["matricula"] == "1234ABC"
    assert mapped["alegaciones"] == "Texto alegaciones"
    assert mapped["observaciones"] == "Texto observaciones"
    assert mapped["fase_procedimiento"] == "Alegaciones"
    assert mapped["sujeto_recurso"] == "ACME SL"


def test_map_data_keeps_legacy_priority() -> None:
    controller = TerrassaController()
    payload = {
        "idRecurso": 1,
        "idExp": 2,
        "numclient": 3,
        "expediente": "LEG-0001",
        "is_company": False,
        "document_number": "12345678Z",
        "nombre": "LEGACY NAME",
        "apellido1": "PEREZ",
        "apellido2": "GOMEZ",
        "matricula": "0000ZZZ",
        "alegaciones": "legacy alegaciones",
        "observaciones": "legacy observaciones",
        "fase_procedimiento": "legacy fase",
        "sujeto_recurso": "legacy sujeto",
        "__canonical_v1": {
            "resource": {
                "id": 999,
                "exp_id": 888,
                "numclient": 777,
                "expedient": "CAN-0001",
                "phase": "canon fase",
                "subject_name": "canon sujeto",
            },
            "client": {
                "type": 2,
                "document": {"nif": "00000000T", "cif": "B00000000"},
                "name": {"first": "CANON", "last1": "SUR1", "last2": "SUR2", "business": "CANON SL"},
            },
            "vehicle": {"plate": {"value": "1111AAA"}},
        },
    }

    mapped = controller.map_data(payload)
    assert mapped["idRecurso"] == 1
    assert mapped["idExp"] == 2
    assert mapped["numclient"] == 3
    assert mapped["expediente"] == "LEG-0001"
    assert mapped["is_company"] is False
    assert mapped["document_number"] == "12345678Z"
    assert mapped["nombre"] == "LEGACY NAME"
    assert mapped["apellido1"] == "PEREZ"
    assert mapped["apellido2"] == "GOMEZ"
    assert mapped["matricula"] == "0000ZZZ"
    assert mapped["alegaciones"] == "legacy alegaciones"
    assert mapped["observaciones"] == "legacy observaciones"
    assert mapped["fase_procedimiento"] == "legacy fase"
    assert mapped["sujeto_recurso"] == "legacy sujeto"
