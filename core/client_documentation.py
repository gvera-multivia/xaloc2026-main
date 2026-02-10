from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Imports para GESDOC
from core.gesdoc_auth import create_gesdoc_session, trigger_client_authorization, close_gesdoc_session
from core.authorization_fetcher import (
    find_authorization_in_tmp,
    move_authorization_to_destinations,
    get_client_type_from_db,
    get_client_info_from_db
)
from core.client_paths import (
    ClientIdentity,
    get_ruta_cliente_documentacion
)

logger = logging.getLogger(__name__)

# --- Excepciones ---

class RequiredClientDocumentsError(RuntimeError):
    """No se han podido localizar/adjuntar los documentos obligatorios del cliente."""

# --- Modelos ---

@dataclass(frozen=True)
class SelectedClientDocuments:
    files_to_upload: list[Path]
    covered_terms: list[str]
    missing_terms: list[str]

# --- Lógica de Identidad ---

def client_identity_from_payload(payload: dict) -> ClientIdentity:
    """Extrae la identidad del cliente del payload."""
    sujeto_recurso = ((payload.get("sujeto_recurso") or payload.get("SujetoRecurso") or payload.get("name") or "")).strip() or None

    mandatario = payload.get("mandatario") or {}
    if isinstance(mandatario, dict) and (mandatario.get("tipo_persona") or "").strip():
        tipo = str(mandatario.get("tipo_persona")).strip().upper()
        if tipo == "JURIDICA":
            empresa = (mandatario.get("razon_social") or "").strip()
            if not empresa:
                raise RequiredClientDocumentsError("Falta razón social para persona JURÍDICA.")
            return ClientIdentity(is_company=True, sujeto_recurso=sujeto_recurso, empresa=empresa)
        if tipo == "FISICA":
            nombre = (mandatario.get("nombre") or "").strip()
            ap1 = (mandatario.get("apellido1") or "").strip()
            ap2 = (mandatario.get("apellido2") or "").strip()
            if not (nombre and ap1):
                raise RequiredClientDocumentsError("Faltan datos completos para persona FÍSICA.")
            return ClientIdentity(is_company=False, sujeto_recurso=sujeto_recurso,
                                  nombre=nombre, apellido1=ap1, apellido2=ap2 or "")

    nombre = (payload.get("cliente_nombre") or payload.get("notif_name") or "").strip()
    ap1 = (payload.get("cliente_apellido1") or payload.get("apellido1") or payload.get("notif_surname1") or "").strip()
    ap2 = (payload.get("cliente_apellido2") or payload.get("apellido2") or payload.get("notif_surname2") or "").strip()
    if nombre and ap1 and ap2:
        return ClientIdentity(is_company=False, sujeto_recurso=sujeto_recurso,
                               nombre=nombre, apellido1=ap1, apellido2=ap2)

    empresa = (payload.get("empresa") or payload.get("razon_social") or payload.get("notif_razon_social") or payload.get("cliente_razon_social") or "").strip()
    if empresa:
        return ClientIdentity(is_company=True, sujeto_recurso=sujeto_recurso, empresa=empresa)
    
    # FALLBACK: Si tenemos un nombre completo en sujeto_recurso/name pero no los campos desglosados
    if sujeto_recurso:
        # Intentamos detectar si es empresa de forma básica
        is_company = any(s in sujeto_recurso.upper() for s in [" S.L.", " S.A.", " SL ", " SA ", " S.C.P."])
        
        # Como client_paths.py usa sujeto_recurso con prioridad, devolvemos identidad básica
        if is_company:
             return ClientIdentity(is_company=True, sujeto_recurso=sujeto_recurso, empresa=sujeto_recurso)
        else:
             # Para persona física, si faltan nombre/apellidos, usamos sujeto_recurso como nombre sucio
             # o lo dejamos vacío si ClientIdentity lo permite. 
             # Para evitar errores en otros sitios, intentamos un split muy básico o pasamos strings vacíos.
             # Viendo client_paths.py -> get_client_folder_name usa sujeto_recurso PRIMERO.
             return ClientIdentity(is_company=False, sujeto_recurso=sujeto_recurso, nombre=sujeto_recurso, apellido1="", apellido2="")

    raise RequiredClientDocumentsError("No se pudo inferir la identidad del cliente.")


