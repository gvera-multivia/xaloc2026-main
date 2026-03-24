import os
import sys

sys.path.append(os.getcwd())

from core.client_documentation import client_identity_from_payload
from core.client_paths import ClientIdentity, get_client_folder_name


def test_client_identity_allows_missing_apellido2_from_payload() -> None:
    payload = {
        "cliente_nombre": "JOAN",
        "cliente_apellido1": "PUJOL",
        "cliente_apellido2": "",
    }
    identity = client_identity_from_payload(payload)
    assert identity.is_company is False
    assert identity.nombre == "JOAN"
    assert identity.apellido1 == "PUJOL"
    assert identity.apellido2 == ""


def test_client_folder_name_allows_missing_apellido2() -> None:
    identity = ClientIdentity(
        is_company=False,
        sujeto_recurso=None,
        nombre="JOAN",
        apellido1="PUJOL",
        apellido2=None,
    )
    folder = get_client_folder_name(identity)
    assert folder == "JOAN PUJOL"


def test_client_identity_uses_tipodecliente_company_with_nombrefiscal() -> None:
    payload = {
        "tipodecliente": 2,
        "Nombrefiscal": "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL",
    }
    identity = client_identity_from_payload(payload)
    assert identity.is_company is True
    assert identity.empresa == "EDIFRED EMPORDANESA DISSENY E INSTAL LACIONS SL"


def test_client_identity_falls_back_when_mandatario_juridica_missing_razon_social() -> None:
    payload = {
        "mandatario": {"tipo_persona": "JURIDICA", "razon_social": ""},
        "cliente_tipo": 2,
        "cliente_razon_social": "ACME SL",
    }
    identity = client_identity_from_payload(payload)
    assert identity.is_company is True
    assert identity.empresa == "ACME SL"


def test_client_folder_name_ignores_degraded_sujeto_for_person() -> None:
    identity = ClientIdentity(
        is_company=False,
        sujeto_recurso="ELIAS MU?OZ ORTIZ",
        nombre="ELIAS",
        apellido1="MUÑOZ",
        apellido2="ORTIZ",
    )
    folder = get_client_folder_name(identity)
    assert folder == "ELIAS MUÑOZ ORTIZ"


def test_client_folder_name_ignores_degraded_sujeto_for_company() -> None:
    identity = ClientIdentity(
        is_company=True,
        sujeto_recurso="EMPRESA ?LFA SL",
        empresa="EMPRESA ALFA SL",
    )
    folder = get_client_folder_name(identity)
    assert folder == "EMPRESA ALFA SL"
