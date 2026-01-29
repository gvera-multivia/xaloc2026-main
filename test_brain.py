#!/usr/bin/env python
"""
test_brain.py - Script de testing del Brain Orchestrator (SIN CLICS REALES).

Este script:
1. ✓ Hace login real en Xvia con aiohttp
2. ✓ Consulta recursos reales desde SQL Server
3. ✗ NO hace POST a /AsignarA (simulado)
4. ✗ NO encola tareas (simulado)

Uso:
    python test_brain.py [--site-id xaloc_girona] [--max-recursos 5]
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [TEST-BRAIN] - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/test_brain.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("test_brain")


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
    rs.FaseProcedimiento
FROM Recursos.RecursosExp rs
WHERE rs.Organisme LIKE ?
  AND rs.TExp IN ({texp_list})
  AND rs.Estado = 0
  AND rs.Expedient IS NOT NULL
ORDER BY rs.idRecurso ASC
"""


# =============================================================================
# FUNCIONES DE TESTING
# =============================================================================

async def test_login(login_url: str) -> bool:
    """
    Prueba el login en Xvia con aiohttp.
    Retorna True si el login fue exitoso.
    """
    logger.info("=" * 60)
    logger.info("🔐 TEST 1: AUTENTICACIÓN EN XVIA")
    logger.info("=" * 60)
    
    try:
        # Configuración de cookies y headers
        cookie_jar = aiohttp.CookieJar(unsafe=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
            "Referer": login_url,
            "Origin": "http://www.xvia-grupoeuropa.net",
            "Connection": "keep-alive",
        }
        
        session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar)
        
        logger.info(f"📍 Autenticando con: {XVIA_EMAIL}")
        
        await create_authenticated_session_in_place(
            session, 
            XVIA_EMAIL, 
            XVIA_PASSWORD,
            login_url
        )
        
        logger.info("✅ LOGIN EXITOSO")
        logger.info(f"   Usuario: {XVIA_EMAIL}")
        logger.info(f"   Cookies guardadas: {len(session.cookie_jar)}")
        
        await session.close()
        return True
        
    except Exception as e:
        logger.error(f"✗ Error en test de login: {e}")
        return False


def test_fetch_recursos(config: dict, conn_str: str, max_recursos: int = 5) -> list[dict]:
    """
    Prueba la consulta de recursos desde SQL Server.
    Retorna lista de recursos encontrados.
    """
    logger.info("\n" + "=" * 60)
    logger.info("🗄️  TEST 2: CONSULTA DE RECURSOS EN SQL SERVER")
    logger.info("=" * 60)
    
    logger.info(f"📋 Configuración:")
    logger.info(f"   Site ID: {config['site_id']}")
    logger.info(f"   Organismo: {config['query_organisme']}")
    logger.info(f"   TExp: {config['filtro_texp']}")
    logger.info(f"   Regex: {config['regex_expediente']}")
    
    texp_values = [int(x.strip()) for x in config["filtro_texp"].split(",")]
    texp_placeholders = ",".join(["?"] * len(texp_values))
    
    query = SQL_FETCH_RECURSOS.format(texp_list=texp_placeholders)
    
    try:
        logger.info("🔌 Conectando a SQL Server...")
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        
        logger.info("🔍 Ejecutando consulta...")
        cursor.execute(query, [config["query_organisme"]] + texp_values)
        
        columns = [column[0] for column in cursor.description]
        results = []
        
        regex = re.compile(config["regex_expediente"])
        
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            expediente = record.get("Expedient", "")
            
            # Validar formato de expediente
            if expediente and regex.match(expediente):
                results.append(record)
            else:
                logger.debug(f"   Descartado: {expediente} (no cumple regex)")
        
        conn.close()
        
        logger.info(f"✅ CONSULTA EXITOSA")
        logger.info(f"   Total encontrados: {len(results)} recursos")
        
        # Mostrar primeros N recursos
        logger.info(f"\n📊 Primeros {min(max_recursos, len(results))} recursos:")
        for i, recurso in enumerate(results[:max_recursos], 1):
            logger.info(f"\n   [{i}] Recurso ID: {recurso['idRecurso']}")
            logger.info(f"       Expediente: {recurso['Expedient']}")
            logger.info(f"       Organismo: {recurso['Organisme']}")
            logger.info(f"       TExp: {recurso['TExp']}")
            logger.info(f"       Estado: {recurso['Estado']}")
            logger.info(f"       Fase: {recurso.get('FaseProcedimiento', 'N/A')}")
        
        return results
        
    except Exception as e:
        logger.error(f"✗ Error consultando SQL Server: {e}")
        return []