def client_identity_from_db(numclient: int, conn_str: str, sujeto_recurso: str | None = None) -> ClientIdentity:
    """Extrae la identidad del cliente consultando SQL Server."""
    info = get_client_info_from_db(numclient, conn_str)
    if not info:
        raise RequiredClientDocumentsError(f"No se encontró información en la DB para el cliente {numclient}")

    nombrefiscal = (info.get("Nombrefiscal") or "").strip()
    if nombrefiscal:
        return ClientIdentity(is_company=True, sujeto_recurso=sujeto_recurso, empresa=nombrefiscal)

    nombre = (info.get("Nombre") or "").strip()
    ap1 = (info.get("Apellido1") or "").strip()
    ap2 = (info.get("Apellido2") or "").strip()

    if not (nombre and ap1):
             raise RequiredClientDocumentsError(f"Datos de DB incompletos para cliente {numclient}")

    return ClientIdentity(is_company=False, sujeto_recurso=sujeto_recurso,
                          nombre=nombre, apellido1=ap1, apellido2=ap2)

# --- Heurística de Selección y Puntuación ---

def _detect_file_type(path: Path) -> str:
    """
    Detecta el tipo real de un archivo leyendo sus magic numbers.
    
    Returns:
        "pdf", "jpg", "jpeg", "png", or "unknown"
    """
    try:
        with open(path, 'rb') as f:
            header = f.read(16)  # Leer primeros 16 bytes
            
            # PDF: %PDF (25 50 44 46)
            if header.startswith(b'%PDF'):
                return "pdf"
            
            # JPEG: FF D8 FF
            if header.startswith(b'\xff\xd8\xff'):
                return "jpeg"
            
            # PNG: 89 50 4E 47 0D 0A 1A 0A
            if header.startswith(b'\x89PNG\r\n\x1a\n'):
                return "png"
            
            return "unknown"
    except Exception as e:
        logger.debug(f"Error detectando tipo de archivo {path.name}: {e}")
        return "unknown"

def _calculate_file_score(path: Path, categories_found: list[str]) -> int:
    """Calcula el score combinando Calidad (CF/SF) y Ubicación."""
    score = 0
    name = path.name.lower()
    path_upper = str(path).upper()
    ext = path.suffix.lower()

    # Filtro base de extensión
    if ext == ".pdf": 
        score += 50
    elif ext in [".jpg", ".jpeg", ".png"]: 
        score += 20
    else:
        # Si no tiene extensión conocida, verificar el tipo real del archivo
        detected_type = _detect_file_type(path)
        if detected_type == "pdf":
            score += 50  # Es un PDF sin extensión
            logger.debug(f"Archivo sin extensión detectado como PDF: {path.name}")
        elif detected_type in ["jpg", "jpeg", "png"]:
            score += 20  # Es una imagen sin extensión
            logger.debug(f"Archivo sin extensión detectado como {detected_type}: {path.name}")
        else:
            return -1000  # Formato no reconocido

    # 1. EL FACTOR DETERMINANTE: FIRMA (CF vs SF)
    # Buscamos patrones que indiquen si está firmado o no
    es_cf = any(k in name for k in [" cf", "_cf", "-cf", "con firma", "confirma", " firmad", " firmat"])
    es_sf = any(k in name for k in [" sf", "_sf", "-sf", "sin firma", "sinfirma"])

    if es_cf: 
        score += 1500  # Prioridad absoluta: el documento está firmado
    elif es_sf: 
        score += 200   # CAMBIO: Antes restaba 100. Ahora suma 200 para que sea 
                       # el mejor candidato si no existe un CF.

    # 2. PRIORIDAD DE UBICACIÓN
    # Valoramos más los archivos en carpetas específicas de gestión
    if "RECURSOS" in path_upper: 
        score += 800
    elif "DOCUMENTA" in path_upper: 
        score += 100 # Bonus por estar en la carpeta oficial de documentación

    # 3. Especificidad vs Documentos Combinados
    # Premiamos archivos que son solo una cosa (ej: solo DNI) sobre combos (ej: AUTDNI)
    if len(categories_found) > 1: 
        score -= 45
    elif len(categories_found) == 1: 
        score += 35

    # 4. Palabras clave de confianza
    if any(k in name for k in ["original", "completo", "definitivo"]): 
        score += 50
    if "_solo_" in name or " solo " in name or name.endswith("solo.pdf"): 
        score -= 15
    if any(k in name for k in ["comp.", "comprimido", "_cmp", " cmp"]) or name.endswith("cmp.pdf"): 
        score += 20

    # 5. Tratamiento de Fragmentos (Anverso/Reverso)
    is_frag = any(k in name for k in ["anverso", "reverso", "cara", "part", "darrera", "trasera", "front", "back", "pag"])
    has_num = bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", name))
    if is_frag or has_num: 
        score += 15

    # 6. Penalización de obsolescencia
    # Si el nombre indica que es viejo, lo hundimos en la puntuación
    if any(k in name for k in ["old", "antiguo", "vencido", "copia"]): 
        score -= 500

    return score

