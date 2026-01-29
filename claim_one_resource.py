#!/usr/bin/env python
"""
claim_one_resource.py - Reclama UN solo recurso y lo encola para el worker.

Este script:
1. Hace login en Xvia
2. Busca UN recurso libre (Estado=0)
3. Lo asigna haciendo POST a /AsignarA
4. Lo encola en tramite_queue
5. El worker lo procesará normalmente

Uso:
    python claim_one_resource.py [--site-id xaloc_girona] [--dry-run]
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime

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
    format="%(asctime)s - [CLAIM-ONE] - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/claim_one.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("claim_one")


# =============================================================================
# CONSULTAS SQL SERVER
# =============================================================================

SQL_FETCH_ONE_RECURSO = """
SELECT TOP 1
    rs.idRecurso,
    rs.idExp,
    rs.Expedient,
    rs.Organisme,
    rs.TExp,
    rs.Estado,
    rs.numclient,
    rs.SujetoRecurso,
    rs.FaseProcedimiento
FROM Recursos.RecursosExp rs
WHERE rs.Organisme LIKE ?
  AND rs.TExp IN ({texp_list})
  AND rs.Estado = 0
  AND rs.Expedient IS NOT NULL
ORDER BY rs.idRecurso ASC
"""

SQL_VERIFY_CLAIM = """
SELECT TExp, UsuarioAsignado
FROM Recursos.RecursosExp
WHERE idRecurso = ?
"""


# =============================================================================
# FUNCIONES PRINCIPALES
# =============================================================================

def build_sqlserver_connection_string() -> str:
    """Construye el connection string para SQL Server."""
    driver = os.getenv("SQLSERVER_DRIVER", "{ODBC Driver 17 for SQL Server}")
    server = os.getenv("SQLSERVER_SERVER")
    database = os.getenv("SQLSERVER_DATABASE")
    username = os.getenv("SQLSERVER_USERNAME")
    password = os.getenv("SQLSERVER_PASSWORD")
    
    return f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}"


def fetch_one_resource(config: dict, conn_str: str) -> dict:
    """Busca UN recurso disponible."""
    logger.info("🔍 Buscando UN recurso disponible...")
    
    texp_values = [int(x.strip()) for x in config["filtro_texp"].split(",")]
    texp_placeholders = ",".join(["?"] * len(texp_values))
    
    query = SQL_FETCH_ONE_RECURSO.format(texp_list=texp_placeholders)
    
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute(query, [config["query_organisme"]] + texp_values)
        
        columns = [column[0] for column in cursor.description]
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            logger.warning("No se encontraron recursos disponibles")
            return None
        
        record = dict(zip(columns, row))
        expediente = record.get("Expedient", "")
        
        # Validar formato de expediente
        regex = re.compile(config["regex_expediente"])
        if not expediente or not regex.match(expediente):
            conn.close()
            logger.warning(f"Expediente {expediente} no cumple regex")
            return None
        
        conn.close()
        
        logger.info(f"✓ Recurso encontrado:")
        logger.info(f"  ID: {record['idRecurso']}")
        logger.info(f"  Expediente: {record['Expedient']}")
        logger.info(f"  Organismo: {record['Organisme']}")
        logger.info(f"  Fase: {record.get('FaseProcedimiento', 'N/A')}")
        
        return record
        
    except Exception as e:
        logger.error(f"Error consultando SQL Server: {e}")
        return None


async def claim_resource(session: aiohttp.ClientSession, id_recurso: int, dry_run: bool = False) -> bool:
    """Reclama el recurso haciendo POST a /AsignarA."""
    if dry_run:
        logger.info(f"[DRY-RUN] Claim simulado para idRecurso={id_recurso}")
        return True
    
    try:
        # Obtener token CSRF de la página de recursos
        async with session.get(
            "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
        ) as resp:
            html = await resp.text()
            match = re.search(r'name="_token"\s+value="([^"]+)"', html)
            if not match:
                logger.error("No se pudo obtener el token CSRF")
                return False
            csrf_token = match.group(1)
        
        # Preparar datos del formulario
        form_data = {
            "_token": csrf_token,
            "id": str(id_recurso),
            "recursosSel": "0"  # 0 = Recurso actual
        }
        
        logger.info(f"📤 Enviando claim para idRecurso={id_recurso}...")
        
        # Hacer POST
        async with session.post(ASIGNAR_URL, data=form_data) as resp:
            if resp.status not in (200, 302, 303):
                logger.error(f"POST falló con status {resp.status}")
                return False
        
        logger.info("✓ POST exitoso")
        return True
        
    except Exception as e:
        logger.error(f"Error en claim: {e}")
        return False


def verify_claim(id_recurso: int, conn_str: str) -> bool:
    """Verifica que el claim fue exitoso en SQL Server."""
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute(SQL_VERIFY_CLAIM, (id_recurso,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] == 1:  # TExp = 1
            logger.info(f"✅ Claim verificado en SQL Server (TExp=1)")
            return True
        else:
            logger.warning(f"⚠️  Claim no confirmado (TExp={row[0] if row else 'NULL'})")
            return False
    except Exception as e:
        logger.error(f"Error verificando claim: {e}")
        return False


def enqueue_task(db: SQLiteDatabase, site_id: str, recurso: dict, dry_run: bool = False) -> int:
    """Encola la tarea en tramite_queue."""
    payload = {
        "idRecurso": recurso["idRecurso"],
        "idExp": recurso.get("idExp"),
        "expediente": recurso["Expedient"],
        "numclient": recurso.get("numclient"),
        "sujeto_recurso": recurso.get("SujetoRecurso"),
        "fase_procedimiento": recurso.get("FaseProcedimiento"),
        "source": "claim_one_resource",
        "claimed_at": datetime.now().isoformat()
    }
    
    if dry_run:
        logger.info(f"[DRY-RUN] Encolado simulado: {payload['expediente']}")
        return -1
    
    task_id = db.insert_task(site_id, None, payload)
    logger.info(f"📥 Tarea {task_id} encolada: {payload['expediente']}")
    return task_id


# =============================================================================
# MAIN
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Reclama UN recurso y lo encola para el worker"
    )
    parser.add_argument(
        "--site-id",
        default="xaloc_girona",
        help="ID del site"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simular sin hacer cambios reales"
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("🎯 CLAIM ONE RESOURCE - Reclamar UN recurso")
    logger.info("=" * 60)
    logger.info(f"Site ID: {args.site_id}")
    logger.info(f"Dry-run: {args.dry_run}")
    logger.info("")
    
    # Validar credenciales
    if not XVIA_EMAIL or not XVIA_PASSWORD:
        logger.error("XVIA_EMAIL y XVIA_PASSWORD deben estar definidos en .env")
        return 1
    
    # Cargar configuración
    db = SQLiteDatabase("db/xaloc_database.db")
    configs = db.get_active_organismo_configs()
    
    config = None
    for cfg in configs:
        if cfg["site_id"] == args.site_id:
            config = cfg
            break
    
    if not config:
        logger.error(f"No se encontró configuración activa para: {args.site_id}")
        return 1
    
    # Buscar UN recurso
    conn_str = build_sqlserver_connection_string()
    recurso = fetch_one_resource(config, conn_str)
    
    if not recurso:
        logger.warning("No hay recursos disponibles para reclamar")
        return 0
    
    # Hacer login
    logger.info("")
    logger.info("🔐 Autenticando en Xvia...")
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": config["login_url"],
        "Origin": "http://www.xvia-grupoeuropa.net",
        "Connection": "keep-alive",
    }
    
    async with aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar) as session:
        try:
            await create_authenticated_session_in_place(session, XVIA_EMAIL, XVIA_PASSWORD)
            logger.info("✓ Login exitoso")
        except Exception as e:
            logger.error(f"Error en login: {e}")
            return 1
        
        # Reclamar recurso
        logger.info("")
        if not await claim_resource(session, recurso["idRecurso"], args.dry_run):
            logger.error("❌ Claim falló")
            return 1
    
    # Verificar claim en SQL Server
    logger.info("")
    if not args.dry_run:
        if not verify_claim(recurso["idRecurso"], conn_str):
            logger.error("❌ Claim no verificado en SQL Server")
            return 1
    
    # Encolar tarea
    logger.info("")
    task_id = enqueue_task(db, args.site_id, recurso, args.dry_run)
    
    # Resumen
    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ PROCESO COMPLETADO")
    logger.info("=" * 60)
    logger.info(f"Recurso reclamado: {recurso['Expedient']}")
    logger.info(f"ID Recurso: {recurso['idRecurso']}")
    if not args.dry_run:
        logger.info(f"Tarea encolada: ID {task_id}")
        logger.info("")
        logger.info("👉 El worker procesará esta tarea automáticamente")
        logger.info("   y subirá el recurso al organismo correspondiente.")
    logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
