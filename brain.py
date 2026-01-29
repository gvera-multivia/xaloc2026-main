#!/usr/bin/env python
"""
brain.py - Orquestador principal del sistema Xvia.

Este módulo es responsable de:
1. Detectar recursos disponibles en SQL Server
2. Autenticarse en la plataforma Xvia con aiohttp
3. Reclamar recursos mediante POST al endpoint /AsignarA
4. Distribuir tareas a la cola local de workers

Uso:
    python brain.py [--once] [--dry-run]

Opciones:
    --once      Ejecutar un solo ciclo (para testing)
    --dry-run   No realizar cambios en las bases de datos
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
import pyodbc
from dotenv import load_dotenv

from core.sqlite_db import SQLiteDatabase
from core.xvia_auth import create_authenticated_session_in_place


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

load_dotenv()

SYNC_INTERVAL_SECONDS = int(os.getenv("BRAIN_SYNC_INTERVAL", 300))
MAX_CLAIMS_PER_CYCLE = int(os.getenv("BRAIN_MAX_CLAIMS", 50))
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db")

# Credenciales Xvia
XVIA_EMAIL = os.getenv("XVIA_EMAIL")
XVIA_PASSWORD = os.getenv("XVIA_PASSWORD")

# Endpoint para asignar recursos
ASIGNAR_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/AsignarA"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [BRAIN] - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/brain.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("brain")


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

SQL_VERIFY_CLAIM = """
SELECT TExp, UsuarioAsignado
FROM Recursos.RecursosExp
WHERE idRecurso = ?
"""


# =============================================================================
# CLASE PRINCIPAL
# =============================================================================

class BrainOrchestrator:
    """
    Orquestador central que gestiona la detección, reclamación y 
    distribución de recursos desde SQL Server hacia los workers locales.
    """
    
    def __init__(
        self, 
        sqlite_db: SQLiteDatabase, 
        sqlserver_conn_str: str,
        dry_run: bool = False
    ):
        self.db = sqlite_db
        self.sqlserver_conn_str = sqlserver_conn_str
        self.dry_run = dry_run
        self.logger = logger
        self.session: Optional[aiohttp.ClientSession] = None
        
    # -------------------------------------------------------------------------
    # PASO 0: Inicializar sesión autenticada
    # -------------------------------------------------------------------------
    async def init_session(self, login_url: str) -> None:
        """Inicializa sesión aiohttp y realiza login en Xvia."""
        if self.dry_run:
            self.logger.info("[DRY-RUN] Saltando inicialización de sesión")
            return
        
        # Configuración de cookies y headers (igual que en worker.py)
        cookie_jar = aiohttp.CookieJar(unsafe=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
            "Referer": login_url,
            "Origin": "http://www.xvia-grupoeuropa.net",
            "Connection": "keep-alive",
        }
        
        self.session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar)
        
        try:
            await create_authenticated_session_in_place(
                self.session, 
                XVIA_EMAIL, 
                XVIA_PASSWORD,
                login_url
            )
            self.logger.info("✓ Sesión XVIA autenticada correctamente")
        except Exception as e:
            await self.session.close()
            self.session = None
            raise RuntimeError(f"Error en autenticación: {e}")
    
    async def close_session(self) -> None:
        """Cierra la sesión."""
        if self.session:
            await self.session.close()
            self.session = None
    
    # -------------------------------------------------------------------------
    # PASO 1: Obtener configuraciones activas
    # -------------------------------------------------------------------------
    def get_active_configs(self) -> list[dict]:
        """Obtiene todas las configuraciones de organismos activos."""
        return self.db.get_active_organismo_configs()
    
    # -------------------------------------------------------------------------
    # PASO 2: Consultar recursos candidatos
    # -------------------------------------------------------------------------
    def fetch_remote_resources(self, config: dict) -> list[dict]:
        """
        Consulta recursos en SQL Server que cumplan:
        - Organisme LIKE config.query_organisme
        - TExp IN (filtro_texp)
        - Estado = 0
        - Expedient válido según regex
        """
        texp_values = [int(x.strip()) for x in config["filtro_texp"].split(",")]
        texp_placeholders = ",".join(["?"] * len(texp_values))
        
        query = SQL_FETCH_RECURSOS.format(texp_list=texp_placeholders)
        
        try:
            conn = pyodbc.connect(self.sqlserver_conn_str)
            cursor = conn.cursor()
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
                    self.logger.debug(
                        f"Expediente descartado por regex: {expediente}"
                    )
            
            conn.close()
            self.logger.info(
                f"[{config['site_id']}] Encontrados {len(results)} recursos válidos"
            )
            return results
            
        except Exception as e:
            self.logger.error(f"Error consultando SQL Server: {e}")
            return []
    
    # -------------------------------------------------------------------------
    # PASO 3: Reclamar recurso vía POST
    # -------------------------------------------------------------------------
    async def claim_resource_via_post(
        self, 
        id_recurso: int,
        expediente: str
    ) -> bool:
        """
        Hace POST al endpoint /AsignarA para reclamar el recurso.
        Retorna True si el claim fue exitoso.
        """
        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Claim simulado para idRecurso={id_recurso}")
            return True
        
        if not self.session:
            self.logger.error("Sesión no inicializada")
            return False
        
        try:
            # Obtener el token CSRF de la sesión actual
            # El token está en las cookies después del login
            csrf_token = None
            for cookie in self.session.cookie_jar:
                if cookie.key == "XSRF-TOKEN":
                    csrf_token = cookie.value
                    break
            
            # Si no está en cookies, obtenerlo de la página
            if not csrf_token:
                async with self.session.get(
                    "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
                ) as resp:
                    html = await resp.text()
                    # Buscar el token en el HTML
                    match = re.search(r'name="_token"\s+value="([^"]+)"', html)
                    if match:
                        csrf_token = match.group(1)
            
            if not csrf_token:
                self.logger.error("No se pudo obtener el token CSRF")
                return False
            
            # Preparar datos del formulario
            form_data = {
                "_token": csrf_token,
                "id": str(id_recurso),
                "recursosSel": "0"  # 0 = Recurso actual
            }
            
            self.logger.info(f"Enviando claim para idRecurso={id_recurso}")
            
            # Hacer POST
            async with self.session.post(ASIGNAR_URL, data=form_data) as resp:
                if resp.status in (200, 302, 303):
                    # Verificar en SQL Server que el claim fue exitoso
                    if self.verify_claim_in_db(id_recurso):
                        self.logger.info(f"✓ Recurso {id_recurso} ({expediente}) reclamado exitosamente")
                        return True
                    else:
                        self.logger.warning(f"✗ POST exitoso pero claim no confirmado en DB para {id_recurso}")
                        return False
                else:
                    self.logger.error(f"✗ POST falló con status {resp.status}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error en claim vía POST para {expediente}: {e}")
            return False
    
    def verify_claim_in_db(self, id_recurso: int) -> bool:
        """Verifica en SQL Server que TExp cambió a 1."""
        try:
            conn = pyodbc.connect(self.sqlserver_conn_str)
            cursor = conn.cursor()
            cursor.execute(SQL_VERIFY_CLAIM, (id_recurso,))
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0] == 1:  # TExp = 1
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error verificando claim en DB: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # PASO 4: Construir payload
    # -------------------------------------------------------------------------
    def build_payload(self, recurso: dict, config: dict) -> dict:
        """
        Construye el payload compatible con el worker.
        
        Este método debe mapear los campos de SQL Server a los campos
        que espera el worker (similar a sync_by_id_to_worker.py).
        """
        return {
            "idRecurso": recurso["idRecurso"],
            "idExp": recurso.get("idExp"),
            "expediente": recurso["Expedient"],
            "numclient": recurso.get("numclient"),
            "sujeto_recurso": recurso.get("SujetoRecurso"),
            "fase_procedimiento": recurso.get("FaseProcedimiento"),
            "source": "brain_orchestrator",
            "claimed_at": datetime.now().isoformat()
        }
    
    # -------------------------------------------------------------------------
    # PASO 5: Encolar tarea
    # -------------------------------------------------------------------------
    def enqueue_locally(self, site_id: str, payload: dict) -> int:
        """Inserta la tarea en tramite_queue de SQLite."""
        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Encolado simulado: {payload['expediente']}")
            return -1
        
        task_id = self.db.insert_task(site_id, None, payload)
        self.logger.info(
            f"📥 Tarea {task_id} encolada: {payload['expediente']} -> {site_id}"
        )
        return task_id
    
    # -------------------------------------------------------------------------
    # CICLO PRINCIPAL
    # -------------------------------------------------------------------------
    async def run_cycle(self) -> dict:
        """
        Ejecuta un ciclo completo de sincronización.
        
        Returns:
            Dict con estadísticas: claimed, enqueued, errors
        """
        stats = {"claimed": 0, "enqueued": 0, "errors": 0}
        
        configs = self.get_active_configs()
        if not configs:
            self.logger.warning("No hay configuraciones activas")
            return stats
        
        self.logger.info(f"Procesando {len(configs)} configuraciones activas")
        
        for config in configs:
            site_id = config["site_id"]
            self.logger.info(f"── Iniciando sync para: {site_id}")
            
            try:
                # Inicializar sesión autenticada
                await self.init_session(config["login_url"])
                
                # Obtener recursos
                recursos = self.fetch_remote_resources(config)
                
                for recurso in recursos[:MAX_CLAIMS_PER_CYCLE]:
                    try:
                        # Intentar claim vía POST
                        if await self.claim_resource_via_post(
                            recurso["idRecurso"],
                            recurso["Expedient"]
                        ):
                            stats["claimed"] += 1
                            
                            # Construir payload y encolar
                            payload = self.build_payload(recurso, config)
                            self.enqueue_locally(site_id, payload)
                            stats["enqueued"] += 1
                            
                    except Exception as e:
                        self.logger.error(f"Error procesando recurso: {e}")
                        stats["errors"] += 1
                
                # Cerrar sesión
                await self.close_session()
                
                # Actualizar timestamp de última sincronización
                if not self.dry_run:
                    self.db.update_last_sync(site_id)
                    
            except Exception as e:
                self.logger.error(f"Error en config {site_id}: {e}")
                stats["errors"] += 1
                await self.close_session()
        
        return stats
    
    async def run_forever(self):
        """Bucle infinito del orquestador."""
        self.logger.info("=" * 60)
        self.logger.info("🧠 BRAIN ORCHESTRATOR INICIADO")
        self.logger.info(f"   Intervalo: {SYNC_INTERVAL_SECONDS}s")
        self.logger.info(f"   Max claims/ciclo: {MAX_CLAIMS_PER_CYCLE}")
        self.logger.info(f"   Dry-run: {self.dry_run}")
        self.logger.info("=" * 60)
        
        while True:
            try:
                stats = await self.run_cycle()
                self.logger.info(
                    f"📊 Ciclo completado: "
                    f"claimed={stats['claimed']}, "
                    f"enqueued={stats['enqueued']}, "
                    f"errors={stats['errors']}"
                )
            except Exception as e:
                self.logger.error(f"Error fatal en ciclo: {e}")
            
            self.logger.info(f"💤 Esperando {SYNC_INTERVAL_SECONDS}s...")
            await asyncio.sleep(SYNC_INTERVAL_SECONDS)


# =============================================================================
# UTILIDADES
# =============================================================================

def build_sqlserver_connection_string() -> str:
    """
    Construye el connection string para SQL Server.
    Prioridad: variable de entorno completa > variables separadas.
    """
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
# PUNTO DE ENTRADA
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Brain Orchestrator - Gestor de recursos Xvia"
    )
    parser.add_argument(
        "--once", 
        action="store_true",
        help="Ejecutar un solo ciclo y salir"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No realizar cambios en las bases de datos"
    )
    parser.add_argument(
        "--sqlite-db",
        default=SQLITE_DB_PATH,
        help="Ruta al archivo SQLite"
    )
    
    args = parser.parse_args()
    
    # Validar credenciales
    if not XVIA_EMAIL or not XVIA_PASSWORD:
        logger.error("XVIA_EMAIL y XVIA_PASSWORD deben estar definidos en .env")
        sys.exit(1)
    
    # Inicializar componentes
    db = SQLiteDatabase(args.sqlite_db)
    conn_str = build_sqlserver_connection_string()
    
    orchestrator = BrainOrchestrator(
        sqlite_db=db,
        sqlserver_conn_str=conn_str,
        dry_run=args.dry_run
    )
    
    # Ejecutar
    if args.once:
        stats = asyncio.run(orchestrator.run_cycle())
        print(f"Ciclo completado: {stats}")
    else:
        asyncio.run(orchestrator.run_forever())


if __name__ == "__main__":
    main()
