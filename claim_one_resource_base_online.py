#!/usr/bin/env python
"""
claim_one_resource_base_online.py - Reclama UN solo recurso de BASE Online y lo encola para el worker.

Este script está adaptado específicamente para BASE Online:
1. Hace login en Xvia
2. Busca UN recurso libre (Estado=0) en los organismos de BASE
3. Valida el formato del expediente
4. Determina el protocolo (P1, P2, P3) según la fase
5. Extrae y formatea datos para el payload específico de BASE
6. Lo asigna haciendo POST a /AsignarA
7. Lo encola en tramite_queue con el payload enriquecido
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime
from decimal import Decimal

import aiohttp
import pyodbc
from dotenv import load_dotenv

from core.sqlite_db import SQLiteDatabase
from core.xvia_auth import create_authenticated_session_in_place
from core.address_classifier import classify_address_with_ai, classify_address_fallback

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

load_dotenv()

XVIA_EMAIL = os.getenv("XVIA_EMAIL")
XVIA_PASSWORD = os.getenv("XVIA_PASSWORD")
ASIGNAR_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/AsignarA"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [CLAIM-BASE] - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/claim_base_online.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("claim_base_online")

# =============================================================================
# CONSULTAS SQL SERVER
# =============================================================================

SQL_FETCH_RECURSOS_BASE = """
SELECT 
    rs.idRecurso,
    rs.idExp,
    rs.Expedient,
    rs.Organisme,
    rs.TExp,
    rs.Estado,
    rs.numclient,
    rs.SujetoRecurso,
    rs.FaseProcedimiento,
    rs.UsuarioAsignado,
    rs.FAlta,
    e.matricula,
    rs.cif,
    -- Datos detallados del cliente
    c.nif AS cliente_nif,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    c.Nombrefiscal AS cliente_razon_social,
    c.provincia AS cliente_provincia,
    c.poblacion AS cliente_municipio,
    c.calle AS cliente_domicilio,
    c.numero AS cliente_numero,
    c.escalera AS cliente_escalera,
    c.piso AS cliente_planta,
    c.puerta AS cliente_puerta,
    c.Cpostal AS cliente_cp,
    c.email AS cliente_email,
    c.telefono1 AS cliente_tel1,
    c.telefono2 AS cliente_tel2,
    c.movil AS cliente_movil,
    -- Adjuntos
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id
WHERE rs.Organisme LIKE '%BASE%'
  AND rs.TExp IN ({texp_list})
  AND rs.Estado IN (0, 1)
  AND rs.Expedient IS NOT NULL
