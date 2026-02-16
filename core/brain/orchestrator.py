import asyncio
import logging
import os
import re
import sys
import uuid
import signal
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
from sites.adapters import MadridAdapter, XalocAdapter, BaseOnlineAdapter, AyuntaPalmaAdapter
from sites.adapters.site_adapter import SiteAdapter

load_dotenv()

SYNC_INTERVAL_SECONDS = int(os.getenv("BRAIN_SYNC_INTERVAL", 500))
TICK_INTERVAL_SECONDS = int(os.getenv("BRAIN_TICK_SECONDS", 5))
MAX_CLAIMS_PER_CYCLE = int(os.getenv("BRAIN_MAX_CLAIMS", 999999))
BRAIN_TARGET_QUEUE_DEPTH = int(os.getenv("BRAIN_TARGET_QUEUE_DEPTH", 50))
ENABLED_SITES_CSV = os.getenv("BRAIN_ENABLED_SITES", "").strip()
QUEUE_BACKEND = (os.getenv("QUEUE_BACKEND", "sqlite") or "sqlite").strip().lower()

XVIA_EMAIL = os.getenv("XVIA_EMAIL")
XVIA_PASSWORD = os.getenv("XVIA_PASSWORD")
ASIGNAR_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/AsignarA"

logger = logging.getLogger("brain")

@dataclass
class EnqueueResult:
    job_id: str
    enqueued: bool
    queue: str  # "ready", "pending_authorization", "duplicate"

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

SITE_PRIORITIES: dict[str, int] = {
    "madrid": 0,
    "xaloc_girona": 1,
    "base_online": 2,
    "ayunta_palma": 3,
}

