from services.payload_validator.app import PayloadValidatorService


def test_incident_type_for_missing_client_folder() -> None:
    reason = "Carpeta de documentación no existe: /mnt/clientes/A-C/CLIENTE/DOCUMENTACION"
    incident = PayloadValidatorService._incident_type_for_gesdoc_reason(reason)
    assert incident == "CLIENT_FOLDER_NOT_FOUND"


def test_incident_type_for_missing_authorization() -> None:
    reason = "No se encontró autorización (AUT) en: /mnt/clientes/A-C/CLIENTE/DOCUMENTACION"
    incident = PayloadValidatorService._incident_type_for_gesdoc_reason(reason)
    assert incident == "CLIENT_AUTHORIZATION_MISSING"


def test_incident_type_for_generic_gesdoc_reason() -> None:
    reason = "Requiere autorización GESDOC"
    incident = PayloadValidatorService._incident_type_for_gesdoc_reason(reason)
    assert incident == "REQUIRES_GESDOC"

