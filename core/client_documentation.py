from __future__ import annotations

import logging
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# --- Excepciones ---

class RequiredClientDocumentsError(RuntimeError):
    """No se han podido localizar/adjuntar los documentos obligatorios del cliente."""

# --- Modelos ---

@dataclass(frozen=True)
class ClientIdentity:
    is_company: bool
    empresa: str | None = None
    nombre: str | None = None
    apellido1: str | None = None
    apellido2: str | None = None

@dataclass(frozen=True)
class SelectedClientDocuments:
    files_to_upload: list[Path]
    covered_terms: list[str]
    missing_terms: list[str]

# --- Lógica de Identidad y Rutas (Mantenida/Refinada) ---

def client_identity_from_payload(payload: dict) -> ClientIdentity:
    """Extrae la identidad del cliente del payload (soporta varios formatos)."""
    mandatario = payload.get("mandatario") or {}
    if isinstance(mandatario, dict) and (mandatario.get("tipo_persona") or "").strip():
        tipo = str(mandatario.get("tipo_persona")).strip().upper()
        if tipo == "JURIDICA":
            empresa = (mandatario.get("razon_social") or "").strip()
            if not empresa:
                raise RequiredClientDocumentsError("Falta razón social para persona JURÍDICA.")
            return ClientIdentity(is_company=True, empresa=empresa)
        if tipo == "FISICA":
            nombre = (mandatario.get("nombre") or "").strip()
            ap1 = (mandatario.get("apellido1") or "").strip()
            ap2 = (mandatario.get("apellido2") or "").strip()
            if not (nombre and ap1 and ap2):
                raise RequiredClientDocumentsError("Faltan datos completos para persona FÍSICA.")
            return ClientIdentity(is_company=False, nombre=nombre, apellido1=ap1, apellido2=ap2)

    # Fallbacks de nombres directos
    empresa = (payload.get("empresa") or payload.get("razon_social") or "").strip()
    if empresa: return ClientIdentity(is_company=True, empresa=empresa)

    nombre = (payload.get("cliente_nombre") or "").strip()
    ap1 = (payload.get("cliente_apellido1") or payload.get("apellido1") or "").strip()
    ap2 = (payload.get("cliente_apellido2") or payload.get("apellido2") or "").strip()
    if nombre and ap1 and ap2:
        return ClientIdentity(is_company=False, nombre=nombre, apellido1=ap1, apellido2=ap2)

    raise RequiredClientDocumentsError("No se pudo inferir la identidad del cliente.")

def get_ruta_cliente_documentacion(client: ClientIdentity, base_path: str | Path) -> Path:
    """Calcula la ruta base y busca carpetas de confianza."""
    base = Path(base_path)
    
    def _get_alpha_folder(char: str) -> str:
        char = char.upper()
        if char in "0123456789": return "0-9 (NUMEROS)"
        if char in "ABC": return "A-C"
        if char in "DE": return "D-E"
        if char in "FGHIJ": return "F-J"
        if char in "KL": return "K-L"
        if char in "MNO": return "M-O"
        if char in "PQRSTU": return "P-U"
        if char in "VWXYZ": return "V-Z"
        return "Desconocido"

    if client.is_company:
        name = client.empresa.strip().rstrip("!.,?;:")
        folder = base / _get_alpha_folder(name[0]) / name
    else:
        full_name = f"{client.nombre} {client.apellido1.upper()} {client.apellido2.upper()}".strip()
        folder = base / _get_alpha_folder(client.nombre[0]) / full_name

    # Jerarquía de carpetas: RECURSOS es la máxima prioridad
    for subname in ["DOCUMENTACION RECURSOS", "DOCUMENTACION", "DOCUMENTACIÓN"]:
        if (folder / subname).exists():
            return folder / subname
    return folder

# --- Nueva Heurística de Selección ---

def _analyze_file_categories(name: str, categories_map: dict) -> list[str]:
    """Determina a cuántas categorías pertenece un nombre de archivo."""
    found = []
    for cat, keywords in categories_map.items():
        if any(k in name.lower() for k in keywords):
            found.append(cat)
    return found

