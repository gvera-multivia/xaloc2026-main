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
from typing import Any, Optional

import aiohttp
import pyodbc
from dotenv import load_dotenv

from core.sqlite_db import SQLiteDatabase
from core.xvia_auth import create_authenticated_session_in_place
from core.nt_expediente_fixer import is_nt_pattern, fix_nt_expediente
from core.client_documentation import check_requires_gesdoc
from core.address_classifier import classify_addresses_batch_with_ai, classify_address_fallback


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

load_dotenv()

SYNC_INTERVAL_SECONDS = int(os.getenv("BRAIN_SYNC_INTERVAL", 300))
TICK_INTERVAL_SECONDS = int(os.getenv("BRAIN_TICK_SECONDS", 5))
MAX_CLAIMS_PER_CYCLE = int(os.getenv("BRAIN_MAX_CLAIMS", 50))
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "db/xaloc_database.db")
ENABLED_SITES_CSV = os.getenv("BRAIN_ENABLED_SITES", "").strip()

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
    rs.FaseProcedimiento,
    -- Campos para identificación del cliente (GESDOC check)
    rs.Empresa,
    rs.cif,
    c.Nombrefiscal,
    c.nifempresa,
    c.nif AS cliente_nif,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    -- Campo matrícula desde expedientes
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
# ADAPTERS Y POLÍTICAS
# =============================================================================

SITE_PRIORITIES: dict[str, int] = {
    "madrid": 0,
    "base_online": 1,
}


def _parse_enabled_sites(csv_value: str) -> Optional[set[str]]:
    value = (csv_value or "").strip()
    if not value:
        return None
    items = [p.strip() for p in value.split(",")]
    return {p for p in items if p}


class SiteAdapter:
    site_id: str
    priority: int
    target_queue_depth: int
    max_refill_batch: int

    def __init__(self, *, site_id: str, priority: int, target_queue_depth: int, max_refill_batch: int):
        self.site_id = site_id
        self.priority = priority
        self.target_queue_depth = target_queue_depth
        self.max_refill_batch = max_refill_batch

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
    ) -> list[dict]:
        raise NotImplementedError

    async def ensure_claimed(self, orchestrator: "BrainOrchestrator", candidate: dict) -> bool:
        estado = int(candidate.get("Estado") or 0)
        if estado == 1:
            return True
        return await orchestrator.claim_resource_with_retries(
            id_recurso=int(candidate["idRecurso"]),
            expediente=str(candidate.get("Expedient") or ""),
        )

    async def build_payloads(self, candidates: list[dict]) -> list[dict]:
        raise NotImplementedError


class MadridAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )

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
    rs.notas,
    rs.matricula AS rs_matricula,

    e.matricula,
    e.Idpublic AS exp_idpublic,

    pe.publicación AS pub_publicacion,

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
    c.numero AS cliente_numero,
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
LEFT JOIN pubExp pe ON pe.Idpublic = e.Idpublic
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id
WHERE {organisme_like_clause}
  AND rs.TExp IN ({texp_list})
  AND rs.Estado IN (0, 1)
  AND rs.Expedient IS NOT NULL
