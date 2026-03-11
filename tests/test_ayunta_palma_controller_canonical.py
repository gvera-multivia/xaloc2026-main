from __future__ import annotations

from sites.ayunta_palma.controller import AyuntaPalmaController


def test_map_data_prefers_canonical_when_legacy_missing() -> None:
    controller = AyuntaPalmaController()
    payload = {
        "__canonical_v1": {
            "resource": {
                "expedient": "MU90046663",
            },
            "client": {
                "type": 2,
                "document": {"nif": "", "cif": "B12345678"},
                "name": {"first": "", "last1": "", "last2": "", "business": "ACME SL"},
                "contact": {"email": "info@acme.test", "mobile": "600000000"},
            },
            "vehicle": {
                "plate": {"value": "1234ABC"},
            },
        },
        "expone": "texto expone",
        "solicita": "texto solicita",
    }

    mapped = controller.map_data(payload)
    assert mapped["tipo_persona"] == "PersonaJuridica"
    assert mapped["nif_empresa"] == "B12345678"
    assert mapped["razon_social"] == "ACME SL"
    assert mapped["email"] == "info@acme.test"
    assert mapped["telefono"] == "600000000"
    assert mapped["expediente"] == "MU90046663"
    assert mapped["matricula"] == "1234ABC"


def test_map_data_keeps_legacy_priority() -> None:
    controller = AyuntaPalmaController()
    payload = {
        "tipo_persona": "PersonaFisica",
        "tipo_documento": "F",
        "documento": "12345678Z",
        "nombre": "JUAN",
        "apellido1": "PEREZ",
        "email": "legacy@example.com",
        "telefono": "699111222",
        "expediente": "MU90000001",
        "matricula": "0000ZZZ",
        "expone": "e",
        "solicita": "s",
        "__canonical_v1": {
            "resource": {"expedient": "SHOULD_NOT_WIN"},
            "client": {"document": {"nif": "99999999R"}},
            "vehicle": {"plate": {"value": "1111AAA"}},
        },
    }

    mapped = controller.map_data(payload)
    assert mapped["tipo_persona"] == "PersonaFisica"
    assert mapped["documento"] == "12345678Z"
    assert mapped["email"] == "legacy@example.com"
    assert mapped["telefono"] == "699111222"
    assert mapped["expediente"] == "MU90000001"
    assert mapped["matricula"] == "0000ZZZ"


def test_map_data_tipodecliente_2_maps_to_persona_juridica() -> None:
    controller = AyuntaPalmaController()
    payload = {
        "tipodecliente": 2,
        "cif": "B12345678",
        "cliente_razon_social": "EMPRESA DEMO SL",
        "expediente": "MU90000002",
        "matricula": "2222BBB",
        "expone": "e",
        "solicita": "s",
    }

    mapped = controller.map_data(payload)
    assert mapped["tipo_persona"] == "PersonaJuridica"
    assert mapped["nif_empresa"] == "B12345678"
    assert mapped["razon_social"] == "EMPRESA DEMO SL"
