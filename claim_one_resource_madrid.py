#!/usr/bin/env python
"""
claim_one_resource_madrid.py - Reclama UN solo recurso de MADRID y lo encola para el worker.

Este script está adaptado específicamente para el organismo de Madrid:
1. Hace login en Xvia
2. Busca UN recurso libre (Estado=0) en los organismos de Madrid
3. Extrae datos detallados de notificación desde SQL Server
4. Incluye datos hardcodeados del representante
5. Lo asigna haciendo POST a /AsignarA
6. Lo encola en tramite_queue con el payload enriquecido
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

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

load_dotenv()

XVIA_EMAIL = os.getenv("XVIA_EMAIL")
XVIA_PASSWORD = os.getenv("XVIA_PASSWORD")
ASIGNAR_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/AsignarA"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [CLAIM-MADRID] - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/claim_madrid.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("claim_madrid")

# =============================================================================
# CONSULTAS SQL SERVER
# =============================================================================

# Consulta adaptada para Madrid con todos los campos de clientes
SQL_FETCH_RECURSOS_MADRID = """
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
    e.matricula,
    rs.cif,
    -- Datos detallados del cliente para NOTIFICACIÓN
    c.nif AS cliente_nif,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    c.Nombrefiscal AS cliente_razon_social,
    c.provincia AS cliente_provincia,
    c.poblacion AS cliente_municipio,
    c.calle AS cliente_domicilio,
    c.escalera AS cliente_escalera,
    c.piso AS cliente_planta,
    c.puerta AS cliente_puerta,
    c.Cpostal AS cliente_cp,
    c.email AS cliente_email,
    c.telefono1 AS cliente_tel1,
    c.telefono2 AS cliente_tel2,
    c.movil AS cliente_movil,
    -- Adjuntos (agrupados luego)
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id
WHERE (rs.Organisme like '%SUBDIRECCION GNAL GESTION MULTAS DE MADRID%' 
       OR rs.Organisme like '%MADRID, SUBDIRECCION GENERAL DE GESTION DE MULTAS%')
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
    """Construye el connection string para SQL Server."""
    driver = os.getenv("SQLSERVER_DRIVER", "{ODBC Driver 17 for SQL Server}")
    server = os.getenv("SQLSERVER_SERVER")
    database = os.getenv("SQLSERVER_DATABASE")
    username = os.getenv("SQLSERVER_USERNAME")
    password = os.getenv("SQLSERVER_PASSWORD")
    return f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}"

def _clean_str(value) -> str:
    return str(value).strip() if value is not None else ""

def _convert_value(v):
    """Convierte valores SQL Server a tipos JSON serializables."""
    if isinstance(v, Decimal):
        return float(v)
    if v is None:
        return None
    return v

def _inferir_tipo_via(domicilio: str) -> str:
    """Intenta extraer el tipo de vía (CL, AV, RONDA, etc.) de la calle."""
    if not domicilio:
        return "CALLE"
    parts = domicilio.split()
    if not parts:
        return "CALLE"
    first = parts[0].upper()
    # Mapeo básico de abreviaturas/nombres a tipos conocidos por el organismo
    via_map = {
        "CL": "CALLE",
        "CALLE": "CALLE",
        "AV": "AVENIDA",
        "AVDA": "AVENIDA",
        "AVENIDA": "AVENIDA",
        "RD": "RONDA",
        "RONDA": "RONDA",
        "PS": "PASEO",
        "PASEO": "PASEO",
        "CTRA": "CARRETERA",
        "CORTES": "PLAZA", # Ejemplo específico si se detecta
        "PL": "PLAZA",
        "PLAZA": "PLAZA"
    }
    return via_map.get(first, "CALLE")

def _detectar_tipo_documento(doc: str) -> str:
    """Detecta si es NIF, NIE o CIF."""
    if not doc:
        return "NIF"
    doc = doc.strip().upper()
    if re.match(r'^[ABCDEFGHKLMNPQSV]', doc):
        return "CIF"
    if re.match(r'^[XYZ]', doc):
        return "NIE"
    return "NIF"

def _seleccionar_telefonos(tel1, tel2, movil) -> tuple:
    """Selecciona un móvil y un teléfono de los campos disponibles."""
    all_nums = [_clean_str(tel1), _clean_str(tel2), _clean_str(movil)]
    final_movil = ""
    final_tel = ""
    
    # Buscar el primer móvil (empieza por 6 o 7)
    for n in all_nums:
        clean_n = re.sub(r'\D', '', n)
        if clean_n.startswith('6') or clean_n.startswith('7'):
            if not final_movil:
                final_movil = clean_n
            elif not final_tel:
                final_tel = clean_n
        elif clean_n:
            if not final_tel:
                final_tel = clean_n
                
    return final_movil[:9], final_tel[:9]

# =============================================================================
# LÓGICA PRINCIPAL
# =============================================================================