# Limites por sitio para recursos reclamados/encolados por tick.
# Temporalmente en Palma solo se procesa 1 recurso por ciclo.
SITE_CLAIM_LIMIT_PER_TICK: dict[str, int] = {
    "ayunta_palma": 1,
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
            "ayunta_palma": AyuntaPalmaAdapter(),
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

    def _extract_csrf_token(self, html: str) -> Optional[str]:
        """
        Extrae el token CSRF del HTML tolerando variaciones de comillas/orden.
        """
        if not html:
            return None

        patterns = [
            r'name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']',
            r'value=["\']([^"\']+)["\'][^>]*name=["\']_token["\']',
            r'"_token"\s*:\s*"([^"]+)"',
            r"'_token'\s*:\s*'([^']+)'",
        ]
        for pattern in patterns:
            m = re.search(pattern, html, flags=re.IGNORECASE)
            if m:
                token = (m.group(1) or "").strip()
                if token:
                    return token
        return None

    async def init_session(self, login_url: str) -> None:
        """Inicializa sesiÃ³n aiohttp y realiza login en Xvia."""
        if self.dry_run:
            self.logger.info("[DRY-RUN] Saltando inicializaciÃ³n de sesiÃ³n")
            return

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

            self.authenticated_user = await self.get_authenticated_username()
            if self.authenticated_user:
                self.logger.info(f"âœ“ Usuario autenticado: {self.authenticated_user}")
            else:
                self.logger.warning("âš ï¸  No se pudo obtener el nombre del usuario autenticado")

        except Exception as e:
            await self.session.close()
            self.session = None
            raise RuntimeError(f"Error en autenticaciÃ³n: {e}")

    async def get_authenticated_username(self) -> Optional[str]:
        if not self.session:
            return None
        try:
            async with self.session.get("http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/home") as resp:
                html = await resp.text()
                match = re.search(r'<i class="fa fa-user-circle"[^>]*></i>\s*([^<]+)', html)
                if match:
                    username = match.group(1).strip()
                    return username
                return None
        except Exception as e:
            self.logger.error(f"Error obteniendo nombre de usuario: {e}")
            return None

    async def close_session(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    def get_active_configs(self) -> list[dict]:
        return self.db.get_active_organismo_configs()

    def fetch_remote_resources(self, config: dict, limit: int = 9999) -> list[dict]:
        if limit <= 0:
            return []

        texp_values = [int(x.strip()) for x in config["filtro_texp"].split(",")]
        texp_placeholders = ",".join(["?"] * len(texp_values))

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
                if len(results) >= limit:
                    break

                record = dict(zip(columns, row))
                expediente = record.get("Expedient", "")

                if expediente and regex.match(expediente):
                    results.append(record)
                else:
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
                                f"â Œ Expediente NT/ no corregible: {expediente}"
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

    async def claim_resource_via_post(
        self,
        id_recurso: int,
        expediente: str
    ) -> bool:
        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Claim simulado para idRecurso={id_recurso}")
            return True

        if not self.session:
            self.logger.error("SesiÃ³n no inicializada")
            return False

        try:
            async with self.session.get(
                "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
            ) as resp:
                html = await resp.text()
                csrf_token = self._extract_csrf_token(html)
                if not csrf_token:
                    self.logger.error("No se pudo obtener el token CSRF del HTML")
                    return False

            form_data = {
                "_token": csrf_token,
                "id": str(id_recurso),
                "recursosSel": "0"
            }

            self.logger.info(f"Enviando claim para idRecurso={id_recurso}")

            async with self.session.post(ASIGNAR_URL, data=form_data) as resp:
                if resp.status in (200, 302, 303):
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
                csrf_token = self._extract_csrf_token(html)
                if not csrf_token:
                    self.logger.error("No se pudo obtener el token CSRF del HTML")
                    return False

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
                usuario_db = str(usuario or "").strip()
                nuestro_usuario = str(self.authenticated_user or "").strip()
                is_claimed = (estado == 1) and (usuario_db == nuestro_usuario)

                if is_claimed:
                    self.logger.info(f"âœ… Claim verificado: Estado={estado}, Usuario='{usuario_db}'")
                    return True
                else:
                    self.logger.warning(f"âš ï¸  Claim NO verificado: TExp={texp}, Estado={estado}, Usuario='{usuario_db}' (Esperado: Estado=1, Usuario='{nuestro_usuario}')")
            return False
        except Exception as e:
            self.logger.error(f"Error verificando claim en DB: {e}")
            return False

    def _convert_value(self, v):
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
        if v is None:
            return None
        return v

    def build_payload(self, recurso: dict, config: dict) -> dict:
        import json
        import re
        import unicodedata
        from pathlib import Path

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

        config_path = Path("config_motivos.json")
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                motivos_config = json.load(f)
        else:
            motivos_config = {}

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
            cif_doc, cif_ctrl = _extraer_documento_control(cif) if cif else ("", "")
            mandatario = {
                "tipo_persona": "JURIDICA",
                "razon_social": empresa,
                "cif_documento": cif_doc,
                "cif_control": cif_ctrl
            }
        else:
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

        return {
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
            "empresa": empresa,
            "cliente_nombre": _clean_str(recurso.get("cliente_nombre")),
            "cliente_apellido1": _clean_str(recurso.get("cliente_apellido1")),
            "cliente_apellido2": _clean_str(recurso.get("cliente_apellido2")),
            "source": "brain_orchestrator",
            "claimed_at": datetime.now().isoformat()
        }

    async def enqueue_locally(self, site_id: str, payload: dict) -> EnqueueResult:
        job_id = str(payload.get("job_id") or uuid.uuid4())
        payload["job_id"] = job_id
        protocol = payload.get("protocol") or payload.get("naturaleza")

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Encolado simulado: {payload['expediente']} (Protocol: {protocol})")
            return EnqueueResult(job_id=job_id, enqueued=True, queue="ready")

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

        enqueued, queued_job_id = await self.queue_gateway.enqueue(site_id=site_id, protocol=protocol, payload=payload)
        if enqueued:
            self.logger.info(f"Tarea {queued_job_id} encolada: {payload['expediente']} -> {site_id}")
        else:
            self.logger.info(f"Tarea duplicada omitida: {payload['expediente']} -> {site_id}")
        return EnqueueResult(job_id=queued_job_id, enqueued=enqueued, queue=("ready" if enqueued else "duplicate"))

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

            current_depth = self.db.count_job_runs(site_id=site_id, states=("queued", "processing"))

            target_depth = int(os.getenv(f"BRAIN_TARGET_QUEUE_DEPTH_{site_id.upper()}", BRAIN_TARGET_QUEUE_DEPTH))

            refill_amount = target_depth - current_depth
            if refill_amount <= 0:
                self.logger.info(f"[{site_id}] Cola llena (depth={current_depth}/{target_depth}). Saltando refill.")
                continue

            site_claim_limit = SITE_CLAIM_LIMIT_PER_TICK.get(site_id)
            site_claims_done = 0

            fetch_limit = min(refill_amount, 9999)
            if site_claim_limit is not None:
                fetch_limit = min(fetch_limit, max(0, site_claim_limit))
                if fetch_limit <= 0:
                    self.logger.info(f"[{site_id}] Limite por sitio agotado para este tick.")
                    continue
            self.logger.info(f"[{site_id}] Refill: depth={current_depth}/{target_depth} -> fetch_limit={fetch_limit}")

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
                    limit=fetch_limit,
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
                    if site_claim_limit is not None and site_claims_done >= site_claim_limit:
                        self.logger.info(f"[{site_id}] Limite por sitio alcanzado ({site_claim_limit}) en este tick.")
                        break

                    rid = int(payload["idRecurso"])
                    exp = str(payload.get("expediente") or "")

                    if await adapter.ensure_claimed(self, payload):
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
                        site_claims_done += 1
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

    async def run_forever(self) -> None:
        self.logger.info(f"=== Brain Orchestrator Iniciado (Sync: {SYNC_INTERVAL_SECONDS}s, Budget: {MAX_CLAIMS_PER_CYCLE}) ===")
        self.logger.info(f"Adapters habilitados: {', '.join(self.adapters.keys())}")

        shutdown_event = asyncio.Event()

        def _signal_handler():
            self.logger.info("Señal de parada recibida (SIGINT/SIGTERM). Iniciando shutdown ordenado...")
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        if os.name != "nt":
            try:
                loop.add_signal_handler(signal.SIGTERM, _signal_handler)
                loop.add_signal_handler(signal.SIGINT, _signal_handler)
            except NotImplementedError:
                pass

        while not shutdown_event.is_set():
            try:
                await self.run_tick()
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=SYNC_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                shutdown_event.set()
                break
            except KeyboardInterrupt:
                self.logger.info("Deteniendo brain por interrupcion de teclado (Ctrl+C)...")
                shutdown_event.set()
                break
            except Exception as e:
                self.logger.error(f"Error inesperado en el bucle principal: {e}")
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

        await self.close_session()
        self.logger.info("Brain finalizado correctamente.")