def select_required_client_documents(
    *,
    ruta_docu: Path,
    is_company: bool,
    strict: bool = True,
    merge_if_multiple: bool = False,
    pdftk_path: str | Path = r"C:\Program Files (x86)\PDFtk\bin\pdftk.exe",
    output_dir: Path = Path("tmp/client_docs"),
    output_label: str = "client",
) -> SelectedClientDocuments:
    if not ruta_docu.exists():
        raise RequiredClientDocumentsError(f"Ruta no encontrada: {ruta_docu}")

    categories_map = {
        "AUT": ["aut"],
        "DNI": ["dni", "nie", "pasaporte"],
        "CIF": ["cif", "nif"],
        "ESCR": ["escr", "constitu", "titularidad", "notar", "poder", "acta", "mercantil"] if is_company else [],
    }

    require_escr = os.getenv("CLIENT_DOCS_REQUIRE_ESCR", "0").lower() in ("1", "true", "y")
    strictly_required = ["AUT"]
    if is_company and require_escr: strictly_required.append("ESCR")
    
    process_cats = ["AUT", "DNI"]
    if is_company: process_cats.extend(["CIF", "ESCR"])

    # Escaneamos TODAS las subcarpetas relevantes del cliente para permitir Gap-Filling
    all_files = [p for p in ruta_docu.rglob("*") if p.is_file()]
    
    # Filtro de ruido: Solo nos interesan archivos dentro de carpetas DOCUMENTACION
    all_files = [f for f in all_files if "DOCUMENTA" in str(f).upper()]

    buckets = defaultdict(list)
    for file_path in all_files:
        cats_found = [cat for cat, keys in categories_map.items() if any(k in file_path.name.lower() for k in keys)]
        if not cats_found: continue

        score = _calculate_file_score(file_path, cats_found)
        if score < 0: continue

        for cat in cats_found:
            low = file_path.name.lower()
            is_fragment = any(x in low for x in ["anverso", "reverso", "cara", "part", "darrera", "trasera"]) or \
                          bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", low))
            buckets[cat].append({"path": file_path, "score": score, "is_fragment": is_fragment})

    final_files: list[Path] = []
    covered: list[str] = []
    missing: list[str] = []

    for cat in process_cats:
        cands = buckets.get(cat, [])
        if not cands:
            missing.append(cat)
            continue

        cands.sort(key=lambda x: x["score"], reverse=True)

        if cat == "AUT" and len(cands) > 1:
            sin_solo = [c for c in cands if "solo" not in c["path"].name.lower()]
            if sin_solo:
                cands = [c for c in cands if "solo" not in c["path"].name.lower() or c["score"] > sin_solo[0]["score"]]
                cands.sort(key=lambda x: x["score"], reverse=True)

        if not cands: continue
        best = cands[0]

        # SELECCIÓN MULTI-SOCIO (Ventana 20 pts)
        top_tier = [c["path"] for c in cands if c["score"] > (best["score"] - 20)]
        final_files.extend(top_tier)

        # SELECCIÓN FRAGMENTOS (Ventana 65 pts)
        if best["is_fragment"]:
            fragmentos = [c["path"] for c in cands if c["is_fragment"] and c["score"] > (best["score"] - 65)]
            final_files.extend(fragmentos)

        covered.append(cat)

    archivos_unicos = []
    seen = set()
    for p in final_files:
        if p not in seen:
            archivos_unicos.append(p); seen.add(p)

    missing_strict = [cat for cat in missing if cat in strictly_required]
    if missing_strict and strict:
        raise RequiredClientDocumentsError(f"Faltan docs obligatorios: {', '.join(missing_strict)}")

    if merge_if_multiple and len(archivos_unicos) > 1:
        pdftk_exe = Path(pdftk_path)
        if pdftk_exe.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"{output_label}_merged.pdf"
            try:
                cmd = [str(pdftk_exe)] + [str(p) for p in archivos_unicos] + ["cat", "output", str(out_path)]
                subprocess.run(cmd, check=True, capture_output=True)
                archivos_unicos = [out_path]
            except Exception as e:
                logger.error(f"Error fusionando con PDFtk: {e}")

    return SelectedClientDocuments(archivos_unicos, covered, missing)


