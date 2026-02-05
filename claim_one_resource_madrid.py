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

Mejoras:
- Fallback de matrícula: si expedientes.matricula viene vacía, se extrae de pubExp.publicación por patrón.
- (Opcional) Fallback adicional desde rs.notas (incluido en SELECT).
- Prevalidación de campos obligatorios antes de encolar.
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

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
ASIGNAR_URL = (
    "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos/AsignarA"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [CLAIM-MADRID] - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/claim_madrid.log", encoding="utf-8")],
)
logger = logging.getLogger("claim_madrid")

# =============================================================================
# CONSULTAS SQL SERVER
# =============================================================================

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


async def get_authenticated_username(session: aiohttp.ClientSession) -> Optional[str]:
    """Obtiene el nombre del usuario autenticado."""
    try:
        async with session.get(
            "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/home"
        ) as resp:
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


def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _convert_value(v: Any) -> Any:
    """Convierte valores SQL Server a tipos JSON serializables."""
    if isinstance(v, Decimal):
        return float(v)
    if v is None:
        return None
    return v


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).strip().lower()
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _detectar_tipo_documento(doc: str) -> str:
    """Detecta si es NIF, NIE o PASAPORTE (Madrid solo acepta estos 3)."""
    if not doc:
        return "NIF"
    doc = doc.strip().upper()
    if re.match(r"^[XYZ]", doc):
        return "NIE"
    if re.match(r"^[A-Z]{3}[0-9]+$", doc):
        return "PASAPORTE"
    return "NIF"


def _seleccionar_telefonos(tel1, tel2, movil) -> tuple[str, str]:
    """Selecciona un móvil y un teléfono de los campos disponibles."""
    all_nums = [_clean_str(tel1), _clean_str(tel2), _clean_str(movil)]
    final_movil = ""
    final_tel = ""

    for n in all_nums:
        clean_n = re.sub(r"\D", "", n)
        if not clean_n:
            continue
        if clean_n.startswith(("6", "7")):
            if not final_movil:
                final_movil = clean_n
            elif not final_tel:
                final_tel = clean_n
        else:
            if not final_tel:
                final_tel = clean_n

    return final_movil[:9], final_tel[:9]


def _inferir_prefijo_expediente(*, fase_raw: str, es_empresa: bool) -> str:
    fase_norm = _normalize_text(fase_raw)
    if "identificacion" in fase_norm:
        return "911" if es_empresa else "912"
    if "denuncia" in fase_norm:
        return "911" if es_empresa else "912"
    if "sancion" in fase_norm or "resolucion" in fase_norm:
        return "931" if es_empresa else "935"
    return "935"


def _parse_expediente(expediente: str, *, fase_raw: str = "", es_empresa: bool = False) -> dict:
    exp = _clean_str(expediente).upper()

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

    m2 = re.match(r"^(?P<lll>[A-Z]{3})/(?P<aaaa>\d{4})/(?P<exp>\d{9})$", exp)
    if m2:
        return {
            "expediente_completo": exp,
            "expediente_tipo": "opcion2",
            "expediente_lll": m2.group("lll"),
            "expediente_aaaa": m2.group("aaaa"),
            "expediente_exp_num": m2.group("exp"),
            "expediente_nnn": "",
            "expediente_eeeeeeeee": "",
            "expediente_d": "",
        }

    m3 = re.match(r"^(?P<exp>\d{9})\.(?P<d>\d)$", exp)
    if m3:
        prefijo = _inferir_prefijo_expediente(fase_raw=fase_raw, es_empresa=es_empresa)
        exp_reconstruido = f"{prefijo}/{exp}"
        logger.warning(
            "Expediente sin prefijo NNN ('%s'). Inferido: %s. Completo: %s",
            exp,
            prefijo,
            exp_reconstruido,
        )
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

    logger.warning("Formato de expediente no reconocido: '%s'", exp)
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


def _load_motivos_config() -> dict:
    try:
        path = Path("config_motivos.json")
        if not path.exists():
            return {}
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("No se pudo cargar config_motivos.json: %s", e)
        return {}


def _inferir_naturaleza_por_motivo_y_fase(*, motivo_key: str, motivo_data: dict | None, fase_raw: str) -> str:
    motivo_norm = _normalize_text(motivo_key)
    fase_norm = _normalize_text(fase_raw)

    if "identificacion" in motivo_norm or "identificacion" in fase_norm:
        return "I"

    if any(tag in motivo_norm for tag in ["denuncia", "propuesta", "subsanacion"]) or any(
        tag in fase_norm for tag in ["denuncia", "propuesta", "subsanacion", "alegacion", "alegaciones"]
    ):
        return "A"

    if any(tag in motivo_norm for tag in ["sancion", "apremio", "embargo", "requerimiento", "reclamacion", "revision"]) or any(
        tag in fase_norm for tag in ["sancion", "apremio", "embargo", "requerimiento", "reclamacion", "revision", "recurso"]
    ):
        return "R"

    blob_parts: list[str] = [motivo_norm, fase_norm]
    if motivo_data:
        for field in ("asunto", "expone", "solicita"):
            blob_parts.append(_normalize_text(motivo_data.get(field)))
    blob = " ".join(p for p in blob_parts if p)

    if "alegacion" in blob or "alegaciones" in blob:
        return "A"
    if "recurso" in blob or "reposicion" in blob or "reclamacion" in blob or "revision" in blob:
        return "R"

    return "A"


