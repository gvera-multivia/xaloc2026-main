#!/usr/bin/env python
"""
brain.py - Orquestador principal del sistema Xvia.

Este mÃ³dulo es responsable de:
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
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiohttp
import pyodbc
from dotenv import load_dotenv

from core.sqlite_db import SQLiteDatabase
from core.queue_gateway import build_queue_gateway
from core.realtime_store import build_realtime_store
from core.xvia_auth import create_authenticated_session_in_place
from core.nt_expediente_fixer import is_nt_pattern, fix_nt_expediente
from core.client_documentation import check_requires_gesdoc
from core.address_classifier import classify_addresses_batch_with_ai, classify_address_fallback
from sites.adapters import MadridAdapter, XalocAdapter, BaseOnlineAdapter
from sites.adapters.site_adapter import SiteAdapter


# =============================================================================
# CONFIGURACIÃ“N
# =============================================================================

load_dotenv()

SYNC_INTERVAL_SECONDS = int(os.getenv("BRAIN_SYNC_INTERVAL", 500))
TICK_INTERVAL_SECONDS = int(os.getenv("BRAIN_TICK_SECONDS", 5))
MAX_CLAIMS_PER_CYCLE = int(os.getenv("BRAIN_MAX_CLAIMS", 999999))
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db")
ENABLED_SITES_CSV = os.getenv("BRAIN_ENABLED_SITES", "").strip()
QUEUE_BACKEND = (os.getenv("QUEUE_BACKEND", "sqlite") or "sqlite").strip().lower()

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


@dataclass
class EnqueueResult:
    job_id: str
    enqueued: bool
    queue: str  # "ready", "pending_authorization", "duplicate"


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
    -- Campos para identificaciÃ³n del cliente (GESDOC check)
    rs.Empresa,
    rs.cif,
    c.Nombrefiscal,
    c.nifempresa,
    c.nif AS cliente_nif,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    -- Campo matrÃ­cula desde expedientes
    e.matricula
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente
WHERE {organisme_like_clause}
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
# ADAPTERS Y POLÃTICAS
# =============================================================================

SITE_PRIORITIES: dict[str, int] = {
    "madrid": 0,
    "xaloc_girona": 1,
    "base_online": 2,
}


def _parse_enabled_sites(csv_value: str) -> Optional[set[str]]:
    value = (csv_value or "").strip()
    if not value:
        return None
    items = [p.strip() for p in value.split(",")]
    return {p for p in items if p}

class BrainOrchestrator:
    """
    Orquestador central que gestiona la detecciÃ³n, reclamaciÃ³n y 
    distribuciÃ³n de recursos desde SQL Server hacia los workers locales.
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
        self.authenticated_user: Optional[str] = None
        self.queue_backend = QUEUE_BACKEND
        self.queue_gateway = build_queue_gateway(backend=self.queue_backend, db=self.db)
        self.realtime_store = build_realtime_store(logger=self.logger)

        self.adapters: dict[str, SiteAdapter] = {
            "madrid": MadridAdapter(),
            "xaloc_girona": XalocAdapter(),
            "base_online": BaseOnlineAdapter(),
        }

    def _record_incident_once(
        self,
        *,
        site_id: str,
        incident_type: str,
        reason: str,
        resource_id: Optional[int],
        expediente: Optional[str],
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        self.realtime_store.record_incident_once(
            site_id=site_id,
            incident_type=incident_type,
            reason=reason,
            resource_id=resource_id,
            expediente=expediente,
            payload=payload,
        )

    def _is_resource_blocked(self, *, site_id: str, resource_id: Any) -> bool:
        try:
            rid = int(resource_id)
        except Exception:
            return False
        return self.db.is_resource_blocked(site_id=site_id, resource_id=rid)


        
    # -------------------------------------------------------------------------
    # PASO 0: Inicializar sesiÃ³n autenticada
    # -------------------------------------------------------------------------
    async def init_session(self, login_url: str) -> None:
        """Inicializa sesiÃ³n aiohttp y realiza login en Xvia."""
        if self.dry_run:
            self.logger.info("[DRY-RUN] Saltando inicializaciÃ³n de sesiÃ³n")
            return
        
        # ConfiguraciÃ³n de cookies y headers (igual que en worker.py)
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
            self.logger.info("âœ“ SesiÃ³n XVIA autenticada correctamente")
            
            # Obtener nombre del usuario autenticado
            self.authenticated_user = await self.get_authenticated_username()
            if self.authenticated_user:
                self.logger.info(f"âœ“ Usuario autenticado: {self.authenticated_user}")
            else:
                self.logger.warning("âš ï¸ No se pudo obtener el nombre del usuario autenticado")
                
        except Exception as e:
            await self.session.close()
            self.session = None
            raise RuntimeError(f"Error en autenticaciÃ³n: {e}")
            
    async def get_authenticated_username(self) -> Optional[str]:
        """Obtiene el nombre del usuario autenticado desde la pÃ¡gina de Xvia."""
        if not self.session:
            return None
        try:
            async with self.session.get("http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/home") as resp:
                html = await resp.text()
                # Buscar el nombre en el dropdown del usuario
                match = re.search(r'<i class="fa fa-user-circle"[^>]*></i>\s*([^<]+)', html)
                if match:
                    username = match.group(1).strip()
                    return username
                return None
        except Exception as e:
            self.logger.error(f"Error obteniendo nombre de usuario: {e}")
            return None
    
    async def close_session(self) -> None:
        """Cierra la sesiÃ³n."""
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
        - Expedient vÃ¡lido segÃºn regex
        """
        texp_values = [int(x.strip()) for x in config["filtro_texp"].split(",")]
        texp_placeholders = ",".join(["?"] * len(texp_values))
        
        # Manejar mÃºltiples patrones LIKE (separados por espacios)
        query_organisme_raw = config["query_organisme"]
        patterns = [p.strip() for p in query_organisme_raw.split(" ") if p.strip()]
        
        if not patterns:
            patterns = ["%"]
        
        like_clauses = ["rs.Organisme LIKE ?"] * len(patterns)
        organisme_like_clause = " AND ".join(like_clauses)
        
        query = SQL_FETCH_RECURSOS.format(
            organisme_like_clause=organisme_like_clause,
            texp_list=texp_placeholders
        )

        
        try:
            conn = pyodbc.connect(self.sqlserver_conn_str)
            cursor = conn.cursor()
            cursor.execute(query, patterns + texp_values)
            
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
                    # Fallback: intentar corregir expediente con formato NT/
                    if is_nt_pattern(expediente):
                        id_exp = record.get("idExp")
                        corrected = fix_nt_expediente(self.sqlserver_conn_str, id_exp)
                        if corrected and regex.match(corrected):
                            self.logger.info(
                                f"âœ… Expediente NT/ corregido: '{expediente}' -> '{corrected}'"
                            )
                            record["Expedient"] = corrected
                            results.append(record)
                        else:
                            self.logger.warning(
                                f"âŒ Expediente NT/ no corregible: {expediente}"
                            )
                    else:
                        self.logger.debug(
                            f"Expediente descartado por regex: {expediente}"
                        )
                        self._record_incident_once(
                            site_id=str(config.get("site_id") or ""),
                            incident_type="REGEX_DISCARDED",
                            reason="Expediente descartado por regex del organismo",
                            resource_id=record.get("idRecurso"),
                            expediente=str(expediente or ""),
                            payload={"record": record},
                        )
            
            conn.close()
            self.logger.info(
                f"[{config['site_id']}] Encontrados {len(results)} recursos vÃ¡lidos"
            )
            return results
            
        except Exception as e:
            self.logger.error(f"Error consultando SQL Server: {e}")
            return []
    
    # -------------------------------------------------------------------------
    # PASO 3: Reclamar recurso vÃ­a POST
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
            self.logger.error("SesiÃ³n no inicializada")
            return False
        
        try:
            # Siempre obtener token CSRF fresco de la pÃ¡gina antes de cada POST
            async with self.session.get(
                "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
            ) as resp:
                html = await resp.text()
                # Buscar el token en el HTML
                match = re.search(r'name="_token"\s+value="([^"]+)"', html)
                if not match:
                    self.logger.error("No se pudo obtener el token CSRF del HTML")
                    return False
                csrf_token = match.group(1)
            
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
                        self.logger.info(f"âœ“ Recurso {id_recurso} ({expediente}) reclamado exitosamente")
                        return True
                    else:
                        self.logger.warning(f"âœ— POST exitoso pero claim no confirmado en DB para {id_recurso}")
                        return False
                else:
                    self.logger.error(f"âœ— POST fallÃ³ con status {resp.status}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error en claim vÃ­a POST para {expediente}: {e}")
            return False

    async def post_claim_resource(self, id_recurso: int) -> bool:
        """
        Hace POST a /AsignarA (sin verificar en SQL Server).
        """
        if self.dry_run:
            return True

        if not self.session:
            self.logger.error("SesiÃ³n no inicializada")
            return False

        try:
            async with self.session.get(
                "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
            ) as resp:
                html = await resp.text()
                match = re.search(r'name="_token"\s+value="([^"]+)"', html)
                if not match:
                    self.logger.error("No se pudo obtener el token CSRF del HTML")
                    return False
                csrf_token = match.group(1)

            form_data = {
                "_token": csrf_token,
                "id": str(id_recurso),
                "recursosSel": "0",
            }

            async with self.session.post(ASIGNAR_URL, data=form_data) as resp:
                return resp.status in (200, 302, 303)

        except Exception as e:
            self.logger.error(f"Error en POST claim (sin verify) idRecurso={id_recurso}: {e}")
            return False

    async def claim_resource_with_retries(
        self,
        *,
        id_recurso: int,
        expediente: str,
        retries: int = 5,
        delays_seconds: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0),
    ) -> bool:
        """
        Reclama recurso vÃ­a POST y verifica en SQL Server con retries/backoff.
        """
        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Claim simulado (retries) para idRecurso={id_recurso}")
            return True

        ok_post = await self.post_claim_resource(id_recurso)
        if not ok_post:
            return False

        for attempt in range(max(retries, 1)):
            if self.verify_claim_in_db(id_recurso):
                self.logger.info(f"âœ“ Recurso {id_recurso} ({expediente}) reclamado/verificado")
                return True
            delay = delays_seconds[min(attempt, len(delays_seconds) - 1)]
            await asyncio.sleep(delay)

        self.logger.warning(f"POST exitoso pero claim no confirmado en DB para idRecurso={id_recurso}")
        return False
    
    def verify_claim_in_db(self, id_recurso: int) -> bool:
        """
        Verifica en SQL Server que el recurso ha sido reclamado correctamente.
        Un recurso se considera reclamado si:
        - TExp cambia a 1.
        - O Estado pasa a ser > 0 (En proceso).
        - O UsuarioAsignado deja de estar vacÃ­o.
        """
        try:
            conn = pyodbc.connect(self.sqlserver_conn_str)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TExp, Estado, UsuarioAsignado 
                FROM Recursos.RecursosExp 
                WHERE idRecurso = ?
            """, (id_recurso,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                texp, estado, usuario = row
                # El claim es vÃ¡lido si el estado ha pasado a 1 y el usuario asignado es el nuestro
                # TExp debe ser 2 o 3 (el 1 y 4 no los hacemos)
                
                # Normalizamos el usuario para comparar
                usuario_db = str(usuario or "").strip()
                nuestro_usuario = str(self.authenticated_user or "").strip()
                
                is_claimed = (estado == 1) and (usuario_db == nuestro_usuario)
                
                if is_claimed:
                    self.logger.info(f"âœ… Claim verificado: Estado={estado}, Usuario='{usuario_db}'")
                    return True
                else:
                    self.logger.warning(f"âš ï¸ Claim NO verificado: TExp={texp}, Estado={estado}, Usuario='{usuario_db}' (Esperado: Estado=1, Usuario='{nuestro_usuario}')")
            return False
        except Exception as e:
            self.logger.error(f"Error verificando claim en DB: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # PASO 4: Construir payload
    # -------------------------------------------------------------------------
    def _convert_value(self, v):
        """Convierte valores SQL Server a tipos JSON serializables."""
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
        if v is None:
            return None
        return v
    
    def build_payload(self, recurso: dict, config: dict) -> dict:
        """
        Construye el payload compatible con el worker.
        Incluye todos los campos requeridos: email, denuncia_num, matricula, expediente_num, motivos.
        """
        import json
        import re
        import unicodedata
        from pathlib import Path
        
        # --- Helper functions (copiadas de claim_one_resource.py) ---
        def _clean_str(value) -> str:
            return str(value).strip() if value is not None else ""
        
        def _normalize_plate(value) -> str:
            cleaned = re.sub(r"\s+", "", _clean_str(value)).upper()
            return cleaned if cleaned else "."
        
        def normalize_text(text) -> str:
            if not text:
                return ""
            text = str(text).strip().lower()
            return "".join(
                c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
            )
        
        # --- Cargar config_motivos.json ---
        config_path = Path("config_motivos.json")
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                motivos_config = json.load(f)
        else:
            motivos_config = {}
        
        # --- Obtener motivos segÃºn fase ---
        expediente = _clean_str(recurso.get("Expedient"))
        fase_raw = recurso.get("FaseProcedimiento")
        sujeto_raw = _clean_str(recurso.get("SujetoRecurso")).upper()
        fase_norm = normalize_text(fase_raw)
        
        motivos_text = ""
        for key, value in (motivos_config or {}).items():
            if key and key in fase_norm:
                asunto = _clean_str(value.get("asunto")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto_raw)
                expone = _clean_str(value.get("expone")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto_raw)
                solicita = _clean_str(value.get("solicita")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto_raw)
                motivos_text = f"ASUNTO: {asunto}\n\nEXPONE: {expone}\n\nSOLICITA: {solicita}"
                break
        
        if not motivos_text:
            self.logger.warning(f"No se encontrÃ³ configuraciÃ³n de motivos para fase: {fase_raw}")
            motivos_text = f"ASUNTO: Recurso expediente {expediente}\n\nEXPONE: ...\n\nSOLICITA: ..."
        
        # --- Construir mandatario ---
        def _normalize_document_id(doc: str) -> str:
            if not doc:
                return ""
            d = doc.strip().upper()
            if d.startswith("ES") and len(d) > 2:
                d = d[2:]
            return re.sub(r"[^A-Z0-9]+", "", d)
 
        def _extraer_documento_control(documento: str) -> tuple[str, str]:
            doc_clean = _normalize_document_id(documento)
            if len(doc_clean) < 2:
                return ("", "")
            return (doc_clean[:-1], doc_clean[-1])
 
        def _detectar_tipo_documento(doc: str) -> str:
            """
            Detecta documento del notificado (Madrid): NIF, NIE o PASAPORTE.
            """
            d = _normalize_document_id(doc)
            if not d:
                return "NIF"
            if re.match(r"^[XYZ]\d{7}[A-Z]$", d) or re.match(r"^[XYZ]\d{7,8}$", d):
                return "NIE"
            if re.match(r"^\d{8}[A-Z]$", d) or re.match(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$", d) or re.match(r"^[KLM]\d{7}[A-Z0-9]$", d):
                return "NIF"
            if re.match(r"^[A-Z]{2,3}\d{5,9}$", d) or (re.search(r"[A-Z]", d) and re.search(r"\d", d) and 6 <= len(d) <= 15):
                return "PASAPORTE"
            return "NIF"
        
        empresa = _clean_str(recurso.get("Empresa") or recurso.get("Nombrefiscal")).upper()
        cif = _normalize_document_id(_clean_str(recurso.get("cif") or recurso.get("nifempresa")))
        
        if empresa or cif:
            # Persona JURÃDICA
            cif_doc, cif_ctrl = _extraer_documento_control(cif) if cif else ("", "")
            mandatario = {
                "tipo_persona": "JURIDICA",
                "razon_social": empresa,
                "cif_documento": cif_doc,
                "cif_control": cif_ctrl
            }
        else:
            # Persona FÃSICA
            nif = _normalize_document_id(_clean_str(recurso.get("cliente_nif")))
            tipo_doc = _detectar_tipo_documento(nif)
            if tipo_doc == "PASAPORTE":
                doc_num, doc_ctrl = nif, ""
            else:
                doc_num, doc_ctrl = _extraer_documento_control(nif) if nif else ("", "")
            mandatario = {
                "tipo_persona": "FISICA",
                "tipo_doc": tipo_doc,
                "doc_numero": doc_num,
                "doc_control": doc_ctrl,
                "nombre": _clean_str(recurso.get("cliente_nombre")).upper(),
                "apellido1": _clean_str(recurso.get("cliente_apellido1")).upper(),
                "apellido2": _clean_str(recurso.get("cliente_apellido2")).upper()
            }
        
        # --- Construir payload completo ---
        return {
            # Campos requeridos por el worker
            "idRecurso": self._convert_value(recurso["idRecurso"]),
            "idExp": self._convert_value(recurso.get("idExp")),
            "user_email": "INFO@XVIA-SERVICIOSJURIDICOS.COM",
            "denuncia_num": expediente,
            "plate_number": _normalize_plate(recurso.get("matricula")),
            "expediente_num": expediente,
            "expediente": expediente,
            "numclient": self._convert_value(recurso.get("numclient")),
            "sujeto_recurso": sujeto_raw,
            "fase_procedimiento": _clean_str(fase_raw),
            "motivos": motivos_text,
            "mandatario": mandatario,
            "adjuntos": [],
            # Campos adicionales para identificaciÃ³n
            "empresa": empresa,
            "cliente_nombre": _clean_str(recurso.get("cliente_nombre")),
            "cliente_apellido1": _clean_str(recurso.get("cliente_apellido1")),
            "cliente_apellido2": _clean_str(recurso.get("cliente_apellido2")),
            "source": "brain_orchestrator",
            "claimed_at": datetime.now().isoformat()
        }
    
    # -------------------------------------------------------------------------
    # PASO 5: Encolar tarea
    # -------------------------------------------------------------------------
    async def enqueue_locally(self, site_id: str, payload: dict) -> EnqueueResult:
        """
        Inserta la tarea en la cola apropiada.
        
        Si el caso requiere autorizaciÃ³n GESDOC â†’ pending_authorization_queue
        Si NO requiere GESDOC â†’ tramite_queue (procesamiento normal)
        """
        job_id = str(payload.get("job_id") or uuid.uuid4())
        payload["job_id"] = job_id
        protocol = payload.get("protocol") or payload.get("naturaleza")

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Encolado simulado: {payload['expediente']} (Protocol: {protocol})")
            return EnqueueResult(job_id=job_id, enqueued=True, queue="ready")
        
        # Verificar si requiere GESDOC antes de encolar (salvo bypass explÃ­cito)
        skip_gesdoc_check = bool(payload.get("disable_gesdoc"))
        requires_gesdoc = False
        reason = None
        if not skip_gesdoc_check:
            requires_gesdoc, reason = check_requires_gesdoc(payload)
        resource_id = payload.get("idRecurso")
        try:
            resource_id = int(resource_id) if resource_id is not None else None
        except Exception:
            resource_id = None
        
        if requires_gesdoc:
            # Enviar a cola de autorizaciÃ³n pendiente
            self.logger.warning(f"Pause Requiere GESDOC: {payload['expediente']} - {reason}")
            self._record_incident_once(
                site_id=site_id,
                incident_type="REQUIRES_GESDOC",
                reason=reason or "Requiere autorizacion GESDOC",
                resource_id=resource_id,
                expediente=str(payload.get("expediente") or payload.get("expediente_num") or ""),
                payload=payload,
            )
            pending_id = self.db.insert_pending_authorization(
                site_id=site_id,
                payload=payload,
                authorization_type="gesdoc",
                reason=reason
            )
            self.db.upsert_job_run(
                job_id=job_id,
                site_id=site_id,
                resource_id=resource_id,
                protocol=protocol,
                payload_snapshot=payload,
                state="awaiting_auth",
            )
            self.logger.info(
                f"ðŸ“‹ Tarea {pending_id} en pending_authorization_queue: {payload['expediente']}"
            )
            return EnqueueResult(job_id=job_id, enqueued=True, queue="pending_authorization")
        
        # No requiere GESDOC â†’ cola normal
        enqueued, queued_job_id = await self.queue_gateway.enqueue(site_id=site_id, protocol=protocol, payload=payload)
        if enqueued:
            self.logger.info(f"Tarea {queued_job_id} encolada: {payload['expediente']} -> {site_id}")
        else:
            self.logger.info(f"Tarea duplicada omitida: {payload['expediente']} -> {site_id}")
        return EnqueueResult(job_id=queued_job_id, enqueued=enqueued, queue=("ready" if enqueued else "duplicate"))
    
    # -------------------------------------------------------------------------
    # CICLO PRINCIPAL
    # -------------------------------------------------------------------------
    def _get_enabled_adapters_and_configs(self) -> tuple[list[SiteAdapter], dict[str, dict]]:
        enabled_sites = _parse_enabled_sites(ENABLED_SITES_CSV)

        configs = {cfg["site_id"]: cfg for cfg in self.get_active_configs()}
        adapters: list[SiteAdapter] = []
        for site_id, adapter in self.adapters.items():
            if enabled_sites is not None and site_id not in enabled_sites:
                continue
            if site_id not in configs:
                continue
            adapters.append(adapter)

        adapters.sort(key=lambda a: (a.priority, a.site_id))
        return adapters, configs

    async def _choose_site_to_refill(self, adapters: list[SiteAdapter], configs: dict[str, dict]) -> Optional[str]:
        priorities = dict(SITE_PRIORITIES)
        for a in adapters:
            priorities[a.site_id] = a.priority

        # Lock global: si hay cualquier tarea queued/processing, NO mezclar.
        if self.queue_backend == "redis":
            counts = self.db.count_job_runs_any(states=("queued", "processing"))
            candidates = [s for s, c in counts.items() if c > 0]
            locked = sorted(candidates, key=lambda s: (priorities.get(s, 999), s))[0] if candidates else None
        else:
            locked = self.db.get_locked_site_by_priority(priorities)
        if locked:
            return locked

        for adapter in adapters:
            if adapter.site_id not in configs:
                continue
            try:
                def _on_discard(item: dict) -> None:
                    try:
                        self._record_incident_once(
                            site_id=str(item.get("site_id") or adapter.site_id),
                            incident_type=str(item.get("tipo_incidencia") or "SITE_RULE_DISCARDED"),
                            reason=str(item.get("motivo") or ""),
                            resource_id=item.get("idRecurso"),
                            expediente=str(item.get("Expedient") or item.get("expediente") or ""),
                            payload=item,
                        )
                    except Exception:
                        return

                candidates = adapter.fetch_candidates(
                    config=configs[adapter.site_id],
                    conn_str=self.sqlserver_conn_str,
                    authenticated_user=self.authenticated_user,
                    limit=9999,
                    on_discard=_on_discard,
                )
                if candidates:
                    return adapter.site_id
            except Exception as e:
                self.logger.error(f"[{adapter.site_id}] Error consultando candidatos remotos: {e}")

        return None

    async def run_tick(self) -> dict:
        """
        Ejecuta un tick del scheduler:
        - Recorre todos los sites habilitados (sin lock global).
        - Repone cola por site hasta su target.
        - Respeta el limite global MAX_CLAIMS_PER_CYCLE.
        """

        stats = {"claimed": 0, "enqueued": 0, "errors": 0, "per_site": {}}

        adapters, configs = self._get_enabled_adapters_and_configs()
        if not adapters:
            self.logger.warning("No hay adapters habilitados/configurados (revisa organismo_config + BRAIN_ENABLED_SITES)")
            return stats

        remaining_claim_budget = MAX_CLAIMS_PER_CYCLE

        for adapter in adapters:
            if remaining_claim_budget <= 0:
                break

            site_id = adapter.site_id
            config = configs.get(site_id)
            if not config:
                self.logger.warning(f"[{site_id}] Sin config activa; saltando.")
                continue

            # Agresivo: No miramos queue_depth ni slots. Pillamos todo.
            self.logger.info(f"[{site_id}] Refill AGRESIVO: Buscando todos los recursos disponibles.")

            # self.logger.info(
            #     f"[{site_id}] Refill: queue_depth={queue_depth} target={adapter.target_queue_depth} batch={site_limit}"
            # )

            try:
                await self.init_session(config["login_url"])
                def _on_discard(item: dict) -> None:
                    try:
                        self._record_incident_once(
                            site_id=str(item.get("site_id") or site_id),
                            incident_type=str(item.get("tipo_incidencia") or "SITE_RULE_DISCARDED"),
                            reason=str(item.get("motivo") or ""),
                            resource_id=item.get("idRecurso"),
                            expediente=str(item.get("Expedient") or item.get("expediente") or ""),
                            payload=item,
                        )
                    except Exception:
                        return

                candidates = adapter.fetch_candidates(
                    config=config,
                    conn_str=self.sqlserver_conn_str,
                    authenticated_user=self.authenticated_user,
                    limit=9999,
                    on_discard=_on_discard,
                )
                if not candidates:
                    self.logger.info(f"[{site_id}] Sin candidatos remotos validos.")
                    continue

                filtered_candidates: list[dict] = []
                skipped_duplicates = 0
                skipped_blocked = 0
                for cand in candidates:
                    rid = cand.get("idRecurso")
                    try:
                        rid_int = int(rid)
                    except Exception:
                        rid_int = None

                    if rid_int is not None:
                        if self._is_resource_blocked(site_id=site_id, resource_id=rid_int):
                            skipped_blocked += 1
                            continue
                        # Si ya existe en la cola local, saltar (Esto se verifica dentro de enqueue_locally o por duplicidad)
                        filtered_candidates.append(cand)
                
                if skipped_duplicates > 0:
                    self.logger.info(f"[{site_id}] {skipped_duplicates} duplicados omitidos ya presentes en la cola.")
                if skipped_blocked > 0:
                    self.logger.info(f"[{site_id}] {skipped_blocked} recursos bloqueados omitidos (retry agotado previo).")
                
                if not filtered_candidates:
                    continue

                payloads = await adapter.build_payloads(filtered_candidates, on_discard=_on_discard)
                per_site = stats["per_site"].setdefault(
                    site_id,
                    {"ready": 0, "pending_authorization": 0, "duplicates": 0, "claimed": 0, "errors": 0},
                )
                
                for payload in payloads:
                    if remaining_claim_budget <= 0:
                        break

                    rid = int(payload["idRecurso"])
                    exp = str(payload.get("expediente") or "")

                    # CLAIM
                    if await adapter.ensure_claimed(self, payload):
                        # ENQUEUE
                        enqueue_res = await self.enqueue_locally(site_id, payload)
                        stats["claimed"] += 1
                        per_site["claimed"] += 1
                        if enqueue_res.queue == "ready" and enqueue_res.enqueued:
                            stats["enqueued"] += 1
                            per_site["ready"] += 1
                        elif enqueue_res.queue == "pending_authorization":
                            stats["enqueued"] += 1
                            per_site["pending_authorization"] += 1
                        else:
                            per_site["duplicates"] += 1
                        remaining_claim_budget -= 1
                    else:
                        stats["errors"] += 1
                        per_site["errors"] += 1

            except Exception as e:
                self.logger.exception(f"[{site_id}] Error en ciclo de reposicion: {e}")
                stats["errors"] += 1
            finally:
                await self.close_session()

        if stats["per_site"]:
            for site_id, s in stats["per_site"].items():
                self.logger.info(
                    "[%s] Encolados: ready=%s pending_auth=%s duplicados=%s claimed=%s errors=%s",
                    site_id,
                    s.get("ready", 0),
                    s.get("pending_authorization", 0),
                    s.get("duplicates", 0),
                    s.get("claimed", 0),
                    s.get("errors", 0),
                )

        return stats

    async def run_cycle(self) -> dict:
        """
        Ejecuta un ciclo completo de sincronizaciÃ³n.
        
        Returns:
            Dict con estadÃ­sticas: claimed, enqueued, errors
        """
        stats = {"claimed": 0, "enqueued": 0, "errors": 0, "per_site": {}}
        
        # 1. Obtener configuraciones activas y habilitadas
        enabled_sites = _parse_enabled_sites(ENABLED_SITES_CSV)
        active_configs = self.get_active_configs()
        
        if enabled_sites is not None:
            active_configs = [c for c in active_configs if c["site_id"] in enabled_sites]
            
        if not active_configs:
            self.logger.warning("No hay organismos habilitados en BRAIN_ENABLED_SITES o configuraciones activas")
            return stats

        # 2. Elegir el sitio a reponer segÃºn prioridad y estado de la cola
        adapters, configs = self._get_enabled_adapters_and_configs()
        site_to_refill = await self._choose_site_to_refill(adapters, configs)
        
        if not site_to_refill:
            self.logger.info("Nada que hacer en este ciclo (sin candidatos).")
            return stats
        config = configs[site_to_refill]
        adapter = self.adapters[site_to_refill]
        
        self.logger.info(f"--- Iniciando sincronizaciÃ³n para {site_to_refill} ---")
        
        try:
            # 3. Inicializar sesiÃ³n y login
            await self.init_session(config["login_url"])
            if not self.session and not self.dry_run:
                self.logger.error("No se pudo establecer sesiÃ³n")
                return stats
            
            # Agresivo: Pillamos todo sin mirar slots ni presupuesto
            fetch_limit = 9999
            
            self.logger.info(f"Buscando todos los recursos para {site_to_refill} (AGRESIVO)...")
                
            self.logger.info(f"Buscando hasta {fetch_limit} recursos para {site_to_refill}...")
            def _on_discard(item: dict) -> None:
                try:
                    self._record_incident_once(
                        site_id=str(item.get("site_id") or site_to_refill),
                        incident_type=str(item.get("tipo_incidencia") or "SITE_RULE_DISCARDED"),
                        reason=str(item.get("motivo") or ""),
                        resource_id=item.get("idRecurso"),
                        expediente=str(item.get("Expedient") or item.get("expediente") or ""),
                        payload=item,
                    )
                except Exception:
                    return

            candidates = adapter.fetch_candidates(
                config=config, 
                conn_str=self.sqlserver_conn_str,
                authenticated_user=self.authenticated_user,
                limit=fetch_limit,
                on_discard=_on_discard,
            )
            filtered_candidates = []
            skipped_blocked = 0
            for cand in candidates:
                rid = cand.get("idRecurso")
                if self._is_resource_blocked(site_id=site_to_refill, resource_id=rid):
                    skipped_blocked += 1
                    continue
                filtered_candidates.append(cand)
            if skipped_blocked > 0:
                self.logger.info(f"[{site_to_refill}] {skipped_blocked} recursos bloqueados omitidos (retry agotado previo).")
            candidates = filtered_candidates
            
            if not candidates:
                self.logger.info(f"No hay recursos adicionales para {site_to_refill}")
                return stats
            
            # 5. Construir payloads (usando el adapter)
            payloads = await adapter.build_payloads(candidates, on_discard=_on_discard)
            per_site = stats["per_site"].setdefault(
                site_to_refill,
                {"ready": 0, "pending_authorization": 0, "duplicates": 0, "claimed": 0, "errors": 0},
            )
            
            # 6. Reclamar y encolar
            for payload in payloads:
                id_recurso = int(payload["idRecurso"])
                expediente = payload.get("expediente") or payload.get("denuncia_num")
                
                # Reclamar recurso (asegurando estado 1)
                # Note: adapter.ensure_claimed ya maneja el claim si es necesario
                if await adapter.ensure_claimed(self, payload):
                    # Encolar localmente (esto incluye el check de GESDOC)
                    enqueue_res = await self.enqueue_locally(site_to_refill, payload)
                    stats["claimed"] += 1
                    per_site["claimed"] += 1
                    if enqueue_res.queue == "ready" and enqueue_res.enqueued:
                        stats["enqueued"] += 1
                        per_site["ready"] += 1
                    elif enqueue_res.queue == "pending_authorization":
                        stats["enqueued"] += 1
                        per_site["pending_authorization"] += 1
                    else:
                        per_site["duplicates"] += 1
                else:
                    stats["errors"] += 1
                    per_site["errors"] += 1
                    self.logger.error(f"Error reclamando recurso {id_recurso} ({expediente})")
                    
        except Exception as e:
            self.logger.exception(f"Error crÃ­tico en ciclo de sincronizaciÃ³n de {site_to_refill}: {e}")
            stats["errors"] += 1
        finally:
            await self.close_session()

        if stats["per_site"]:
            for site_id, s in stats["per_site"].items():
                self.logger.info(
                    "[%s] Encolados: ready=%s pending_auth=%s duplicados=%s claimed=%s errors=%s",
                    site_id,
                    s.get("ready", 0),
                    s.get("pending_authorization", 0),
                    s.get("duplicates", 0),
                    s.get("claimed", 0),
                    s.get("errors", 0),
                )

        return stats

    async def run_forever(self) -> None:
        """Bucle infinito del orquestador."""
        self.logger.info(f"=== Brain Orchestrator Iniciado (Sync: {SYNC_INTERVAL_SECONDS}s, Budget: {MAX_CLAIMS_PER_CYCLE}) ===")
        self.logger.info(f"Adapters habilitados: {', '.join(self.adapters.keys())}")
        
        while True:
            try:
                # En lugar de run_cycle (1 solo site), usamos run_tick (todos los sites hasta presupuesto)
                await self.run_tick()
                self.logger.info(f"Proximo tick en {SYNC_INTERVAL_SECONDS} segundos...")
            except KeyboardInterrupt:
                self.logger.info("Deteniendo brain por interrupcion de teclado (Ctrl+C)...")
                break
            except Exception as e:
                self.logger.error(f"Error inesperado en el bucle principal: {e}")
            
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
        stats = asyncio.run(orchestrator.run_tick())
        print(f"Ciclo completado: {stats}")
    else:
        asyncio.run(orchestrator.run_forever())


if __name__ == "__main__":
    main()

