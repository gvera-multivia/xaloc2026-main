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