def _build_expone_solicita(fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str, str]:
    config = _load_motivos_config()
    fase_norm = _normalize_text(fase_raw)

    selected: dict | None = None
    selected_key = ""
    for key, value in (config or {}).items():
        key_norm = _normalize_text(key)
        if key_norm and key_norm in fase_norm:
            selected = value
            selected_key = key
            break

    exp = _clean_str(expediente)
    sujeto_txt = _clean_str(sujeto)

    if not selected:
        expone = f"Se presenta escrito relativo al expediente {exp}."
        solicita = f"Se tenga por presentado el escrito. Expediente: {exp}."
        naturaleza = _inferir_naturaleza_por_motivo_y_fase(motivo_key="", motivo_data=None, fase_raw=fase_raw)
        return expone, solicita, naturaleza

    expone = _clean_str(selected.get("expone")).replace("{expediente}", exp).replace("{sujeto_recurso}", sujeto_txt)
    solicita = _clean_str(selected.get("solicita")).replace("{expediente}", exp).replace("{sujeto_recurso}", sujeto_txt)

    naturaleza = _inferir_naturaleza_por_motivo_y_fase(motivo_key=selected_key, motivo_data=selected, fase_raw=fase_raw)
    return expone, solicita, naturaleza


# ==========================
# Matrícula fallback (PUBEXP)
# ==========================

_PLATE_PATTERNS = [
    re.compile(r"\b\d{4}[A-Z]{3}\b"),           # 2390GZF
    re.compile(r"\b[A-Z]{1,2}\d{4}[A-Z]{1,2}\b"),  # B1234CD
    re.compile(r"\b\d{4}[A-Z]{2,3}\b"),
]


def _extract_plate(text: str) -> str:
    if not text:
        return ""
    t = _clean_str(text).upper()
    t = re.sub(r"\s+", " ", t)
    for pat in _PLATE_PATTERNS:
        m = pat.search(t)
        if m:
            return m.group(0).strip()
    return ""


def _resolve_plate_number(recurso: dict) -> tuple[str, str]:
    """
    Devuelve (matricula, source)
    source: 'expedientes.matricula' | 'pubExp.publicación' | 'recursosExp.notas' | ''
    """
    plate = _clean_str(recurso.get("matricula")).upper()
    if plate:
        return plate, "expedientes.matricula"

    pub = _clean_str(recurso.get("pub_publicacion"))
    plate = _extract_plate(pub)
    if plate:
        return plate, "pubExp.publicación"

    notas = _clean_str(recurso.get("notas"))
    plate = _extract_plate(notas)
    if plate:
        return plate, "recursosExp.notas"

    return "", ""


def _prevalidate_required_fields(payload: dict) -> None:
    missing = []
    if not _clean_str(payload.get("plate_number")):
        missing.append("plate_number")
    if not _clean_str(payload.get("notif_numero_documento")):
        missing.append("notif_numero_documento")
    if not _clean_str(payload.get("notif_nombre_via")):
        missing.append("notif_nombre_via")
    if not _clean_str(payload.get("notif_numero")) and payload.get("notif_tipo_numeracion") == "NUM":
        # si eliges NUM, número debería existir (si es S/N, no)
        missing.append("notif_numero")
    if missing:
        raise ValueError(f"Payload inválido, faltan campos requeridos: {', '.join(missing)}")


# =============================================================================
# LÓGICA PRINCIPAL
# =============================================================================