def _calculate_file_score(path: Path, categories_found: list[str]) -> int:
    """
    Calcula el score priorizando archivos específicos sobre combos.
    Valores altos = Documento con alta probabilidad de ser el correcto.
    """
    score = 0
    name = path.name.lower()
    ext = path.suffix.lower()

    # 1. Filtro de extensión (PROHIBIDO WORD)
    if ext == ".pdf": score += 50
    elif ext in [".jpg", ".jpeg", ".png"]: score += 20
    else: return -1000  # Descarte automático

    # 2. ESPECIFICIDAD vs COMBOS (El matiz clave)
    if len(categories_found) > 1:
        score -= 40  # Penalizamos archivos tipo "AUTDNI.pdf"
    elif len(categories_found) == 1:
        score += 30  # Premiamos archivos específicos como "AUTORIZACION.pdf"

    # 3. Filtro de tamaño (evitar logos de 10KB o manuales de 50MB)
    try:
        size_kb = path.stat().st_size / 1024
        if size_kb < 40: return -500  # Probablemente un logo de firma
        if size_kb > 10000: score -= 30  # Penalizar archivos gigantes (>10MB)
        if 200 < size_kb < 4000: score += 25  # "Sweet spot" de un escaneo normal
    except OSError:
        return -1000

    # 4. Keywords de Confianza
    if any(k in name for k in ["firmada", "firmat", "recursos", "original"]):
        score += 50
    if any(k in name for k in ["comp", "completo"]):
        score += 20
    
    # 5. Keywords de Fragmento (Indican que es una parte de algo)
    # Incluye términos en catalán, español e inglés
    if any(k in name for k in [
        "anverso", "reverso", "cara", "part", "front", "back", 
        "darrera", "trasera", "frontal", "cara1", "cara2", 
        "page1", "pág1", "página1"
    ]):
        score += 15

    # 6. Penalización de archivos antiguos
    if any(k in name for k in ["old", "antiguo", "vencido", "copia"]):
        score -= 100

    return score