async def build_required_client_documents_for_payload(
    payload: dict,
    gesdoc_user: Optional[str] = None,
    gesdoc_pwd: Optional[str] = None,
    sqlserver_conn_str: Optional[str] = None,
    **kwargs
) -> list[Path]:
    """
    Construye la lista de documentos requeridos del cliente.
    
    Si no se puede inferir la identidad del cliente desde el payload,
    o si falta la autorización (AUT), intenta obtenerla vía GESDOC como fallback.
    """
    # Intentar obtener identidad del cliente
    client: ClientIdentity | None = None
    identity_error: Optional[Exception] = None
    try:
        client = client_identity_from_payload(payload)
    except RequiredClientDocumentsError as e:
        identity_error = e

    if client is None:
        numclient = payload.get("numclient")
        if numclient and sqlserver_conn_str:
            try:
                client = client_identity_from_db(
                    numclient,
                    sqlserver_conn_str,
                    sujeto_recurso=payload.get("sujeto_recurso")
                )
            except RequiredClientDocumentsError as e:
                identity_error = e

    if client is None:
        # No se puede determinar identidad sin revisar rutas -> no usar GESDOC a?n
        raise identity_error or RequiredClientDocumentsError("No se pudo inferir la identidad del cliente.")
    
    # Intentar seleccionar documentos
    base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    ruta = get_ruta_cliente_documentacion(client, base_path=base_path)
    
    try:
        selected = select_required_client_documents(
            ruta_docu=ruta,
            is_company=client.is_company,
            output_label=str(payload.get("idRecurso", "client")),
            **kwargs,
        )
        return selected.files_to_upload
    except RequiredClientDocumentsError as e:
        # FALLBACK 2: Falta AUT → Intentar GESDOC
        if "AUT" in str(e):
            logger.warning(f"Falta autorización (AUT). Intentando obtenerla vía GESDOC...")
            
            numclient = payload.get("numclient")
            expediente = payload.get("expediente")
            
            if not numclient or not expediente:
                raise ValueError("No se puede obtener autorización sin numclient y expediente") from e
            
            if not gesdoc_user or not gesdoc_pwd or not sqlserver_conn_str:
                logger.error("No hay credenciales GESDOC disponibles")
                raise ValueError("Credenciales GESDOC no configuradas") from e
            
            # Obtener autorización vía GESDOC
            auth_file = await fetch_missing_authorization_via_gesdoc(
                numclient,
                expediente,
                gesdoc_user,
                gesdoc_pwd,
                sqlserver_conn_str
            )
            
            if not auth_file:
                raise ValueError("No se pudo obtener autorización del cliente vía GESDOC") from e
            
            # Reintentar selección de documentos
            logger.info(f"Reintentando selección de documentos tras obtener autorización...")
            selected = select_required_client_documents(
                ruta_docu=ruta,
                is_company=client.is_company,
                output_label=str(payload.get("idRecurso", "client")),
                **kwargs,
            )
            return selected.files_to_upload
        else:
            # Otro error, no relacionado con AUT
            raise