def test_simulate_claim(recursos: list[dict], max_claims: int = 3):
    """
    Simula el proceso de claim SIN hacer POST real.
    """
    logger.info("\n" + "=" * 60)
    logger.info("🎭 TEST 3: SIMULACIÓN DE CLAIM (SIN POST REAL)")
    logger.info("=" * 60)
    
    logger.info(f"⚠️  MODO SIMULACIÓN: No se harán POST a /AsignarA")
    logger.info(f"   Recursos a simular: {min(max_claims, len(recursos))}")
    
    ASIGNAR_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/AsignarA"
    
    for i, recurso in enumerate(recursos[:max_claims], 1):
        logger.info(f"\n   [{i}] SIMULANDO claim para:")
        logger.info(f"       Expediente: {recurso['Expedient']}")
        logger.info(f"       ID Recurso: {recurso['idRecurso']}")
        logger.info(f"       ✓ Haría POST a: {ASIGNAR_URL}")
        logger.info(f"       ✓ Con datos: _token=<csrf>, id={recurso['idRecurso']}, recursosSel=0")
        logger.info(f"       ✓ Verificaría: TExp cambió a 1 en SQL Server")
        logger.info(f"       ⚠️  SIMULADO - No se ejecutó realmente")


def test_simulate_enqueue(recursos: list[dict], site_id: str, max_enqueue: int = 3):
    """
    Simula el encolado de tareas SIN insertar en la base de datos.
    """
    logger.info("\n" + "=" * 60)
    logger.info("📥 TEST 4: SIMULACIÓN DE ENCOLADO (SIN INSERTAR EN DB)")
    logger.info("=" * 60)
    
    logger.info(f"⚠️  MODO SIMULACIÓN: No se insertarán tareas en tramite_queue")
    logger.info(f"   Tareas a simular: {min(max_enqueue, len(recursos))}")
    
    for i, recurso in enumerate(recursos[:max_enqueue], 1):
        payload = {
            "idRecurso": recurso["idRecurso"],
            "idExp": recurso.get("idExp"),
            "expediente": recurso["Expedient"],
            "numclient": recurso.get("numclient"),
            "sujeto_recurso": recurso.get("SujetoRecurso"),
            "fase_procedimiento": recurso.get("FaseProcedimiento"),
            "source": "test_brain_simulator",
            "claimed_at": datetime.now().isoformat()
        }
        
        logger.info(f"\n   [{i}] SIMULANDO encolado:")
        logger.info(f"       Site ID: {site_id}")
        logger.info(f"       Expediente: {payload['expediente']}")
        logger.info(f"       Payload: {len(str(payload))} bytes")
        logger.info(f"       ✓ Insertaría en: tramite_queue")
        logger.info(f"       ⚠️  SIMULADO - No se insertó realmente")


def build_sqlserver_connection_string() -> str:
    """Construye el connection string para SQL Server."""
    direct = os.getenv("SQLSERVER_CONNECTION_STRING")
    if direct:
        return direct
    
    driver = os.getenv("SQLSERVER_DRIVER", "{ODBC Driver 17 for SQL Server}")
    server = os.getenv("SQLSERVER_SERVER")
    database = os.getenv("SQLSERVER_DATABASE")
    username = os.getenv("SQLSERVER_USERNAME")
    password = os.getenv("SQLSERVER_PASSWORD")
    
    if os.getenv("SQLSERVER_TRUSTED_CONNECTION") == "1":
        return f"DRIVER={driver};SERVER={server};DATABASE={database};Trusted_Connection=yes"
    
    return f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}"


# =============================================================================
# MAIN
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Test del Brain Orchestrator (solo login real, resto simulado)"
    )
    parser.add_argument(
        "--site-id",
        default="xaloc_girona",
        help="ID del site a testear"
    )
    parser.add_argument(
        "--max-recursos",
        type=int,
        default=5,
        help="Máximo de recursos a mostrar"
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="Saltar test de login"
    )
    
    args = parser.parse_args()
    
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
        logger.info(f"Configuraciones disponibles: {[c['site_id'] for c in configs]}")
        return 1
    
    # TEST 1: Login
    if not args.skip_login:
        login_success = await test_login(config["login_url"])
        if not login_success:
            logger.error("❌ Test de login falló. Abortando.")
            return 1
    else:
        logger.info("⏭️  Saltando test de login (--skip-login)")
    
    # TEST 2: Consulta de recursos
    conn_str = build_sqlserver_connection_string()
    recursos = test_fetch_recursos(config, conn_str, args.max_recursos)
    
    if not recursos:
        logger.warning("⚠️  No se encontraron recursos para procesar")
        return 0
    
    # TEST 3: Simulación de claim
    test_simulate_claim(recursos, max_claims=3)
    
    # TEST 4: Simulación de encolado
    test_simulate_enqueue(recursos, args.site_id, max_enqueue=3)
    
    # Resumen final
    logger.info("\n" + "=" * 60)
    logger.info("📊 RESUMEN DEL TEST")
    logger.info("=" * 60)
    logger.info(f"✅ Login: {'OK' if not args.skip_login else 'SALTADO'}")
    logger.info(f"✅ Consulta SQL Server: OK ({len(recursos)} recursos)")
    logger.info(f"⚠️  Claim: SIMULADO (sin POST real)")
    logger.info(f"⚠️  Encolado: SIMULADO (sin insertar en DB)")
    logger.info("=" * 60)
    logger.info("✅ TEST COMPLETADO EXITOSAMENTE")
    logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