def fetch_one_resource_madrid(conn_str: str, authenticated_user: Optional[str] = None) -> Optional[dict]:
    """Busca UN recurso disponible de Madrid."""
    logger.info("🔍 Buscando recursos de MADRID disponibles...")

    regex_madrid = [re.compile(r"^\d{3}/\d{9}\.\d$"), re.compile(r"^\d{9}\.\d$")]

    texp_values = [2, 3]
    texp_placeholders = ",".join(["?"] * len(texp_values))
    query = SQL_FETCH_RECURSOS_MADRID.format(texp_list=texp_placeholders)

    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute(query, texp_values)

        columns = [column[0] for column in cursor.description]
        recursos_map: dict[int, dict] = {}

        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            id_recurso = record.get("idRecurso")
            if not id_recurso:
                continue

            if id_recurso not in recursos_map:
                recursos_map[id_recurso] = {**record, "adjuntos": []}

            adj_id = record.get("adjunto_id")
            if adj_id:
                recursos_map[id_recurso]["adjuntos"].append({"id": adj_id, "filename": record.get("adjunto_filename")})

        conn.close()

        for id_recurso, recurso in recursos_map.items():
            expediente = _clean_str(recurso.get("Expedient"))
            estado = recurso.get("Estado", 0)
            usuario = str(recurso.get("UsuarioAsignado", "")).strip()

            expediente_valido = any(reg.match(expediente) for reg in regex_madrid)

            fase_norm = _normalize_text(recurso.get("FaseProcedimiento"))
            es_fase_negra = any(x in fase_norm for x in ["reclamacion", "embargo", "apremio"])

            if expediente_valido and not es_fase_negra:
                if estado == 1 and (not authenticated_user or usuario != authenticated_user):
                    continue

                status_str = "LIBRE" if estado == 0 else f"EN PROCESO ({usuario})"
                logger.info(
                    "✓ Recurso MADRID encontrado (%s): %s - %s (Fase: %s)",
                    status_str,
                    id_recurso,
                    expediente,
                    recurso.get("FaseProcedimiento"),
                )
                return recurso

        logger.warning("No se encontraron recursos de Madrid válidos")
        return None

    except Exception as e:
        logger.error(f"Error consultando SQL Server: {e}")
        return None


async def claim_resource(session: aiohttp.ClientSession, id_recurso: int, dry_run: bool = False) -> bool:
    """Reclama el recurso en Xvia."""
    if dry_run:
        return True
    try:
        async with session.get(
            "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos"
        ) as resp:
            html = await resp.text()
            match = re.search(r'name="_token"\s+value="([^"]+)"', html)
            if not match:
                return False
            csrf_token = match.group(1)

        form_data = {"_token": csrf_token, "id": str(id_recurso), "recursosSel": "0"}
        async with session.post(ASIGNAR_URL, data=form_data) as resp:
            return resp.status in (200, 302, 303)
    except Exception as e:
        logger.error(f"Error en claim: {e}")
        return False