ORDER BY rs.Estado ASC, rs.idRecurso ASC
"""

    def __init__(self):
        super().__init__(site_id="madrid", priority=0, target_queue_depth=2, max_refill_batch=5)
        self._regex_madrid = re.compile(r"^(\d{3}/\d{9}\.\d|\d{9}\.\d)$")

    @staticmethod
    def _clean_str(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _normalize_text(text: Any) -> str:
        import unicodedata

        if not text:
            return ""
        t = str(text).strip().lower()
        return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
    ) -> list[dict]:
        texp_values = [2, 3]
        texp_placeholders = ",".join(["?"] * len(texp_values))
        
        # Manejar múltiples patrones LIKE (separados por espacios)
        query_organisme_raw = config.get("query_organisme", "%")
        patterns = [p.strip() for p in query_organisme_raw.split(" ") if p.strip()]
        
        if not patterns:
            patterns = ["%"]
        
        like_clauses = ["rs.Organisme LIKE ?"] * len(patterns)
        organisme_like_clause = " AND ".join(like_clauses)
        
        query = self.SQL_FETCH_RECURSOS_MADRID.format(
            organisme_like_clause=organisme_like_clause,
            texp_list=texp_placeholders
        )

        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(query, patterns + texp_values)
            columns = [column[0] for column in cursor.description]

            recursos_map: dict[int, dict] = {}
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                rid = record.get("idRecurso")
                if not rid:
                    continue
                rid_int = int(rid)

                if rid_int not in recursos_map:
                    recursos_map[rid_int] = {**record, "adjuntos": []}

                adj_id = record.get("adjunto_id")
                if adj_id:
                    filename = self._clean_str(record.get("adjunto_filename"))
                    if filename:
                        recursos_map[rid_int]["adjuntos"].append(
                            {
                                "id": int(adj_id),
                                "filename": filename,
                                "url": self.ADJUNTO_URL_TEMPLATE.format(id=int(adj_id)),
                            }
                        )

            out: list[dict] = []
            for _, recurso in recursos_map.items():
                if limit and len(out) >= limit:
                    break

                expediente = self._clean_str(recurso.get("Expedient")).upper()
                if not expediente or not self._regex_madrid.match(expediente):
                    continue

                fase_norm = self._normalize_text(recurso.get("FaseProcedimiento"))
                if any(x in fase_norm for x in ["reclamacion", "embargo", "apremio"]):
                    continue

                estado = int(recurso.get("Estado") or 0)
                usuario = self._clean_str(recurso.get("UsuarioAsignado"))
                if estado == 1 and authenticated_user and usuario != authenticated_user:
                    continue
                if estado == 1 and not authenticated_user:
                    continue

                out.append(recurso)

            return out
        finally:
            conn.close()

    @staticmethod
    def _inferir_prefijo_expediente(*, fase_raw: str, es_empresa: bool) -> str:
        fase_norm = MadridAdapter._normalize_text(fase_raw)
        if "identificacion" in fase_norm:
            return "911" if es_empresa else "912"
        if "denuncia" in fase_norm:
            return "911" if es_empresa else "912"
        if "sancion" in fase_norm or "resolucion" in fase_norm:
            return "931" if es_empresa else "935"
        return "935"

    @staticmethod
    def _parse_expediente(expediente: str, *, fase_raw: str = "", es_empresa: bool = False) -> dict:
        exp = MadridAdapter._clean_str(expediente).upper()

        m1 = re.match(r"^(?P<nnn>\d{3})/(?P<exp>\d{9})\.(?P<d>\d)$", exp)
        if m1:
            return {
                "expediente_completo": exp,
                "expediente_tipo": "opcion1",
                "expediente_nnn": m1.group("nnn"),
                "expediente_eeeeeeeee": m1.group("exp"),
                "expediente_d": m1.group("d"),
                "expediente_lll": "",
                "expediente_aaaa": "",
                "expediente_exp_num": "",
            }

        m3 = re.match(r"^(?P<exp>\d{9})\.(?P<d>\d)$", exp)
        if m3:
            prefijo = MadridAdapter._inferir_prefijo_expediente(fase_raw=fase_raw, es_empresa=es_empresa)
            exp_reconstruido = f"{prefijo}/{exp}"
            return {
                "expediente_completo": exp_reconstruido,
                "expediente_tipo": "opcion1",
                "expediente_nnn": prefijo,
                "expediente_eeeeeeeee": m3.group("exp"),
                "expediente_d": m3.group("d"),
                "expediente_lll": "",
                "expediente_aaaa": "",
                "expediente_exp_num": "",
            }

        return {
            "expediente_completo": exp,
            "expediente_tipo": "",
            "expediente_nnn": "",
            "expediente_eeeeeeeee": "",
            "expediente_d": "",
            "expediente_lll": "",
            "expediente_aaaa": "",
            "expediente_exp_num": "",
        }

    @staticmethod
    def _load_motivos_config() -> dict:
        try:
            path = Path("config_motivos.json")
            if not path.exists():
                return {}
            import json as _json

            return _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _build_expone_solicita(fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str, str]:
        config = MadridAdapter._load_motivos_config()
        fase_norm = MadridAdapter._normalize_text(fase_raw)

        selected: dict | None = None
        selected_key = ""
        for key, value in (config or {}).items():
            key_norm = MadridAdapter._normalize_text(key)
            if key_norm and key_norm in fase_norm:
                selected = value
                selected_key = key
                break

        asunto = ""
        expone = ""
        solicita = ""
        if selected:
            asunto = MadridAdapter._clean_str(selected.get("asunto")).replace("{expediente}", expediente).replace(
                "{sujeto_recurso}", sujeto
            )
            expone = MadridAdapter._clean_str(selected.get("expone")).replace("{expediente}", expediente).replace(
                "{sujeto_recurso}", sujeto
            )
            solicita = (
                MadridAdapter._clean_str(selected.get("solicita"))
                .replace("{expediente}", expediente)
                .replace("{sujeto_recurso}", sujeto)
            )

        selected_key_norm = MadridAdapter._normalize_text(selected_key)
        blob = " ".join(
            [
                selected_key_norm,
                fase_norm,
                MadridAdapter._normalize_text(asunto),
                MadridAdapter._normalize_text(expone),
                MadridAdapter._normalize_text(solicita),
            ]
        )

        # Naturaleza del escrito:
        # - "A": Alegación
        # - "R": Recurso (incluye Resolución sancionadora, Apremio, Embargo, etc.)
        # - "I": Identificación del conductor
        #
        # Regla: si hay match en config_motivos, preferimos mapping por key para evitar falsos positivos
        # (p.ej. "propuesta de resolucion" puede contener la palabra "recurso" en el texto).
        naturaleza = "A"
        if selected_key_norm in {"identificacion"} or "identificacion" in blob:
            naturaleza = "I"
        elif selected_key_norm in {"denuncia", "propuesta de resolucion", "subsanacion"}:
            naturaleza = "A"
        elif selected_key_norm in {
            "sancion",
            "apremio",
            "embargo",
            "reclamaciones",
            "requerimiento embargo",
            "extraordinario de revision",
        }:
            naturaleza = "R"
        elif any(
            tag in blob
            for tag in [
                "recurso",
                "reposicion",
                "reclamacion",
                "revision",
                "apremio",
                "embargo",
                "resolucion sancionadora",
                "sancion",
            ]
        ):
            naturaleza = "R"

        if not (asunto and expone and solicita):
            asunto = asunto or f"Recurso expediente {expediente}"
            expone = expone or "..."
            solicita = solicita or "..."

        return expone, solicita, naturaleza

    @staticmethod
    def _resolve_plate_number(recurso: dict) -> tuple[str, str]:
        # 1. Prioridad: Tabla recursosexp (rs.matricula)
        plate_rs = MadridAdapter._clean_str(recurso.get("rs_matricula"))
        if plate_rs:
            return re.sub(r"\s+", "", plate_rs).upper(), "Recursos.RecursosExp.matricula"

        # 2. Prioridad: Tabla expedientes (e.matricula)
        plate_exp = MadridAdapter._clean_str(recurso.get("matricula"))
        if plate_exp:
            return re.sub(r"\s+", "", plate_exp).upper(), "expedientes.matricula"

        # 3. Regex en texto (Publicación o Notas)
        # Regex mejorada que permite espacios y guiones opcionales pero respeta word boundaries
        regex = r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4}[\s-]*[A-Z]{1,2})\b"

        def _try_extract(text: str, source_name: str) -> tuple[str, str] | None:
            if not text:
                return None
            m = re.search(regex, text.upper())
            if m:
                # Limpiar la matrícula encontrada de espacios y guiones
                clean_plate = m.group(1).replace(" ", "").replace("-", "")
                return clean_plate, source_name
            return None

        # 3.a Publicación
        res_pub = _try_extract(MadridAdapter._clean_str(recurso.get("pub_publicacion")), "pubExp.publicación")
        if res_pub:
            return res_pub

        # 3.b Notas
        res_notas = _try_extract(MadridAdapter._clean_str(recurso.get("notas")), "rs.notas")
        if res_notas:
            return res_notas

        return "", ""

    @staticmethod
    def _detectar_tipo_documento(doc: str) -> str:
        if not doc:
            return "NIF"
        d = doc.strip().upper()
        if re.match(r"^[A-Z]{3}[0-9]+", d):
            return "PS"
        return "NIF"

    @staticmethod
    def _convert_value(v: Any) -> Any:
        from decimal import Decimal

        if isinstance(v, Decimal):
            return float(v)
        return v

    @staticmethod
    def _prevalidate_required_fields(payload: dict) -> None:
        required = [
            "idRecurso",
            "expediente_tipo",
            "naturaleza",
            "expone",
            "solicita",
            "rep_tipo_via",
            "rep_tipo_numeracion",
            "rep_cp",
            "rep_municipio",
            "rep_provincia",
            "rep_pais",
            "notif_tipo_documento",
            "notif_numero_documento",
            "notif_name",
            "notif_surname1",
            "notif_pais",
            "notif_provincia",
            "notif_municipio",
            "notif_tipo_via",
            "notif_nombre_via",
            "notif_tipo_numeracion",
            "notif_codigo_postal",
        ]
        missing = [k for k in required if not str(payload.get(k) or "").strip()]
        if payload.get("notif_tipo_numeracion") == "NUM" and not str(payload.get("notif_numero") or "").strip():
            missing.append("notif_numero")
        if missing:
            raise ValueError(f"Payload Madrid inválido, faltan campos: {', '.join(sorted(set(missing)))}")

    async def build_payloads(self, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []

        items: list[dict] = []
        for r in candidates:
            items.append(
                {
                    "idRecurso": r.get("idRecurso"),
                    "direccion_raw": self._clean_str(r.get("cliente_domicilio")),
                    "poblacion": self._clean_str(r.get("cliente_municipio")),
                    "numero": self._clean_str(r.get("cliente_numero")),
                    "piso": self._clean_str(r.get("cliente_planta")),
                    "puerta": self._clean_str(r.get("cliente_puerta")),
                }
            )

        batch_mapping: dict[str, dict] = {}
        if os.getenv("GROQ_API_KEY"):
            try:
                batch_mapping = await classify_addresses_batch_with_ai(items)
            except Exception as e:
                logger.warning("[MADRID][IA] Falló batch LLM, usando fallback local: %s", e)
                batch_mapping = {}

        payloads: list[dict] = []
        for r in candidates:
            expediente_raw = self._clean_str(r.get("Expedient")).upper()
            cif_empresa = self._clean_str(r.get("cif"))
            nif = cif_empresa or self._clean_str(r.get("cliente_nif"))
            fase_raw = self._clean_str(r.get("FaseProcedimiento"))

            exp_parts = self._parse_expediente(expediente_raw, fase_raw=fase_raw, es_empresa=bool(cif_empresa))
            expediente_para_textos = exp_parts.get("expediente_completo", expediente_raw)

            expone, solicita, naturaleza = self._build_expone_solicita(
                fase_raw,
                expediente_para_textos,
                self._clean_str(r.get("SujetoRecurso")),
            )

            plate_number, plate_src = self._resolve_plate_number(r)

            rid = str(r.get("idRecurso"))
            clasif = batch_mapping.get(rid)
            domicilio_raw = self._clean_str(r.get("cliente_domicilio"))
            numero_db = self._clean_str(r.get("cliente_numero"))
            poblacion = self._clean_str(r.get("cliente_municipio"))
            piso_db = self._clean_str(r.get("cliente_planta"))
            puerta_db = self._clean_str(r.get("cliente_puerta"))
            escalera_db = self._clean_str(r.get("cliente_escalera"))

            if not clasif:
                clasif = classify_address_fallback(domicilio_raw)

            notif_tipo_via = (clasif.get("tipo_via") or "CALLE").upper()
            notif_nombre_via = (clasif.get("calle") or "").upper()
            notif_numero = (clasif.get("numero") or numero_db).upper()
            notif_escalera = ((clasif.get("escalera") or escalera_db) or "").upper()
            notif_planta = ((clasif.get("planta") or piso_db) or "").upper()
            notif_puerta = ((clasif.get("puerta") or puerta_db) or "").upper()

            tipo_numeracion = "NUM" if self._clean_str(notif_numero) else "S/N"
            provincia_notif = self._clean_str(r.get("cliente_provincia")).upper() or poblacion.upper()

            representante = {
                "rep_tipo_via": "RONDA",
                "rep_tipo_numeracion": "NUM",
                "representative_city": "BARCELONA",
                "representative_province": "BARCELONA",
                "representative_country": "ESPAÑA",
                "representative_street": "GENERAL MITRE, DEL",
                "representative_number": "169",
                "representative_zip": "08022",
                "representative_email": "info@xvia-serviciosjuridicos.com",
                "representative_phone": "932531411",
                "rep_nombre_via": "GENERAL MITRE, DEL",
                "rep_numero": "169",
                "rep_cp": "08022",
                "rep_municipio": "BARCELONA",
                "rep_provincia": "BARCELONA",
                "rep_pais": "ESPAÑA",
                "rep_email": "info@xvia-serviciosjuridicos.com",
                "rep_movil": "932531411",
                "rep_telefono": "932531411",
                "rep_tipo_numeracion": "NUM",
            }

            payload = {
                "idRecurso": self._convert_value(r.get("idRecurso")),
                "idExp": self._convert_value(r.get("idExp")),
                "expediente": expediente_raw,
                "numclient": self._convert_value(r.get("numclient")),
                "sujeto_recurso": self._clean_str(r.get("SujetoRecurso")),
                "fase_procedimiento": fase_raw,

                "plate_number": plate_number,
                "plate_number_source": plate_src,

                "user_phone": "932531411",
                "inter_telefono": "932531411",
                "inter_email_check": bool(self._clean_str(r.get("cliente_email"))),

                **representante,

                "notif_tipo_documento": self._detectar_tipo_documento(nif),
                "notif_numero_documento": nif,
                "notif_name": self._clean_str(r.get("cliente_nombre")).upper(),
                "notif_surname1": self._clean_str(r.get("cliente_apellido1")).upper(),
                "notif_surname2": self._clean_str(r.get("cliente_apellido2")).upper(),
                "notif_razon_social": self._clean_str(r.get("cliente_razon_social")).upper(),
                "notif_pais": "ESPAÑA",
                "notif_provincia": provincia_notif,
                "notif_municipio": poblacion.upper(),
                "notif_tipo_via": notif_tipo_via,
                "notif_nombre_via": notif_nombre_via,
                "notif_tipo_numeracion": tipo_numeracion,
                "notif_numero": self._clean_str(notif_numero),
                "notif_portal": "",
                "notif_escalera": self._clean_str(notif_escalera),
                "notif_planta": self._clean_str(notif_planta),
                "notif_puerta": self._clean_str(notif_puerta),
                "notif_codigo_postal": self._clean_str(r.get("cliente_cp")),
                "notif_email": "info@xvia-serviciosjuridicos.com",
                "notif_movil": "",
                "notif_telefono": "932531411",

                **exp_parts,
                # Alias directos para el controller (evita depender de map_data)
                "exp_tipo": exp_parts.get("expediente_tipo"),
                "exp_nnn": exp_parts.get("expediente_nnn"),
                "exp_eeeeeeeee": exp_parts.get("expediente_eeeeeeeee"),
                "exp_d": exp_parts.get("expediente_d"),
                "exp_lll": exp_parts.get("expediente_lll"),
                "exp_aaaa": exp_parts.get("expediente_aaaa"),
                "exp_exp_num": exp_parts.get("expediente_exp_num"),
                "naturaleza": naturaleza,
                "expone": expone,
                "solicita": solicita,

                "adjuntos": r.get("adjuntos") or [],

                "source": "brain_orchestrator",
                "claimed_at": datetime.now().isoformat(),
            }

            self._prevalidate_required_fields(payload)
            payloads.append(payload)

        return payloads


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
        self.authenticated_user: Optional[str] = None

        self.adapters: dict[str, SiteAdapter] = {
            "madrid": MadridAdapter(),
        }
        
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
            
            # Obtener nombre del usuario autenticado
            self.authenticated_user = await self.get_authenticated_username()
            if self.authenticated_user:
                self.logger.info(f"✓ Usuario autenticado: {self.authenticated_user}")
            else:
                self.logger.warning("⚠️ No se pudo obtener el nombre del usuario autenticado")
                
        except Exception as e:
            await self.session.close()
            self.session = None
            raise RuntimeError(f"Error en autenticación: {e}")
            
    async def get_authenticated_username(self) -> Optional[str]:
        """Obtiene el nombre del usuario autenticado desde la página de Xvia."""
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
        
        # Manejar múltiples patrones LIKE (separados por espacios)
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
                                f"✅ Expediente NT/ corregido: '{expediente}' -> '{corrected}'"
                            )
                            record["Expedient"] = corrected
                            results.append(record)
                        else:
                            self.logger.warning(
                                f"❌ Expediente NT/ no corregible: {expediente}"
                            )
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
            # Siempre obtener token CSRF fresco de la página antes de cada POST
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

    async def post_claim_resource(self, id_recurso: int) -> bool:
        """
        Hace POST a /AsignarA (sin verificar en SQL Server).
        """
        if self.dry_run:
            return True

        if not self.session:
            self.logger.error("Sesión no inicializada")
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
                self.logger.info(f"✓ Recurso {id_recurso} ({expediente}) reclamado/verificado")
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
        - O UsuarioAsignado deja de estar vacío.
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
                # El claim es válido si el estado ha pasado a 1 y el usuario asignado es el nuestro
                # TExp debe ser 2 o 3 (el 1 y 4 no los hacemos)
                
                # Normalizamos el usuario para comparar
                usuario_db = str(usuario or "").strip()
                nuestro_usuario = str(self.authenticated_user or "").strip()
                
                is_claimed = (estado == 1) and (usuario_db == nuestro_usuario)
                
                if is_claimed:
                    self.logger.info(f"✅ Claim verificado: Estado={estado}, Usuario='{usuario_db}'")
                    return True
                else:
                    self.logger.warning(f"⚠️ Claim NO verificado: TExp={texp}, Estado={estado}, Usuario='{usuario_db}' (Esperado: Estado=1, Usuario='{nuestro_usuario}')")
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
        
        # --- Obtener motivos según fase ---
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
            self.logger.warning(f"No se encontró configuración de motivos para fase: {fase_raw}")
            motivos_text = f"ASUNTO: Recurso expediente {expediente}\n\nEXPONE: ...\n\nSOLICITA: ..."
        
        # --- Construir mandatario ---
        def _extraer_documento_control(documento: str) -> tuple:
            doc_clean = documento.strip().upper()
            if len(doc_clean) < 2:
                return ("", "")
            return (doc_clean[:-1], doc_clean[-1])
        
        def _detectar_tipo_documento(doc: str) -> str:
            if not doc:
                return "NIF"
            doc = doc.strip().upper()
            if re.match(r'^[A-Z]{3}[0-9]+', doc):
                return "PS"
            return "NIF"
        
        empresa = _clean_str(recurso.get("Empresa") or recurso.get("Nombrefiscal")).upper()
        cif = _clean_str(recurso.get("cif") or recurso.get("nifempresa")).upper()
        
        if empresa or cif:
            # Persona JURÍDICA
            cif_doc, cif_ctrl = _extraer_documento_control(cif) if cif else ("", "")
            mandatario = {
                "tipo_persona": "JURIDICA",
                "razon_social": empresa,
                "cif_documento": cif_doc,
                "cif_control": cif_ctrl
            }
        else:
            # Persona FÍSICA
            nif = _clean_str(recurso.get("cliente_nif")).upper()
            doc_num, doc_ctrl = _extraer_documento_control(nif) if nif else ("", "")
            tipo_doc = _detectar_tipo_documento(nif)
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
            # Campos adicionales para identificación
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
    def enqueue_locally(self, site_id: str, payload: dict) -> int:
        """
        Inserta la tarea en la cola apropiada.
        
        Si el caso requiere autorización GESDOC → pending_authorization_queue
        Si NO requiere GESDOC → tramite_queue (procesamiento normal)
        """
        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Encolado simulado: {payload['expediente']}")
            return -1
        
        # Verificar si requiere GESDOC antes de encolar
        requires_gesdoc, reason = check_requires_gesdoc(payload)
        
        if requires_gesdoc:
            # Enviar a cola de autorización pendiente
            self.logger.warning(f"⏸️ Requiere GESDOC: {payload['expediente']} - {reason}")
            pending_id = self.db.insert_pending_authorization(
                site_id=site_id,
                payload=payload,
                authorization_type="gesdoc",
                reason=reason
            )
            self.logger.info(
                f"📋 Tarea {pending_id} en pending_authorization_queue: {payload['expediente']}"
            )
            return pending_id
        
        # No requiere GESDOC → cola normal
        task_id = self.db.insert_task(site_id, None, payload)
        self.logger.info(
            f"📥 Tarea {task_id} encolada: {payload['expediente']} -> {site_id}"
        )
        return task_id
    
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

        # Lock global: si hay cualquier tarea pending/processing en cola, NO mezclar.
        locked = self.db.get_locked_site_by_priority(priorities)
        if locked:
            return locked

        for adapter in adapters:
            if adapter.site_id not in configs:
                continue
            try:
                candidates = adapter.fetch_candidates(
                    config=configs[adapter.site_id],
                    conn_str=self.sqlserver_conn_str,
                    authenticated_user=self.authenticated_user,
                    limit=1,
                )
                if candidates:
                    return adapter.site_id
            except Exception as e:
                self.logger.error(f"[{adapter.site_id}] Error consultando candidatos remotos: {e}")

        return None

    async def run_tick(self) -> dict:
        """
        Ejecuta un tick del scheduler:
        - Determina el site "locked" (no mezclar organismos).
        - Repone la cola hasta `target_queue_depth` si hay candidatos.
        """

        stats = {"claimed": 0, "enqueued": 0, "errors": 0}

        adapters, configs = self._get_enabled_adapters_and_configs()
        if not adapters:
            self.logger.warning("No hay adapters habilitados/configurados (revisa organismo_config + BRAIN_ENABLED_SITES)")
            return stats

        site_id = await self._choose_site_to_refill(adapters, configs)
        if not site_id:
            self.logger.info("No hay lock ni candidatos remotos disponibles en sites habilitados.")
            return stats

        adapter = self.adapters.get(site_id)
        config = configs.get(site_id)
        if not adapter or not config:
            self.logger.warning(f"[{site_id}] Sin adapter/config; saltando.")
            return stats

        queue_depth = self.db.count_tasks(site_id)
        if queue_depth >= adapter.target_queue_depth:
            self.logger.info(f"[{site_id}] Cola OK (depth={queue_depth} >= target={adapter.target_queue_depth}); no se repone.")
            return stats

        self.logger.info(
            f"[{site_id}] Refill: queue_depth={queue_depth} target={adapter.target_queue_depth} batch={adapter.max_refill_batch}"
        )

        try:
            await self.init_session(config["login_url"])
            candidates = adapter.fetch_candidates(
                config=config,
                conn_str=self.sqlserver_conn_str,
                authenticated_user=self.authenticated_user,
                limit=adapter.max_refill_batch,
            )
            if not candidates:
                self.logger.info(f"[{site_id}] Sin candidatos remotos válidos.")
                return stats

            claimed_candidates: list[dict] = []
            for cand in candidates:
                try:
                    ok = await adapter.ensure_claimed(self, cand)
                    if ok:
                        claimed_candidates.append(cand)
                        if int(cand.get("Estado") or 0) == 0:
                            stats["claimed"] += 1
                except Exception as e:
                    self.logger.error(f"[{site_id}] Error reclamando candidato: {e}")
                    stats["errors"] += 1

            if not claimed_candidates:
                self.logger.info(f"[{site_id}] No se pudo reclamar ningún candidato.")
                return stats

            payloads = await adapter.build_payloads(claimed_candidates)
            for payload in payloads:
                try:
                    self.enqueue_locally(site_id, payload)
                    stats["enqueued"] += 1
                except Exception as e:
                    self.logger.error(f"[{site_id}] Error encolando tarea: {e}")
                    stats["errors"] += 1

            if not self.dry_run:
                self.db.update_last_sync(site_id)

            return stats
        finally:
            await self.close_session()

    async def run_cycle(self) -> dict:
        """
        Ejecuta un ciclo completo de sincronización.
        
        Returns:
            Dict con estadísticas: claimed, enqueued, errors
        """
        legacy = (os.getenv("BRAIN_LEGACY_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}
        if not legacy:
            return await self.run_tick()
        self.logger.warning("BRAIN_LEGACY_MODE activo: usando run_cycle legacy (puede mezclar organismos).")

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
        self.logger.info(f"   Tick: {TICK_INTERVAL_SECONDS}s")
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
            
            self.logger.info(f"💤 Esperando {TICK_INTERVAL_SECONDS}s...")
            await asyncio.sleep(TICK_INTERVAL_SECONDS)


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