async def _fetch_and_rebuild_client_identity(
    payload: dict,
    gesdoc_user: Optional[str],
    gesdoc_pwd: Optional[str],
    sqlserver_conn_str: Optional[str],
    original_error: Exception
) -> ClientIdentity:
    """Helper para obtener autorización vía GESDOC y reconstruir identidad."""
    numclient = payload.get("numclient")
    expediente = payload.get("expediente")
    
    if not numclient or not expediente:
        raise ValueError("No se puede obtener autorización sin numclient y expediente") from original_error
    
    if not gesdoc_user or not gesdoc_pwd or not sqlserver_conn_str:
        logger.error("No hay credenciales GESDOC disponibles")
        raise ValueError("Credenciales GESDOC no configuradas") from original_error
    
    # Intentar obtener autorización
    auth_file = await fetch_missing_authorization_via_gesdoc(
        numclient,
        expediente,
        gesdoc_user,
        gesdoc_pwd,
        sqlserver_conn_str
    )
    
    if not auth_file:
        raise ValueError("No se pudo obtener autorización del cliente vía GESDOC") from original_error
    
    # Reintentar obtener identidad desde la DB
    logger.info(f"Reintentando obtener identidad desde la base de datos para cliente {numclient}...")
    try:
        return client_identity_from_db(numclient, sqlserver_conn_str, sujeto_recurso=payload.get("sujeto_recurso"))
    except RequiredClientDocumentsError as db_err:
        raise ValueError(f"Autorización obtenida pero aún no se puede inferir identidad: {db_err}") from original_error


# =============================================================================
# INTEGRACIÓN GESDOC - Obtención Automática de Autorizaciones
# =============================================================================

async def fetch_missing_authorization_via_gesdoc(
    numclient: int,
    expediente: str,
    gesdoc_user: str,
    gesdoc_pwd: str,
    sqlserver_conn_str: str,
    max_polling_retries: int = 5,
    polling_interval: float = 2.0
) -> Optional[Path]:
    """
    Obtiene autorización de cliente vía GESDOC cuando no está disponible localmente.
    """
    logger.info(f"Intentando obtener autorización para cliente {numclient} vía GESDOC")
    
    # 1. Obtener identidad completa desde SQL Server
    client_info = get_client_info_from_db(numclient, sqlserver_conn_str)
    if not client_info:
        logger.error(f"No se pudo obtener información de la DB para el cliente {numclient}")
        return None
        
    client_type = "empresa" if client_info.get("Nombrefiscal") else "particular"
    
    # Construimos la identidad
    client = ClientIdentity(
        is_company=(client_type == "empresa"),
        empresa=client_info.get("Nombrefiscal"),
        nombre=client_info.get("Nombre"),
        apellido1=client_info.get("Apellido1"),
        apellido2=client_info.get("Apellido2")
    )
    
    # Calculamos rutas de destino
    base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    client_root = get_ruta_cliente_documentacion(client, base_path)
    
    # Las subcarpetas estándar son DOCUMENTACION y DOCUMENTACION RECURSOS (o similar)
    # Buscamos subcarpetas que contengan estas palabras
    dest_folders = []
    if client_root.exists():
        for sub in client_root.iterdir():
            if sub.is_dir():
                sub_name = sub.name.upper()
                if "DOCUMENTA" in sub_name:
                    dest_folders.append(sub)
    
    # Si no existen, las definimos por defecto dentro del cliente
    if not dest_folders:
        dest_folders = [
            client_root / "DOCUMENTACION",
            client_root / "DOCUMENTACION RECURSOS"
        ]

    # 2. Buscar primero en tmp (puede que ya exista)
    auth_file = find_authorization_in_tmp(numclient, client_type)
    if auth_file:
        logger.info(f"✓ Autorización ya existe en tmp: {auth_file.name}")
        if move_authorization_to_destinations(auth_file, dest_folders):
            return auth_file
        else:
            logger.warning("No se pudo mover la autorización, pero existe")
            return auth_file
    
    # 3. No existe, generar vía GESDOC (UNA SOLA VEZ)
    logger.warning(f"⚠️ Enviando solicitud de autorización a GESDOC para {numclient}")
    try:
        session = await create_gesdoc_session(gesdoc_user, gesdoc_pwd)
        success = await trigger_client_authorization(session, numclient)
        await close_gesdoc_session(session)
        
        if not success:
            logger.error("Trigger de GESDOC falló")
            return None
    except Exception as e:
        logger.error(f"Error en autenticación/trigger GESDOC: {e}")
        return None
    
    # 4. Polling para verificar generación
    for attempt in range(max_polling_retries):
        logger.info(f"Verificando generación del PDF (intento {attempt + 1}/{max_polling_retries})...")
        await asyncio.sleep(polling_interval)
        
        auth_file = find_authorization_in_tmp(numclient, client_type)
        if auth_file:
            logger.info(f"✓ Autorización generada: {auth_file.name}")
            move_authorization_to_destinations(auth_file, dest_folders)
            return auth_file
    
    logger.error(f"No se generó autorización después de {max_polling_retries} intentos")
    return None