async def build_madrid_payload(recurso: dict) -> dict:
    """Construye el payload enriquecido para Madrid con expediente normalizado."""
    expediente_raw = _clean_str(recurso.get("Expedient"))
    cif_empresa = _clean_str(recurso.get("cif"))
    nif = cif_empresa or _clean_str(recurso.get("cliente_nif"))
    fase_raw = _clean_str(recurso.get("FaseProcedimiento"))

    exp_parts = _parse_expediente(expediente_raw, fase_raw=fase_raw, es_empresa=bool(cif_empresa))
    expediente_para_textos = exp_parts.get("expediente_completo", expediente_raw)

    expone, solicita, naturaleza = _build_expone_solicita(
        fase_raw,
        expediente_para_textos,
        _clean_str(recurso.get("SujetoRecurso")),
    )

    # Matrícula: campo directo o fallback por publicación/notas
    plate_number, plate_src = _resolve_plate_number(recurso)
    if not plate_number:
        logger.warning(
            "Matrícula vacía tras fallback. idRecurso=%s idExp=%s Expedient=%s Idpublic=%s pub='%s'",
            recurso.get("idRecurso"),
            recurso.get("idExp"),
            recurso.get("Expedient"),
            recurso.get("exp_idpublic"),
            _clean_str(recurso.get("pub_publicacion"))[:160],
        )

    # Clasificación de dirección (IA o Fallback)
    domicilio_raw = _clean_str(recurso.get("cliente_domicilio"))
    numero_db = _clean_str(recurso.get("cliente_numero"))
    poblacion = _clean_str(recurso.get("cliente_municipio"))
    piso_db = _clean_str(recurso.get("cliente_planta"))
    puerta_db = _clean_str(recurso.get("cliente_puerta"))
    escalera_db = _clean_str(recurso.get("cliente_escalera"))

    use_ai = os.getenv("GROQ_API_KEY") is not None
    if use_ai:
        try:
            logger.info("[IA] Clasificando dirección con IA: '%s'", domicilio_raw)
            clasificacion = await classify_address_with_ai(
                direccion_raw=domicilio_raw,
                poblacion=poblacion,
                numero=numero_db,
                piso=piso_db,
                puerta=puerta_db,
            )
            notif_tipo_via = clasificacion["tipo_via"]
            notif_nombre_via = clasificacion["calle"].upper()
            notif_numero = clasificacion["numero"]
            notif_escalera = (clasificacion.get("escalera") or escalera_db).upper()
            notif_planta = (clasificacion.get("planta") or piso_db).upper()
            notif_puerta = (clasificacion.get("puerta") or puerta_db).upper()
        except Exception as e:
            logger.warning("[IA] Falló clasificación IA, usando fallback: %s", e)
            use_ai = False

    if not use_ai:
        clasificacion = classify_address_fallback(domicilio_raw)
        notif_tipo_via = clasificacion["tipo_via"]
        notif_nombre_via = clasificacion["calle"].upper()
        notif_numero = clasificacion["numero"] or numero_db
        notif_escalera = escalera_db.upper()
        notif_planta = piso_db.upper()
        notif_puerta = puerta_db.upper()

    tipo_numeracion = "NUM" if _clean_str(notif_numero) else "S/N"
    provincia_notif = _clean_str(recurso.get("cliente_provincia")).upper() or poblacion.upper()

    movil, tel = _seleccionar_telefonos(recurso.get("cliente_tel1"), recurso.get("cliente_tel2"), recurso.get("cliente_movil"))

    # Representante (Datos fijos)
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
    }

    payload = {
        "idRecurso": _convert_value(recurso["idRecurso"]),
        "idExp": _convert_value(recurso["idExp"]),
        "expediente": expediente_raw,
        "numclient": _convert_value(recurso["numclient"]),
        "sujeto_recurso": _clean_str(recurso.get("SujetoRecurso")),
        "fase_procedimiento": fase_raw,

        "plate_number": plate_number,
        "plate_number_source": plate_src,

        "user_phone": "932531411",
        "inter_email_check": bool(_clean_str(recurso.get("cliente_email"))),

        **representante,

        "notif_tipo_documento": _detectar_tipo_documento(nif),
        "notif_numero_documento": nif,
        "notif_name": _clean_str(recurso.get("cliente_nombre")).upper(),
        "notif_surname1": _clean_str(recurso.get("cliente_apellido1")).upper(),
        "notif_surname2": _clean_str(recurso.get("cliente_apellido2")).upper(),
        "notif_razon_social": _clean_str(recurso.get("cliente_razon_social")).upper(),
        "notif_pais": "ESPAÑA",
        "notif_provincia": provincia_notif,
        "notif_municipio": poblacion.upper(),
        "notif_tipo_via": notif_tipo_via,
        "notif_nombre_via": notif_nombre_via,
        "notif_tipo_numeracion": tipo_numeracion,
        "notif_numero": _clean_str(notif_numero),
        "notif_portal": "",
        "notif_escalera": _clean_str(notif_escalera),
        "notif_planta": _clean_str(notif_planta),
        "notif_puerta": _clean_str(notif_puerta),
        "notif_codigo_postal": _clean_str(recurso.get("cliente_cp")),

        # Email/teléfono (como venías haciendo)
        "notif_email": "info@xvia-serviciosjuridicos.com",
        "notif_movil": "",  # cleared
        "notif_telefono": "932531411",

        # Standard keys for core.client_documentation.client_identity_from_payload
        "cliente_nombre": _clean_str(recurso.get("cliente_nombre")).upper(),
        "cliente_apellido1": _clean_str(recurso.get("cliente_apellido1")).upper(),
        "cliente_apellido2": _clean_str(recurso.get("cliente_apellido2")).upper(),
        "razon_social": _clean_str(recurso.get("cliente_razon_social")).upper(),

        "inter_telefono": "932531411",
        "rep_movil": "",
        "rep_telefono": "932531411",

        **exp_parts,

        "naturaleza": naturaleza,
        "expone": expone,
        "solicita": solicita,

        "source": "claim_one_resource_madrid",
        "claimed_at": datetime.now().isoformat(),
    }

    # Adjuntos ya agregados en fetch_one_resource_madrid
    # (si tu worker espera archivos_adjuntos explícito, ajústalo aquí)
    if recurso.get("adjuntos"):
        payload["adjuntos"] = recurso["adjuntos"]

    return payload


async def main() -> int:
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
        logger.info("✓ Usuario: %s", user)

        conn_str = build_sqlserver_connection_string()
        recurso = fetch_one_resource_madrid(conn_str, user)
        if not recurso:
            return 0

        id_rec = recurso["idRecurso"]
        if recurso.get("Estado") == 0:
            ok = await claim_resource(session, id_rec, args.dry_run)
            if not ok:
                logger.error("❌ Claim falló")
                return 1
            logger.info("✅ Recurso %s reclamado vía POST", id_rec)

        payload = await build_madrid_payload(recurso)

        # Prevalidación (falla rápido si falta matrícula u otros obligatorios)
        _prevalidate_required_fields(payload)

        db = SQLiteDatabase("db/xaloc_database.db")
        if not args.dry_run:
            task_id = db.insert_task("madrid", None, payload)
            logger.info("📥 Tarea %s encolada para MADRID", task_id)
        else:
            logger.info("[DRY-RUN] Payload Madrid: %s", payload)

    finally:
        await session.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