def fetch_one_resource_madrid(conn_str: str, authenticated_user: str = None) -> dict:
    """Busca UN recurso disponible de Madrid."""
    logger.info("🔍 Buscando recursos de MADRID disponibles...")
    
    # Formatos de Madrid: 935/564097331.0 o 719421608.4
    regex_madrid = [
        re.compile(r'^\d{3}/\d{9}\.\d$'),
        re.compile(r'^\d{9}\.\d$')
    ]
    
    # Madrid suele ser TExp 2 o 3, pero filtramos por organismos
    texp_values = [2, 3]
    texp_placeholders = ",".join(["?"] * len(texp_values))
    query = SQL_FETCH_RECURSOS_MADRID.format(texp_list=texp_placeholders)
    
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
            
            # Validar formatos Madrid
            expediente_valido = any(reg.match(expediente) for reg in regex_madrid)
            
            if expediente_valido:
                if estado == 1 and (not authenticated_user or usuario != authenticated_user):
                    continue
                    
                status_str = "LIBRE" if estado == 0 else f"EN PROCESO ({usuario})"
                logger.info(f"✓ Recurso MADRID encontrado ({status_str}): {id_recurso} - {expediente}")
                return recurso
                
        logger.warning("No se encontraron recursos de Madrid válidos")
        return None
        
    except Exception as e:
        logger.error(f"Error consultando SQL Server: {e}")
        return None

async def claim_resource(session: aiohttp.ClientSession, id_recurso: int, dry_run: bool = False) -> bool:
    """Reclama el recurso en Xvia."""
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

def build_madrid_payload(recurso: dict) -> dict:
    """Construye el payload enriquecido para Madrid."""
    expediente = _clean_str(recurso.get("Expedient"))
    nif = _clean_str(recurso.get("cliente_nif"))
    
    # Notificación (Dinámico desde DB)
    movil, tel = _seleccionar_telefonos(
        recurso.get("cliente_tel1"), 
        recurso.get("cliente_tel2"), 
        recurso.get("cliente_movil")
    )
    
    domicilio = _clean_str(recurso.get("cliente_domicilio")).upper()
    
    notificacion = {
        "tipo_documento": _detectar_tipo_documento(nif),
        "numero_documento": nif,
        "nombre": _clean_str(recurso.get("cliente_nombre")).upper(),
        "apellido1": _clean_str(recurso.get("cliente_apellido1")).upper(),
        "apellido2": _clean_str(recurso.get("cliente_apellido2")).upper(),
        "razon_social": _clean_str(recurso.get("cliente_razon_social")).upper(),
        "provincia": _clean_str(recurso.get("cliente_provincia")).upper(),
        "municipio": _clean_str(recurso.get("cliente_municipio")).upper(),
        "tipo_via": _inferir_tipo_via(domicilio),
        "domicilio": domicilio,
        "escalera": _clean_str(recurso.get("cliente_escalera")).upper(),
        "planta": _clean_str(recurso.get("cliente_planta")).upper(),
        "puerta": _clean_str(recurso.get("cliente_puerta")).upper(),
        "cp": _clean_str(recurso.get("cliente_cp")),
        "email": _clean_str(recurso.get("cliente_email")),
        "movil": movil,
        "telefono": tel
    }
    
    # Representante (Fijo)
    representante = {
        "municipio": "BARCELONA",
        "tipo_via": "RONDA",
        "domicilio": "GENERAL MITRE, DEL",
        "tipo_numeracion": "NUMERO",
        "numero": "169",
        "cp": "08022",
        "email": "info@xvia-serviciosjuridicos.com",
        "movil": "722761154"
    }

    return {
        "idRecurso": _convert_value(recurso["idRecurso"]),
        "idExp": _convert_value(recurso["idExp"]),
        "expediente": expediente,
        "numclient": _convert_value(recurso["numclient"]),
        "sujeto_recurso": _clean_str(recurso.get("SujetoRecurso")),
        "fase_procedimiento": _clean_str(recurso.get("FaseProcedimiento")),
        "matricula": _clean_str(recurso.get("matricula")),
        "notificacion": notificacion,
        "representante": representante,
        "source": "claim_one_resource_madrid",
        "claimed_at": datetime.now().isoformat()
    }

async def main():
    parser = argparse.ArgumentParser(description="Reclama UN recurso de MADRID")
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
        logger.info(f"✓ Usuario: {user}")
        
        conn_str = build_sqlserver_connection_string()
        recurso = fetch_one_resource_madrid(conn_str, user)
        if not recurso: return 0
        
        id_rec = recurso["idRecurso"]
        if recurso.get("Estado") == 0:
            if not await claim_resource(session, id_rec, args.dry_run):
                logger.error("❌ Claim falló")
                return 1
            logger.info(f"✅ Recurso {id_rec} reclamado vía POST")
        
        # Encolar en tramite_queue
        payload = build_madrid_payload(recurso)
        db = SQLiteDatabase("db/xaloc_database.db")
        
        if not args.dry_run:
            task_id = db.insert_task("madrid_multas", None, payload)
            logger.info(f"📥 Tarea {task_id} encolada para MADRID")
        else:
            logger.info(f"[DRY-RUN] Payload Madrid: {payload}")
            
    finally:
        await session.close()
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
