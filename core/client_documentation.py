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
    get_client_type_from_db
)

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

# --- Lógica de Identidad ---

def client_identity_from_payload(payload: dict) -> ClientIdentity:
    """Extrae la identidad del cliente del payload."""
    sujeto_recurso = ((payload.get("sujeto_recurso") or payload.get("SujetoRecurso") or "")).strip() or None

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

    empresa = (payload.get("empresa") or payload.get("razon_social") or "").strip()
    if empresa:
        return ClientIdentity(is_company=True, sujeto_recurso=sujeto_recurso, empresa=empresa)

    nombre = (payload.get("cliente_nombre") or "").strip()
    ap1 = (payload.get("cliente_apellido1") or payload.get("apellido1") or "").strip()
    ap2 = (payload.get("cliente_apellido2") or payload.get("apellido2") or "").strip()
    if nombre and ap1 and ap2:
        return ClientIdentity(is_company=False, sujeto_recurso=sujeto_recurso,
                               nombre=nombre, apellido1=ap1, apellido2=ap2)

    raise RequiredClientDocumentsError("No se pudo inferir la identidad del cliente.")

# --- Heurística de Selección y Puntuación ---

def _calculate_file_score(path: Path, categories_found: list[str]) -> int:
    """Calcula el score combinando Calidad (CF/SF) y Ubicación (RECURSOS)."""
    score = 0
    name = path.name.lower()
    path_upper = str(path).upper()
    ext = path.suffix.lower()

    if ext == ".pdf": score += 50
    elif ext in [".jpg", ".jpeg", ".png"]: score += 20
    else: return -1000

    # 1. EL FACTOR DETERMINANTE: FIRMA (CF vs SF)
    # Le damos el peso más alto: un CF en carpeta normal gana a un SF en Recursos
    es_cf = any(k in name for k in [" cf", "_cf", "-cf", "con firma", "confirma", " firmad", " firmat"])
    es_sf = any(k in name for k in [" sf", "_sf", "-sf", "sin firma", "sinfirma"])

    if es_cf: score += 1500
    elif es_sf: score -= 100

    # 2. PRIORIDAD DE UBICACIÓN (RECURSOS)
    if "RECURSOS" in path_upper: score += 800

    # 3. Especificidad vs Combos (AUTDNI)
    if len(categories_found) > 1: score -= 45
    elif len(categories_found) == 1: score += 35

    # 4. Confianza
    if any(k in name for k in ["original", "completo", "definitivo"]): score += 50
    if "_solo_" in name or " solo " in name or name.endswith("solo.pdf"): score -= 15
    if any(k in name for k in ["comp.", "comprimido", "_cmp", " cmp"]) or name.endswith("cmp.pdf"): score += 20

    # 5. Fragmentos
    is_frag = any(k in name for k in ["anverso", "reverso", "cara", "part", "darrera", "trasera", "front", "back", "pag"])
    has_num = bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", name))
    if is_frag or has_num: score += 15

    # 6. Penalización
    if any(k in name for k in ["old", "antiguo", "vencido", "copia"]): score -= 500

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

def build_required_client_documents_for_payload(payload: dict, **kwargs) -> list[Path]:
    client = client_identity_from_payload(payload)
    base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    ruta = get_ruta_cliente_documentacion(client, base_path=base_path)
    selected = select_required_client_documents(
        ruta_docu=ruta,
        is_company=client.is_company,
        output_label=str(payload.get("idRecurso", "client")),
        **kwargs,
    )
    return selected.files_to_upload


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


async def build_required_client_documents_for_payload(
    payload: dict,
    gesdoc_user: Optional[str] = None,
    gesdoc_pwd: Optional[str] = None,
    sqlserver_conn_str: Optional[str] = None,
    **kwargs
) -> list[Path]:
    """
    Construye la lista de documentos requeridos del cliente.
    
    Si no se encuentra la identidad del cliente y se proporcionan credenciales GESDOC,
    intentará obtener la autorización automáticamente vía GESDOC.
    
    Args:
        payload: Datos del recurso
        gesdoc_user: Usuario de GESDOC (opcional, para fallback)
        gesdoc_pwd: Contraseña de GESDOC (opcional, para fallback)
        sqlserver_conn_str: Connection string de SQL Server (opcional, para fallback)
        **kwargs: Argumentos adicionales para select_required_client_documents
    
    Returns:
        Lista de paths de documentos a subir
    
    Raises:
        RequiredClientDocumentsError: Si no se puede obtener documentación
        ValueError: Si falta información necesaria para GESDOC
    """
    try:
        client = client_identity_from_payload(payload)
    except RequiredClientDocumentsError as e:
        # NUEVO: Intentar obtener vía GESDOC
        logger.warning(f"No se encontró identidad del cliente. Intentando GESDOC...")
        
        numclient = payload.get("numclient")
        expediente = payload.get("expediente")
        
        if not numclient or not expediente:
            raise ValueError("No se puede obtener autorización sin numclient y expediente") from e
        
        if not gesdoc_user or not gesdoc_pwd or not sqlserver_conn_str:
            logger.error("No hay credenciales GESDOC disponibles")
            raise ValueError("Credenciales GESDOC no configuradas") from e
        
        # Intentar obtener autorización
        auth_file = await fetch_missing_authorization_via_gesdoc(
            numclient,
            expediente,
            gesdoc_user,
            gesdoc_pwd,
            sqlserver_conn_str
        )
        
        if not auth_file:
            raise ValueError("No se pudo obtener autorización del cliente vía GESDOC") from e
        
        # Reintentar obtener identidad (ahora debería funcionar)
        try:
            client = client_identity_from_payload(payload)
        except RequiredClientDocumentsError:
            raise ValueError("Autorización obtenida pero aún no se puede inferir identidad") from e
    
    # Resto de la lógica sin cambios
    base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    ruta = get_ruta_cliente_documentacion(client, base_path=base_path)
    selected = select_required_client_documents(
        ruta_docu=ruta,
        is_company=client.is_company,
        output_label=str(payload.get("idRecurso", "client")),
        **kwargs,
    )
    return selected.files_to_upload