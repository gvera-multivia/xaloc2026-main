from __future__ import annotations

import logging
import os
import re
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
    sujeto_recurso: str | None = None
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
    sujeto_recurso = (
        (payload.get("sujeto_recurso") or payload.get("SujetoRecurso") or "")
    ).strip() or None
    
    # Debug logging para trazar el valor de sujeto_recurso
    logger.debug(f"[ClientIdentity] payload keys: {list(payload.keys())}")
    logger.debug(f"[ClientIdentity] sujeto_recurso extraído: '{sujeto_recurso}'")
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
            if not (nombre and ap1 and ap2):
                raise RequiredClientDocumentsError("Faltan datos completos para persona FÍSICA.")
            return ClientIdentity(
                is_company=False,
                sujeto_recurso=sujeto_recurso,
                nombre=nombre,
                apellido1=ap1,
                apellido2=ap2,
            )

    # Fallbacks de nombres directos
    empresa = (payload.get("empresa") or payload.get("razon_social") or "").strip()
    if empresa: return ClientIdentity(is_company=True, sujeto_recurso=sujeto_recurso, empresa=empresa)

    nombre = (payload.get("cliente_nombre") or "").strip()
    ap1 = (payload.get("cliente_apellido1") or payload.get("apellido1") or "").strip()
    ap2 = (payload.get("cliente_apellido2") or payload.get("apellido2") or "").strip()
    if nombre and ap1 and ap2:
        return ClientIdentity(
            is_company=False,
            sujeto_recurso=sujeto_recurso,
            nombre=nombre,
            apellido1=ap1,
            apellido2=ap2,
        )

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

    def _first_alnum_char(value: str) -> str:
        for ch in (value or "").strip():
            if ch.isalnum():
                return ch
        return (value or "").strip()[:1] or "?"

    if client.sujeto_recurso:
        folder_name = re.sub(r"\s+", " ", client.sujeto_recurso.strip()).rstrip("!.,?;:")
        folder = base / _get_alpha_folder(_first_alnum_char(folder_name)) / folder_name
        logger.info(f"[Ruta Docs] Usando SUJETO_RECURSO: '{folder_name}' -> {folder}")
    elif client.is_company:
        name = client.empresa.strip().rstrip("!.,?;:")
        folder = base / _get_alpha_folder(_first_alnum_char(name)) / name
        logger.info(f"[Ruta Docs] Usando EMPRESA: '{name}' -> {folder}")
    else:
        full_name = f"{client.nombre} {client.apellido1.upper()} {client.apellido2.upper()}".strip()
        folder = base / _get_alpha_folder(_first_alnum_char(client.nombre)) / full_name
        logger.info(f"[Ruta Docs] Usando NOMBRE+APELLIDOS: '{full_name}' -> {folder}")

    # Jerarquía de carpetas: RECURSOS es la máxima prioridad
    for subname in ["DOCUMENTACION RECURSOS", "DOCUMENTACION", "DOCUMENTACIÓN"]:
        if (folder / subname).exists():
            logger.info(f"[Ruta Docs] Subcarpeta encontrada: {folder / subname}")
            return folder / subname
    logger.info(f"[Ruta Docs] Sin subcarpeta DOCUMENTACION, usando: {folder}")
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
    path_upper = str(path).upper()
    ext = path.suffix.lower()

    # 1. Filtro de extensión
    if ext == ".pdf":
        score += 50
    elif ext in [".jpg", ".jpeg", ".png"]:
        score += 20
    else:
        return -1000

    # 2. PRIORIDAD RECURSOS (Bonus masivo)
    if "RECURSOS" in path_upper:
        score += 1000

    # 3. Especificidad vs Combos
    if len(categories_found) > 1:
        score -= 45
    elif len(categories_found) == 1:
        score += 35

    # 4. Keywords de Confianza
    if any(k in name for k in ["firmad", "firmat", "original", "completo"]):
        score += 50

    # REGLA "SOLO": penaliza para que pierda contra la versión normal
    if "_solo_" in name or " solo " in name or name.endswith("solo.pdf"):
        score -= 10

    if (
        "comp." in name
        or "comprimido" in name
        or "_cmp" in name
        or " cmp" in name
        or name.endswith("cmp.pdf")
    ):
        score += 20

    # 5. Detección de fragmentos
    is_frag = any(
        k in name
        for k in [
            "anverso",
            "reverso",
            "cara",
            "part",
            "darrera",
            "trasera",
            "front",
            "back",
            "pag",
            "pág",
            "página",
        ]
    )
    has_num = bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", name))
    if is_frag or has_num:
        score += 15

    # 6. Penalización de basura / antiguos
    if any(k in name for k in ["old", "antiguo", "vencido", "copia"]):
        score -= 200

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
    # SOLO AUT es estrictamente obligatorio - el resto son opcionales
    # Si es empresa, ESCR es opcional a menos que se fuerce por env
    require_escr = os.getenv("CLIENT_DOCS_REQUIRE_ESCR", "0").lower() in ("1", "true", "y")
    
    # Mapeo de categorías a términos de búsqueda
    categories_map = {
        "AUT": ["aut"],
        "DNI": ["dni", "nie", "pasaporte"],
        "CIF": ["cif", "nif"] if is_company else [],
        "ESCR": ["escr", "constitu", "titularidad", "notar", "poder", "acta", "mercantil"] if is_company else [],
    }
    
    # Solo AUT es obligatorio; DNI, CIF, ESCR son opcionales (se añaden si existen)
    strictly_required = ["AUT"]
    optional_cats = ["DNI"]
    if is_company:
        optional_cats.append("CIF")
        if require_escr:
            strictly_required.append("ESCR")  # Solo si se fuerza por env
        else:
            optional_cats.append("ESCR")
    
    # Buscamos tanto los obligatorios como los opcionales
    required_cats = strictly_required + optional_cats

    # Cubetas para clasificar candidatos
    buckets: dict[str, list[dict]] = defaultdict(list)

    # 1. Clasificación y Puntuación
    all_files = [p for p in ruta_docu.rglob("*") if p.is_file()]

    # --- REGLA DE ORO: SI HAY RECURSOS, IGNORAMOS EL RESTO ---
    has_recursos = any("DOCUMENTACION RECURSOS" in str(p).upper() for p in all_files)
    if has_recursos:
        filtered: list[Path] = []
        for p in all_files:
            up = str(p).upper()
            if ("DOCUMENTACION" in up or "DOCUMENTACIÓN" in up) and "RECURSOS" not in up:
                continue
            filtered.append(p)
        all_files = filtered

    for file_path in all_files:
        
        cats_found = _analyze_file_categories(file_path.name, categories_map)
        if not cats_found: continue

        score = _calculate_file_score(file_path, cats_found)
        if score < 0: continue

        for cat in cats_found:
            low = file_path.name.lower()
            is_fragment = any(
                x in low
                for x in [
                    "anverso",
                    "reverso",
                    "cara",
                    "part",
                    "darrera",
                    "trasera",
                    "front",
                    "back",
                    "pag",
                    "pág",
                    "página",
                ]
            ) or bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", low))
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

    # 2. Selección inteligente por cubeta (misma lógica que correr_test.py)
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

        # --- LÓGICA ESPECIAL PARA AUTORIZACIONES "SOLO" ---
        if cat == "AUT" and len(cands) > 1:
            sin_solo = [c for c in cands if "solo" not in c["path"].name.lower()]
            if sin_solo:
                best_sin_solo_score = sin_solo[0]["score"]
                cands = [
                    c
                    for c in cands
                    if "solo" not in c["path"].name.lower() or c["score"] > best_sin_solo_score
                ]
                cands.sort(key=lambda x: x["score"], reverse=True)

        if not cands:
            if cat not in missing:
                missing.append(cat)
            continue

        best = cands[0]

        # --- SELECCIÓN MULTI-SOCIO (Ventana de 20 pts) ---
        top_tier = [c["path"] for c in cands if c["score"] > (best["score"] - 20)]
        final_files.extend(top_tier)

        # --- SELECCIÓN FRAGMENTOS (Ventana de 65 pts) ---
        if best["is_fragment"]:
            fragmentos = [c["path"] for c in cands if c["is_fragment"] and c["score"] > (best["score"] - 65)]
            final_files.extend(fragmentos)
        
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

    # Solo fallar si falta documentación ESTRICTAMENTE obligatoria (AUT)
    missing_strict = [cat for cat in missing if cat in strictly_required]
    if missing_strict and strict:
        raise RequiredClientDocumentsError(f"Faltan docs obligatorios en {ruta_docu.name}: {', '.join(missing_strict)}")
    
    # Log de documentos opcionales no encontrados (no es error)
    missing_optional = [cat for cat in missing if cat not in strictly_required]
    if missing_optional:
        logger.info(f"[Docs Opcionales] No encontrados (OK): {', '.join(missing_optional)}")

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
