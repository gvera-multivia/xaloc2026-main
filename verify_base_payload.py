import asyncio
import json
from datetime import datetime

# Importar funciones desde el script principal (mocked here for simplicity in the test script)
def parse_expediente_base(expediente: str) -> dict:
    exp = expediente.strip().upper()
    m_a = re.match(r'^(?P<id_ens>\d{5})-(?P<any>\d{4})/(?P<num>\d{5})-GIM$', exp)
    if m_a:
        return {"expediente_id_ens": m_a.group("id_ens"), "expediente_any": m_a.group("any"), "expediente_num": m_a.group("num"), "num_butlleti": ""}
    return {"expediente_id_ens": "", "expediente_any": "", "expediente_num": "", "num_butlleti": exp}

import re
import os

# Mocks para poder probar fuera del entorno
os.environ["GROQ_API_KEY"] = "mock_key"

async def build_base_online_payload(recurso: dict) -> dict:
    # Copia simplificada de la lógica del script principal para testear el output
    fase_raw = recurso.get("FaseProcedimiento", "").upper()
    if "IDENTIFICACION" in fase_raw: protocol = "P1"
    elif "ALEGACION" in fase_raw: protocol = "P2"
    else: protocol = "P3"
    
    exp_raw = recurso.get("Expedient", "")
    exp_parts = parse_expediente_base(exp_raw)
    
    payload = {
        "idRecurso": recurso["idRecurso"],
        "protocol": protocol,
        "user_phone": "600000000",
        "user_email": "info@xvia-serviciosjuridicos.com",
        "plate_number": recurso.get("matricula"),
        "data_denuncia": "01/01/2024",
        "nif": recurso.get("cliente_nif"),
        "name": recurso.get("SujetoRecurso").upper(),
        "address_sigla": "CL",
        "address_street": "BALMES",
        "address_number": "100",
        "address_zip": "08001",
        "address_city": "BARCELONA",
        "address_province": "BARCELONA",
        "address_country": "ESPAÑA",
        **exp_parts
    }
    
    if protocol == "P1": payload["llicencia_conduccio"] = ""
    if protocol == "P2":
        payload["exposo"] = "Expongo..."
        payload["solicito"] = "Solicito..."
    if protocol == "P3":
        payload["p3_tipus_objecte"] = "IVTM"
        payload["p3_dades_especifiques"] = recurso.get("matricula")
        payload["p3_tipus_solicitud_value"] = "1"
        payload["p3_exposo"] = "P3 Expongo..."
        payload["p3_solicito"] = "P3 Solicito..."
        
    return payload

recursos_test = [
    {"idRecurso": 101, "Expedient": "43185-2025/40818-GIM", "SujetoRecurso": "JUAN PEREZ", "cliente_nif": "12345678Z", "matricula": "1234AAA", "FaseProcedimiento": "IDENTIFICACION"},
    {"idRecurso": 102, "Expedient": "43-558-779-2018-11-0005780", "SujetoRecurso": "EMPRESA SL", "cliente_nif": "B12345678", "matricula": "5678BBB", "FaseProcedimiento": "ALEGACIONES"},
    {"idRecurso": 103, "Expedient": "1-2025/27474-EXE", "SujetoRecurso": "MARIA LOPEZ", "cliente_nif": "87654321X", "matricula": "9012CCC", "FaseProcedimiento": "RECURSO REPOSICION"}
]

async def run_test():
    for r in recursos_test:
        p = await build_base_online_payload(r)
        print(f"\n--- Resource {r['idRecurso']} ({p['protocol']}) ---")
        print(json.dumps(p, indent=2))

asyncio.run(run_test())