ORDER BY rs.Estado ASC, rs.idRecurso ASC
"""

SQL_VERIFY_CLAIM = """
SELECT TExp, Estado, UsuarioAsignado
FROM Recursos.RecursosExp
WHERE idRecurso = ?
"""

# =============================================================================
# LOGICA DE VALIDACIÓN Y PARSEO
# =============================================================================

def valida_expediente_base(expediente: str) -> bool:
    """
    Valida si el expediente cumple con uno de los tres formatos permitidos.
    - GIM (Tipo A): NNNNN-NNNN/NNNNN-GIM
    - GIM (Tipo B): NN-NNN-NNN-NNNN-NN-NNNNNNN
    - EXE / ECC: N-NNNN/NNNNN-EXE (o ECC)
    """
    exp = expediente.strip().upper()
    
    # GIM (Tipo A): 43185-2025/40818-GIM
    if re.match(r'^\d{5}-\d{4}/\d{5}-GIM$', exp):
        return True
    
    # GIM (Tipo B): 43-558-779-2018-11-0005780
    if re.match(r'^\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{7}$', exp):
        return True
    
    # EXE / ECC: 1-2025/27474-EXE o 1-2025/27474-ECC
    if re.match(r'^\d-\d{4}/\d{5}-(EXE|ECC)$', exp):
        return True
        
    return False

def determina_protocolo(fase: str) -> str:
    """Determina si es P1, P2 o P3 según la fase del procedimiento."""
    f = str(fase).upper()
    if any(tag in f for tag in ["IDENTIFICACION", "IDENTIFICACIÓ"]):
        return "P1"
    if any(tag in f for tag in ["ALEGACION", "ALEGACIÓ", "ALEGACIONES"]):
        return "P2"
    if any(tag in f for tag in ["REPOSICION", "REPOSICIÓ", "RECURSO"]):
        return "P3"
    
    # Fallback conservador
    return "P2"

def parse_expediente_base(expediente: str) -> dict:
    """Extrae id_ens, any y num del expediente."""
    exp = expediente.strip().upper()
    
    # Tipo A: 43185-2025/40818-GIM
    m_a = re.match(r'^(?P<id_ens>\d{5})-(?P<any>\d{4})/(?P<num>\d{5})-GIM$', exp)
    if m_a:
        return {
            "expediente_id_ens": m_a.group("id_ens"),
            "expediente_any": m_a.group("any"),
            "expediente_num": m_a.group("num"),
            "num_butlleti": ""
        }
    
    # Tipo EXE/ECC: 1-2025/27474-EXE
    m_exe = re.match(r'^(?P<id_ens>\d)-(?P<any>\d{4})/(?P<num>\d{5})-(EXE|ECC)$', exp)
    if m_exe:
        return {
            "expediente_id_ens": m_exe.group("id_ens"),
            "expediente_any": m_exe.group("any"),
            "expediente_num": m_exe.group("num"),
            "num_butlleti": ""
        }

    # Tipo B: 43-558-779-2018-11-0005780
    # No está claro cómo mapear id_ens, any, num aquí, pero pondremos el expediente completo en num_butlleti o similar
    return {
        "expediente_id_ens": "",
        "expediente_any": "",
        "expediente_num": "",
        "num_butlleti": exp
    }

def formatear_fecha(fecha_dt) -> str:
    """Convierte datetime de SQL a dd/mm/yyyy."""
    if not fecha_dt: return ""
    try:
        if isinstance(fecha_dt, str):
            # Parsear string: 2018-12-11 12:50:32.863
            dt = datetime.strptime(fecha_dt.split('.')[0], "%Y-%m-%d %H:%M:%S")
        else:
            dt = fecha_dt
        return dt.strftime("%d/%m/%Y")
    except Exception as e:
        logger.warning(f"Error parseando fecha {fecha_dt}: {e}")
        return ""

def seleccionar_telefono(tel1, tel2, movil) -> str:
    """Selecciona un teléfono no nulo."""
    for n in [movil, tel1, tel2]:
        if n and str(n).strip() and str(n).strip().lower() != "null":
            return str(n).strip()
    return ""

# =============================================================================
# FUNCIONES DE APOYO
# =============================================================================

async def get_authenticated_username(session: aiohttp.ClientSession) -> str:
    """Obtiene el nombre del usuario autenticado."""
    try:
        async with session.get("http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/home") as resp:
            html = await resp.text()
            match = re.search(r'<i class="fa fa-user-circle"[^>]*></i>\s*([^<]+)', html)
            if match:
                return match.group(1).strip()
            return None
    except Exception as e:
        logger.error(f"Error obteniendo nombre de usuario: {e}")
        return None

def build_sqlserver_connection_string() -> str:
    driver = os.getenv("SQLSERVER_DRIVER", "{ODBC Driver 17 for SQL Server}")
    server = os.getenv("SQLSERVER_SERVER")
    database = os.getenv("SQLSERVER_DATABASE")
    username = os.getenv("SQLSERVER_USERNAME")
    password = os.getenv("SQLSERVER_PASSWORD")
    return f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}"

def _clean_str(value) -> str:
    return str(value).strip() if value is not None else ""

def _convert_value(v):
    if isinstance(v, Decimal):
        return float(v)
    if v is None:
        return None
    return v

def _load_motivos_config() -> dict:
    try:
        import json
        from pathlib import Path
        path = Path("config_motivos.json")
        if not path.exists(): return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _normalize_text(text: str) -> str:
    if not text: return ""
    import unicodedata
    text = str(text).strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

def get_motivos_base(fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str]:
    config = _load_motivos_config()
    fase_norm = _normalize_text(fase_raw)
    selected = None
    for key, value in (config or {}).items():
        if _normalize_text(key) in fase_norm:
            selected = value
            break
    
    exp = _clean_str(expediente)
    sujeto_txt = _clean_str(sujeto)

    if not selected:
        return f"Escrito relativo al exp {exp}", f"Se tenga por presentado el escrito. Exp {exp}"
    
    expone = _clean_str(selected.get("expone")).replace("{expediente}", exp).replace("{sujeto_recurso}", sujeto_txt)
    solicita = _clean_str(selected.get("solicita")).replace("{expediente}", exp).replace("{sujeto_recurso}", sujeto_txt)
    return expone, solicita

# =============================================================================
# LÓGICA PRINCIPAL
# =============================================================================

def fetch_one_resource_base(conn_str: str, authenticated_user: str = None) -> dict:
    logger.info("🔍 Buscando recursos de BASE disponibles...")
    
    texp_values = [2, 3]
    texp_placeholders = ",".join(["?"] * len(texp_values))
    query = SQL_FETCH_RECURSOS_BASE.format(texp_list=texp_placeholders)
    
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute(query, texp_values)
        
        columns = [column[0] for column in cursor.description]
        recursos_map = {}
        
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            id_recurso = record.get("idRecurso")
            if not id_recurso: continue
            
            if id_recurso not in recursos_map:
                recursos_map[id_recurso] = {**record, "adjuntos": []}
            
            adj_id = record.get("adjunto_id")
            if adj_id:
                recursos_map[id_recurso]["adjuntos"].append({
                    "id": adj_id, "filename": record.get("adjunto_filename")
                })
        
        conn.close()
        
        for id_recurso, recurso in recursos_map.items():
            expediente = _clean_str(recurso.get("Expedient"))
            estado = recurso.get("Estado", 0)
            usuario = str(recurso.get("UsuarioAsignado", "")).strip()
            
            if valida_expediente_base(expediente):
                if estado == 1 and (not authenticated_user or usuario != authenticated_user):
                    continue
                return recurso
                
        return None
    except Exception as e:
        logger.error(f"Error consultando SQL Server: {e}")
        return None

async def build_base_online_payload(recurso: dict) -> dict:
    """Construye el payload para BASE Online según el protocolo."""
    fase_raw = _clean_str(recurso.get("FaseProcedimiento"))
    protocolo = determina_protocolo(fase_raw)
    expediente_raw = _clean_str(recurso.get("Expedient"))
    
    # Datos comunes
    exp_parts = parse_expediente_base(expediente_raw)
    tel = seleccionar_telefono(recurso.get("cliente_tel1"), recurso.get("cliente_tel2"), recurso.get("cliente_movil"))
    nif = _clean_str(recurso.get("cif") or recurso.get("cliente_nif"))
    
    # Dirección (Reutilizamos lógica de Madrid)
    domicilio_raw = _clean_str(recurso.get("cliente_domicilio"))
    poblacion = _clean_str(recurso.get("cliente_municipio"))
    numero_db = _clean_str(recurso.get("cliente_numero"))
    cp = _clean_str(recurso.get("cliente_cp"))
    provincia = _clean_str(recurso.get("cliente_provincia")) or poblacion
    
    use_ai = os.getenv("GROQ_API_KEY") is not None
    notif_data = {}
    if use_ai:
        try:
            cl = await classify_address_with_ai(direccion_raw=domicilio_raw, poblacion=poblacion, numero=numero_db)
            notif_data = {
                "address_sigla": cl["tipo_via"],
                "address_street": cl["calle"].upper(),
                "address_number": cl["numero"] or numero_db,
                "address_zip": cp,
                "address_city": poblacion.upper(),
                "address_province": provincia.upper(),
                "address_country": "ESPAÑA"
            }
        except Exception: use_ai = False
    
    if not use_ai:
        cl = classify_address_fallback(domicilio_raw)
        notif_data = {
            "address_sigla": cl["tipo_via"],
            "address_street": cl["calle"].upper(),
            "address_number": cl["numero"] or numero_db,
            "address_zip": cp,
            "address_city": poblacion.upper(),
            "address_province": provincia.upper(),
            "address_country": "ESPAÑA"
        }

    expone, solicita = get_motivos_base(fase_raw, expediente_raw, recurso.get("SujetoRecurso"))

    payload = {
        "idRecurso": _convert_value(recurso["idRecurso"]),
        "idExp": _convert_value(recurso["idExp"]),
        "protocol": protocolo,
        "user_phone": tel,
        "user_email": "info@xvia-serviciosjuridicos.com",
        "plate_number": _clean_str(recurso.get("matricula")),
        "data_denuncia": formatear_fecha(recurso.get("FAlta")),
        "nif": nif,
        "name": _clean_str(recurso.get("SujetoRecurso")).upper(),
        **notif_data,
        **exp_parts,
        "source": "claim_one_resource_base_online",
        "claimed_at": datetime.now().isoformat()
    }

    if protocolo == "P1":
        payload["llicencia_conduccio"] = "" # Pendiente de definición
    
    if protocolo == "P2":
        payload["exposo"] = expone
        payload["solicito"] = solicita
        
    if protocolo == "P3":
        payload["p3_tipus_objecte"] = "IVTM"
        payload["p3_dades_especifiques"] = payload["plate_number"]
        payload["p3_tipus_solicitud_value"] = "1"
        payload["p3_exposo"] = expone
        payload["p3_solicito"] = solicita

    return payload

async def claim_resource(session: aiohttp.ClientSession, id_recurso: int, dry_run: bool = False) -> bool:
    if dry_run: return True
    try:
        async with session.get("http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos") as resp:
            html = await resp.text()
            match = re.search(r'name="_token"\s+value="([^"]+)"', html)
            if not match: return False
            csrf_token = match.group(1)
        
        form_data = {"_token": csrf_token, "id": str(id_recurso), "recursosSel": "0"}
        async with session.post(ASIGNAR_URL, data=form_data) as resp:
            return resp.status in (200, 302, 303)
    except Exception as e:
        logger.error(f"Error en claim: {e}")
        return False

async def main():
    parser = argparse.ArgumentParser(description="Reclama UN recurso de BASE Online")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin cambios")
    args = parser.parse_args()
    
    if not XVIA_EMAIL or not XVIA_PASSWORD:
        logger.error("Faltan credenciales en .env")
        return 1

    logger.info("🔐 Autenticando en Xvia...")
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    try:
        await create_authenticated_session_in_place(session, XVIA_EMAIL, XVIA_PASSWORD)
        user = await get_authenticated_username(session)
        
        conn_str = build_sqlserver_connection_string()
        recurso = fetch_one_resource_base(conn_str, user)
        if not recurso:
            logger.warning("No hay recursos de BASE disponibles.")
            return 0
        
        id_rec = recurso["idRecurso"]
        if recurso.get("Estado") == 0:
            if not await claim_resource(session, id_rec, args.dry_run):
                logger.error("❌ Claim falló")
                return 1
            logger.info(f"✅ Recurso {id_rec} reclamado.")

        payload = await build_base_online_payload(recurso)
        if not args.dry_run:
            db = SQLiteDatabase("db/xaloc_database.db")
            task_id = db.insert_task("base_online", payload.get("protocol"), payload)
            logger.info(f"📥 Tarea {task_id} encolada para BASE Online (Protocolo {payload.get('protocol')})")
        else:
            import json
            logger.info(f"[DRY-RUN] Payload Base Online:\n{json.dumps(payload, indent=2)}")
            
    finally:
        await session.close()
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