def _log_score_table(buckets: dict[str, list[dict]], cat: str) -> None:
    """Imprime una tabla de scores para debugging y trazabilidad."""
    if not buckets.get(cat):
        return
    
    logger.info(f"\n{'='*80}")
    logger.info(f"Score Table para categoría: {cat}")
    logger.info(f"{'-'*80}")
    logger.info(f"{'Archivo':<50} {'Score':>8} {'Fragmento':>12}")
    logger.info(f"{'-'*80}")
    
    for item in sorted(buckets[cat], key=lambda x: x["score"], reverse=True):
        filename = item["path"].name[:48]  # Truncar si es muy largo
        score = item["score"]
        is_frag = "Sí" if item["is_fragment"] else "No"
        logger.info(f"{filename:<50} {score:>8} {is_frag:>12}")
    
    logger.info(f"{'='*80}\n")

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

    # Definir requisitos
    # Si es empresa, ESCR es opcional a menos que se fuerce por env
    require_escr = os.getenv("CLIENT_DOCS_REQUIRE_ESCR", "0").lower() in ("1", "true", "y")
    
    # Mapeo de categorías a términos de búsqueda
    categories_map = {
        "AUT": ["aut"],
        "DNI": ["dni", "nie", "pasaporte"],
        "CIF": ["cif", "nif"] if is_company else [],
        "ESCR": ["escr", "constitu"] if is_company else []
    }
    
    required_cats = ["AUT", "DNI"]
    if is_company:
        required_cats.append("CIF")
        if require_escr: required_cats.append("ESCR")

    # Cubetas para clasificar candidatos
    buckets: dict[str, list[dict]] = defaultdict(list)

    # 1. Clasificación y Puntuación
    for file_path in ruta_docu.rglob("*"):
        if not file_path.is_file(): continue
        
        cats_found = _analyze_file_categories(file_path.name, categories_map)
        if not cats_found: continue

        score = _calculate_file_score(file_path, cats_found)
        if score < 0: continue

        for cat in cats_found:
            # Detectamos si es un fragmento con keywords ampliados
            is_fragment = any(x in file_path.name.lower() for x in [
                "anverso", "reverso", "cara", "part", "darrera", "trasera", 
                "front", "back", "frontal", "cara1", "cara2", 
                "page1", "pág1", "página1"
            ])
            buckets[cat].append({
                "path": file_path,
                "score": score,
                "is_fragment": is_fragment
            })

    final_files: list[Path] = []
    covered: list[str] = []
    missing: list[str] = []
    
    # Variable de entorno para activar logging detallado
    debug_scoring = os.getenv("CLIENT_DOCS_DEBUG_SCORING", "0").lower() in ("1", "true", "y")

    # 2. Selección inteligente por cubeta usando ESTRATEGIA DE VECINDAD
    for cat in required_cats:
        cands = buckets.get(cat, [])
        if not cands:
            missing.append(cat)
            continue
        
        # Logging de scores para debugging
        if debug_scoring:
            _log_score_table(buckets, cat)
        
        # Ordenar por puntuación (mejor primero)
        cands.sort(key=lambda x: x["score"], reverse=True)
        best = cands[0]

        # --- ESTRATEGIA DE VECINDAD ---
        # Si el mejor es un fragmento, asumimos que el documento está dividido.
        # Nos llevamos todos los archivos específicos (no combos) con buen score.
        if best["is_fragment"]:
            logger.info(f"[{cat}] Fragmento detectado: {best['path'].name} (score: {best['score']})")
            logger.info(f"[{cat}] Aplicando estrategia de vecindad (tolerancia: -60)")
            
            # Ventana de tolerancia: archivos con score cercano al mejor
            tolerance_threshold = best["score"] - 60
            relacionados = [
                c["path"] for c in cands 
                if c["score"] > tolerance_threshold
                # Esto incluirá tanto fragmentos como archivos específicos sin etiqueta
            ]
            
            if debug_scoring or len(relacionados) > 1:
                logger.info(
                    f"[{cat}] Seleccionados {len(relacionados)} archivo(s) relacionados: "
                    + ", ".join(p.name for p in relacionados)
                )
            
            final_files.extend(relacionados)
        else:
            # Si el mejor no es fragmento (ej: DNI_COMPLETO.pdf), es el ganador único
            logger.info(f"[{cat}] Archivo único seleccionado: {best['path'].name} (score: {best['score']})")
            final_files.append(best["path"])
        
        covered.append(cat)

    # Añadir ESCR si existe aunque no sea obligatorio
    if is_company and not require_escr and buckets.get("ESCR"):
        cands = sorted(buckets["ESCR"], key=lambda x: x["score"], reverse=True)
        final_files.append(cands[0]["path"])
        covered.append("ESCR")

    # Dedup manteniendo orden
    archivos_unicos = []
    seen = set()
    for p in final_files:
        if p not in seen:
            archivos_unicos.append(p)
            seen.add(p)

    if missing and strict:
        raise RequiredClientDocumentsError(f"Faltan docs en {ruta_docu.name}: {', '.join(missing)}")

    # 3. Fusión con PDFtk
    if merge_if_multiple and len(archivos_unicos) > 1:
        pdftk_exe = Path(pdftk_path)
        if pdftk_exe.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"{output_label}_merged.pdf"
            try:
                cmd = [str(pdftk_exe)] + [str(p) for p in archivos_unicos] + ["cat", "output", str(out_path)]
                subprocess.run(cmd, check=True, capture_output=True)
                archivos_unicos = [out_path]
                logger.info(f"Fusión exitosa: {out_path.name}")
            except Exception as e:
                logger.error(f"Error fusionando con PDFtk: {e}")
        else:
            logger.warning("PDFtk no encontrado. Se envían archivos separados.")

    return SelectedClientDocuments(
        files_to_upload=archivos_unicos,
        covered_terms=covered,
        missing_terms=missing
    )

def build_required_client_documents_for_payload(
    payload: dict,
    *,
    strict: bool = True,
    merge_if_multiple: bool = False,
) -> list[Path]:
    """API principal."""
    client = client_identity_from_payload(payload)
    base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    
    ruta = get_ruta_cliente_documentacion(client, base_path=base_path)
    
    selected = select_required_client_documents(
        ruta_docu=ruta,
        is_company=client.is_company,
        strict=strict,
        merge_if_multiple=merge_if_multiple,
        output_label=str(payload.get("idRecurso", "client"))
    )
    return selected.files_to_upload