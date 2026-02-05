
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from core.client_documentation import client_identity_from_payload, ClientIdentity

def test_madrid_payload_identity():
    # Mock Madrid payload with the new standard keys
    payload = {
        "notif_name": "JUAN",
        "notif_surname1": "PEREZ",
        "notif_surname2": "GARCIA",
        "notif_razon_social": "",
        "sujeto_recurso": "1234ABC",
        "idRecurso": 12345
    }
    
    print("Testing Madrid payload (FISICA)...")
    try:
        identity = client_identity_from_payload(payload)
        print(f"Success: {identity}")
        assert identity.nombre == "JUAN"
        assert identity.apellido1 == "PEREZ"
        assert identity.apellido2 == "GARCIA"
        assert identity.is_company is False
    except Exception as e:
        print(f"Failed: {e}")
        return False

    payload_juridica = {
        "notif_name": "",
        "notif_surname1": "",
        "notif_surname2": "",
        "notif_razon_social": "EMPRESA SL",
        "sujeto_recurso": "B12345678",
    }
    
    print("\nTesting Madrid payload (JURIDICA)...")
    try:
        identity = client_identity_from_payload(payload_juridica)
        print(f"Success: {identity}")
        assert identity.empresa == "EMPRESA SL"
        assert identity.is_company is True
    except Exception as e:
        print(f"Failed: {e}")
        return False
        
    return True

if __name__ == "__main__":
    if test_madrid_payload_identity():
        print("\nALL TESTS PASSED")
        sys.exit(0)
    else:
        print("\nTESTS FAILED")
        sys.exit(1)
