from services.payload_validator.app import PayloadValidatorService


def test_incident_type_for_missing_client_folder() -> None:
    reason = "Carpeta de documentacion no existe: /mnt/clientes/A-C/CLIENTE/DOCUMENTACION"
    incident = PayloadValidatorService._incident_type_for_gesdoc_reason(reason)
    assert incident == "CLIENT_FOLDER_NOT_FOUND"


def test_incident_type_for_missing_authorization() -> None:
    reason = "No se encontro autorizacion (AUT) en: /mnt/clientes/A-C/CLIENTE/DOCUMENTACION"
    incident = PayloadValidatorService._incident_type_for_gesdoc_reason(reason)
    assert incident == "CLIENT_AUTHORIZATION_MISSING"


def test_incident_type_for_generic_gesdoc_reason() -> None:
    reason = "Requiere autorizacion GESDOC"
    incident = PayloadValidatorService._incident_type_for_gesdoc_reason(reason)
    assert incident == "REQUIRES_GESDOC"


def test_normalize_job_type_uses_canonical_phase_fallback() -> None:
    raw_payload = {
        "__canonical_v1": {
            "resource": {
                "phase": "Identificacion del conductor",
            }
        }
    }
    assert PayloadValidatorService._normalize_job_type(raw_payload) == "P1"


def test_hydrate_payload_from_canonical_sets_identity_defaults() -> None:
    raw_payload = {
        "__canonical_v1": {
            "resource": {
                "id": 6001,
                "exp_id": 7001,
                "numclient": 999,
                "expedient": "2026/12345-MUL",
                "phase": "Alegaciones",
                "subject_name": "ACME SL",
            },
            "client": {
                "type": 2,
                "document": {"nif": "", "cif": "B12345678"},
                "name": {"business": "ACME SL", "first": "", "last1": "", "last2": ""},
                "contact": {"email": "info@acme.test", "phone1": "930000000", "phone2": "", "mobile": "600000000"},
                "address": {
                    "street_name": "CALLE MAYOR",
                    "number": "10",
                    "floor": "",
                    "door": "",
                    "zip": "08001",
                    "city": "BARCELONA",
                    "province": "BARCELONA",
                },
            },
            "vehicle": {
                "plate": {"value": "1234ABC"},
            },
        }
    }
    hydrated = PayloadValidatorService._hydrate_payload_from_canonical(raw_payload)
    assert hydrated["idRecurso"] == 6001
    assert hydrated["numclient"] == 999
    assert hydrated["Expedient"] == "2026/12345-MUL"
    assert hydrated["cliente_razon_social"] == "ACME SL"
    assert hydrated["cif"] == "B12345678"
    assert hydrated["cliente_domicilio"] == "CALLE MAYOR"