# =============================================================================
# VERIFICACIÓN DE REQUISITOS GESDOC
# =============================================================================

def check_requires_gesdoc(payload: dict, base_path: str | None = None) -> tuple[bool, str | None]:
    """
    Verifica si un caso requiere autorización GESDOC antes de procesarse.
    
    Comprueba si existe AUT del cliente en la carpeta de documentación local.
    Si no existe, el caso debe ir a pending_authorization_queue.
    
    Args:
        payload: Datos del trámite (debe incluir datos del cliente)
        base_path: Ruta base de clientes (default: CLIENT_DOCS_BASE_PATH o \\SERVER-DOC\clientes)
    
    Returns:
        (requires_gesdoc: bool, reason: str | None)
        - (False, None) si NO requiere GESDOC
        - (True, "motivo") si SÍ requiere GESDOC
    """
    if base_path is None:
        base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    
    # 1. Intentar obtener identidad del cliente
    try:
        client = client_identity_from_payload(payload)
    except RequiredClientDocumentsError as e:
        # No se puede determinar identidad → requiere GESDOC
        return (True, f"No se pudo inferir identidad del cliente: {e}")
    
    # 2. Obtener ruta de documentación
    try:
        ruta_docu = get_ruta_cliente_documentacion(client, base_path=base_path)
    except Exception as e:
        return (True, f"Error obteniendo ruta de documentación: {e}")
    
    # 3. Verificar si la carpeta existe
    if not ruta_docu.exists():
        return (True, f"Carpeta de documentación no existe: {ruta_docu}")
    
    # 4. Buscar AUT en la carpeta (solo verificamos existencia, no seleccionamos)
    aut_keywords = ["aut"]
    all_files = [p for p in ruta_docu.rglob("*") if p.is_file()]
    
    # Filtrar solo archivos en carpetas DOCUMENTACION
    doc_files = [f for f in all_files if "DOCUMENTA" in str(f).upper()]
    
    # Buscar cualquier archivo que contenga "aut" en el nombre
    aut_files = [
        f for f in doc_files 
        if any(kw in f.name.lower() for kw in aut_keywords)
        and f.suffix.lower() in [".pdf", ".jpg", ".jpeg", ".png"]
    ]
    
    if not aut_files:
        return (True, f"No se encontró autorización (AUT) en: {ruta_docu}")
    
    # Si hay AUT, no requiere GESDOC
    logger.debug(f"AUT encontrado para el cliente: {aut_files[0].name}")
    return (False, None)