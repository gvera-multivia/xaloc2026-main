from __future__ import annotations

from sites.base_online.controller import BaseOnlineController
from sites.madrid.controller import MadridController
from sites.redsara.controller import RedsaraController
from sites.xaloc_girona.controller import XalocGironaController


def test_xaloc_map_data_prefers_canonical_when_legacy_missing() -> None:
    controller = XalocGironaController()
    payload = {
        "__canonical_v1": {
            "resource": {"expedient": "EXP-1", "phase": "Alegaciones"},
            "client": {"contact": {"email": "info@acme.test"}},
            "vehicle": {"plate": {"value": "1234ABC"}},
        },
        "motivos": "motivos canon",
        "archivos": ["a.pdf"],
    }

    mapped = controller.map_data(payload)
    assert mapped["email"] == "info@acme.test"
    assert mapped["num_denuncia"] == "EXP-1"
    assert mapped["num_expediente"] == "EXP-1"
    assert mapped["matricula"] == "1234ABC"
    assert mapped["fase_procedimiento"] == "Alegaciones"


def test_base_online_map_data_prefers_canonical_when_legacy_missing() -> None:
    controller = BaseOnlineController()
    payload = {
        "__canonical_v1": {
            "resource": {"expedient": "BO-2026-01"},
            "client": {
                "document": {"nif": "12345678Z"},
                "contact": {"email": "base@test.com", "mobile": "600111222", "phone2": "931111111"},
                "address": {
                    "street_name": "CALLE MAYOR",
                    "number": "10",
                    "zip": "08001",
                    "city": "BARCELONA",
                    "province": "BARCELONA",
                    "country": "ESPANA",
                },
            },
            "vehicle": {"plate": {"value": "9999ZZZ"}},
        },
    }

    mapped = controller.map_data(payload)
    assert mapped["p1_correu"] == "base@test.com"
    assert mapped["p1_telefon_mobil"] == "600111222"
    assert mapped["p1_telefon_fix"] == "931111111"
    assert mapped["p1_matricula"] == "9999ZZZ"
    assert mapped["p1_identificacio"] == "12345678Z"
    assert mapped["p1_address_street"] == "CALLE MAYOR"
    assert mapped["p1_address_zip"] == "08001"
    assert mapped["p1_address_city"] == "BARCELONA"
    assert mapped["p1_address_province"] == "BARCELONA"
    assert mapped["p1_address_pais"] == "ESPANA"


def test_redsara_map_data_prefers_canonical_when_legacy_missing() -> None:
    controller = RedsaraController()
    payload = {
        "__canonical_v1": {
            "client": {
                "type": 2,
                "document": {"cif": "B12345678"},
                "name": {"business": "ACME SL"},
                "address": {"street_name": "ARIBAU 1", "zip": "08008", "city": "BARCELONA", "province": "BARCELONA"},
            }
        },
        "subject": "Asunto",
        "exposes": "Expone",
        "solicit": "Solicita",
        "archivos": ["d.pdf"],
    }

    mapped = controller.map_data(payload)
    assert mapped["interested_is_company"] is True
    assert mapped["interested_doc_type"] == "CIF"
    assert mapped["interested_doc_number"] == "B12345678"
    assert mapped["interested_name"] == "ACME SL"
    assert mapped["interested_address"] == "ARIBAU 1"
    assert mapped["interested_zip"] == "08008"
    assert mapped["interested_city"] == "BARCELONA"
    assert mapped["interested_province"] == "BARCELONA"


def test_redsara_map_data_normalizes_multiline_interested_address() -> None:
    controller = RedsaraController()
    payload = {
        "cliente_tipo": 2,
        "cif": "B12345678",
        "cliente_razon_social": "ACME SL",
        "address_street": "MOLI DE LA TORRE\r\nPASSEIG DEL PONT\r\nPASSEIG DEL PONT, 1",
        "address_zip": "17163",
        "address_city": "FORNELLS DE LA SELVA",
        "address_province": "GIRONA",
        "destination_organism_code": "LA0006797",
        "subject": "Asunto",
        "exposes": "Expone",
        "solicit": "Solicita",
        "archivos": ["a.pdf"],
    }

    mapped = controller.map_data(payload)
    assert mapped["interested_address"] == "PASSEIG DEL PONT, 1"
    assert mapped["interested_zip"] == "17163"
    assert mapped["interested_city"] == "FORNELLS DE LA SELVA"
    assert mapped["interested_province"] == "GIRONA"


def test_madrid_map_data_prefers_canonical_when_legacy_missing() -> None:
    controller = MadridController()
    payload = {
        "__canonical_v1": {
            "resource": {"id": 55},
            "client": {
                "name": {"first": "JUAN"},
                "contact": {"mobile": "600222333", "email": "notif@test.com"},
                "address": {
                    "street_name": "ALCALA",
                    "number": "1",
                    "zip": "28001",
                    "city": "MADRID",
                    "province": "MADRID",
                    "country": "ESPANA",
                },
            },
            "vehicle": {"plate": {"value": "1234ABC"}},
        },
    }

    mapped = controller.map_data(payload)
    assert mapped["idRecurso"] == 55
    assert mapped["matricula"] == "1234ABC"
    assert mapped["inter_telefono"] == "600222333"
    assert mapped["notif_nombre"] == "JUAN"
    assert mapped["notif_email"] == "notif@test.com"
    assert mapped["notif_nombre_via"] == "ALCALA"
    assert mapped["notif_numero"] == "1"
    assert mapped["notif_codigo_postal"] == "28001"
