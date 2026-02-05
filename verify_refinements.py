
import sys
import os
import asyncio
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.getcwd())

# Mocking parts of claim_one_resource_madrid to test logic without network/db
import claim_one_resource_madrid

def test_job_filtering():
    print("Testing job filtering logic...")
    
    recursos = [
        {"idRecurso": 1, "Expedient": "123/123456789.0", "FaseProcedimiento": "Denuncia", "Estado": 0},
        {"idRecurso": 2, "Expedient": "123/123456789.0", "FaseProcedimiento": "Reclamacion de multa", "Estado": 0},
        {"idRecurso": 3, "Expedient": "123/123456789.0", "FaseProcedimiento": "Embargo de bienes", "Estado": 0},
        {"idRecurso": 4, "Expedient": "123/123456789.0", "FaseProcedimiento": "Apremio", "Estado": 0},
        {"idRecurso": 5, "Expedient": "123/123456789.0", "FaseProcedimiento": "Sancion", "Estado": 0},
    ]

    regex_madrid = [claim_one_resource_madrid.re.compile(r'^\d{3}/\d{9}\.\d$')]
    
    results = []
    for rec in recursos:
        expediente = rec["Expedient"]
        fase_norm = claim_one_resource_madrid._normalize_text(rec["FaseProcedimiento"])
        es_fase_negra = any(x in fase_norm for x in ["reclamacion", "embargo", "apremio"])
        
        valido = any(reg.match(expediente) for reg in regex_madrid)
        if valido and not es_fase_negra:
            results.append(rec["idRecurso"])
            print(f"  [OK] accepted: {rec['FaseProcedimiento']}")
        elif es_fase_negra:
            print(f"  [SKIP] blacklisted: {rec['FaseProcedimiento']}")
        else:
            print(f"  [SKIP] invalid format: {rec['Expedient']}")

    assert 1 in results
    assert 5 in results
    assert 2 not in results
    assert 3 not in results
    assert 4 not in results
    print("[SUCCESS] Filtering logic PASSED")

async def test_payload_construction():
    print("\nTesting payload construction (phone/mobile)...")
    
    recurso = {
        "idRecurso": 12345,
        "idExp": 67890,
        "Expedient": "911/123456789.0",
        "numclient": 999,
        "SujetoRecurso": "TEST SUJETO",
        "FaseProcedimiento": "Denuncia",
        "matricula": "1234BBB",
        "cliente_email": "client@test.com",
        "cliente_tel1": "931234567",
        "cliente_tel2": "931234568",
        "cliente_movil": "600123456",
        "cliente_nombre": "JUAN",
        "cliente_apellido1": "PEREZ",
        "cliente_apellido2": "GARCIA",
        "cliente_razon_social": "",
        "cliente_provincia": "MADRID",
        "cliente_municipio": "MADRID",
        "cliente_domicilio": "CALLE MAYOR 1",
        "cliente_numero": "1",
        "cliente_cp": "28001",
    }
    
    # Mock OS env for IA
    os.environ["GROQ_API_KEY"] = "fake" 
    
    payload = await claim_one_resource_madrid.build_madrid_payload(recurso)
    
    print(f"  user_phone: {payload['user_phone']}")
    print(f"  notif_telefono: {payload['notif_telefono']}")
    print(f"  notif_movil: '{payload['notif_movil']}'")
    print(f"  inter_telefono: {payload['inter_telefono']}")
    print(f"  rep_telefono: {payload['rep_telefono']}")
    print(f"  rep_movil: '{payload['rep_movil']}'")
    print(f"  representative_phone (in dict): {payload['representative_phone']}")

    assert payload["user_phone"] == "932531411"
    assert payload["notif_telefono"] == "932531411"
    assert payload["notif_movil"] == ""
    assert payload["inter_telefono"] == "932531411"
    assert payload["rep_telefono"] == "932531411"
    assert payload["rep_movil"] == ""
    assert payload["representative_phone"] == "932531411"
    
    print("[SUCCESS] Payload construction PASSED")

if __name__ == "__main__":
    test_job_filtering()
    asyncio.run(test_payload_construction())
    print("\nALL VERIFICATIONS PASSED")
