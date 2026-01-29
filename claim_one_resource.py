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

SQL_FETCH_RECURSOS = """
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
    rs.UsuarioAsignado
FROM Recursos.RecursosExp rs
WHERE rs.Organisme LIKE ?
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
# FUNCIONES DE AUTENTICACIÓN
# =============================================================================

async def get_authenticated_username(session: aiohttp.ClientSession) -> str:
    """
    Obtiene el nombre del usuario autenticado desde la página de Xvia.
    Busca el patrón: <i class="fa fa-user-circle"...></i> Guillem Vera
    """
    try:
        async with session.get("http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/home") as resp:
            html = await resp.text()
            # Buscar el nombre en el dropdown del usuario
            match = re.search(r'<i class="fa fa-user-circle"[^>]*></i>\s*([^<]+)', html)
            if match:
                username = match.group(1).strip()
                return username
            return None
    except Exception as e:
        logger.error(f"Error obteniendo nombre de usuario: {e}")
        return None


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


def fetch_one_resource(config: dict, conn_str: str, authenticated_user: str = None) -> dict:
    """Busca UN recurso disponible que cumpla el regex."""
    logger.info("🔍 Buscando recursos disponibles...")
    
    texp_values = [int(x.strip()) for x in config["filtro_texp"].split(",")]
    texp_placeholders = ",".join(["?"] * len(texp_values))
    
    query = SQL_FETCH_RECURSOS.format(texp_list=texp_placeholders)
    
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute(query, [config["query_organisme"]] + texp_values)
        
        columns = [column[0] for column in cursor.description]
        regex = re.compile(config["regex_expediente"])
        
        # Iterar sobre TODOS los recursos hasta encontrar uno válido
        valid_count = 0
        invalid_count = 0
        
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            expediente_raw = record.get("Expedient", "")
            expediente = expediente_raw.strip() if expediente_raw else ""
            estado = record.get("Estado", 0)
            usuario = str(record.get("UsuarioAsignado", "")).strip()
            
            # Validar formato de expediente
            if expediente and regex.match(expediente):
                # Si está en Estado 1, verificar que esté asignado al usuario actual
                if estado == 1:
                    if not authenticated_user or usuario != authenticated_user:
                        logger.debug(f"  Descartado: '{expediente}' (Asignado a '{usuario}', no a '{authenticated_user}')")
                        invalid_count += 1
                        continue
                
                # ¡Encontramos uno válido!
                conn.close()
                
                if estado == 0:
                    status_str = "LIBRE"
                else:
                    status_str = f"EN PROCESO (Asignado a ti: {usuario})"
                
                logger.info(f"✓ Recurso válido encontrado ({status_str}):")
                logger.info(f"  ID: {record['idRecurso']}")
                logger.info(f"  Expediente: '{expediente}'")
                logger.info(f"  Organismo: {record['Organisme']}")
                logger.info(f"  Fase: {record.get('FaseProcedimiento', 'N/A')}")
                
                return record
            else:
                invalid_count += 1
                # logger.debug(f"  [DEBUG] Descartado: '{expediente}' (Regex no coincide)")
        
        conn.close()
        
        if invalid_count > 0:
            logger.warning(f"Se revisaron {invalid_count} recursos pero ninguno cumple los criterios")
        else:
            logger.warning("No se encontraron recursos disponibles")
        
        return None
        
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
    # Esperar un momento para que SQL Server refleje el cambio
    import time
    time.sleep(1)
    
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute(SQL_VERIFY_CLAIM, (id_recurso,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            logger.error(f"No se encontró el recurso {id_recurso} para verificar")
            return False
            
        texp, estado, usuario = row
        logger.info(f"Estado actual en DB: TExp={texp}, Estado={estado}, Usuario='{usuario}'")
        
        # Consideramos éxito si:
        # 1. TExp cambió a 1 (lo que esperábamos originalmente)
        # 2. O Estado ya no es 0 (pasó de Pendiente a En Proceso)
        # 3. O ya tiene un usuario asignado
        if estado > 0 or (usuario and str(usuario).strip()):
            logger.info(f"✅ Claim verificado exitosamente (Estado={estado}, Usuario='{usuario}')")
            return True
        else:
            logger.warning(f"⚠️ El recurso sigue apareciendo como PENDIENTE (TExp={texp}, Estado={estado})")
            return False
    except Exception as e:
        logger.error(f"Error verificando claim: {e}")
        return False


def enqueue_task(db: SQLiteDatabase, site_id: str, recurso: dict, dry_run: bool = False) -> int:
    """Encola la tarea en tramite_queue."""
    # Convertir Decimal a int para evitar errores de serialización JSON
    payload = {
        "idRecurso": int(recurso["idRecurso"]) if recurso.get("idRecurso") else None,
        "idExp": int(recurso["idExp"]) if recurso.get("idExp") else None,
        "expediente": recurso["Expedient"],
        "numclient": int(recurso["numclient"]) if recurso.get("numclient") else None,
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
    
    # Primero hacer login para obtener el nombre del usuario autenticado
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
    
    session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar)
    
    try:
        await create_authenticated_session_in_place(session, XVIA_EMAIL, XVIA_PASSWORD)
        logger.info("✓ Login exitoso")
        
        # Obtener nombre del usuario autenticado
        authenticated_user = await get_authenticated_username(session)
        if authenticated_user:
            logger.info(f"✓ Usuario autenticado: {authenticated_user}")
        else:
            logger.warning("⚠️  No se pudo obtener el nombre del usuario")
    except Exception as e:
        logger.error(f"Error en login: {e}")
        await session.close()
        return 1
    
    # Buscar UN recurso (libre o asignado al usuario actual)
    conn_str = build_sqlserver_connection_string()
    recurso = fetch_one_resource(config, conn_str, authenticated_user)
    
    if not recurso:
        logger.warning("No hay recursos disponibles para reclamar")
        await session.close()
        return 0
    
    # Si el recurso ya está en Estado 1, saltamos la parte de POST
    already_claimed = (recurso.get("Estado") == 1)
    
    if already_claimed:
        logger.info(f"ℹ️  El recurso ya está ASIGNADO a ti (Estado=1). Saltando claim vía POST.")
    else:
        # Reclamar recurso (ya tenemos la sesión autenticada)
        logger.info("")
        if not await claim_resource(session, recurso["idRecurso"], args.dry_run):
            logger.error("❌ Claim falló")
            await session.close()
            return 1
    
        # Verificar claim en SQL Server solo si lo acabamos de reclamar
        logger.info("")
        if not args.dry_run:
            if not verify_claim(recurso["idRecurso"], conn_str):
                logger.error("❌ Claim no verificado en SQL Server")
                await session.close()
                return 1
    
    await session.close()
    
    # Encolar tarea (se hace tanto si lo acabamos de reclamar como si ya estaba asignado)
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
