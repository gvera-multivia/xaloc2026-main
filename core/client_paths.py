"""
Utilidades compartidas para el cálculo de rutas de clientes.
"""

import re
import os
import unicodedata
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


DEFAULT_WINDOWS_CLIENT_DOCS_PATH = r"\\SERVER-DOC\clientes"
DEFAULT_LINUX_CLIENT_DOCS_PATH = "/mnt/clientes"

@dataclass(frozen=True)
class ClientIdentity:
    is_company: bool
    sujeto_recurso: Optional[str] = None
    empresa: Optional[str] = None
    nombre: Optional[str] = None
    apellido1: Optional[str] = None
    apellido2: Optional[str] = None


def resolve_client_docs_base_path() -> str:
    """
    Resuelve la ruta base de documentacion de clientes de forma segura por plataforma.

    Regla anti-fantasma:
    - En Linux, nunca usar fallback UNC de Windows.
    - Si el env trae UNC en Linux, se fuerza /mnt/clientes para evitar crear
      carpetas locales como '\\\\SERVER-DOC\\...' dentro del workspace.
    """
    env_value = (os.getenv("CLIENT_DOCS_BASE_PATH") or "").strip()
    env_windows = (os.getenv("CLIENT_DOCS_BASE_PATH_WINDOWS") or "").strip()
    env_linux = (os.getenv("CLIENT_DOCS_BASE_PATH_LINUX") or "").strip()
    if env_value:
        if os.name != "nt" and env_value.startswith("\\\\"):
            return env_linux or DEFAULT_LINUX_CLIENT_DOCS_PATH
        if os.name == "nt":
            env_lower = env_value.replace("\\", "/").lower()
            # En Windows, evitar rutas Linux tipo /mnt/... heredadas de contenedor.
            if env_lower.startswith("/mnt/") or env_lower.startswith("mnt/"):
                return env_windows or DEFAULT_WINDOWS_CLIENT_DOCS_PATH
        return env_value

    if os.name != "nt":
        return env_linux or DEFAULT_LINUX_CLIENT_DOCS_PATH
    return env_windows or DEFAULT_WINDOWS_CLIENT_DOCS_PATH


def strip_accents(text: str) -> str:
    """Elimina tildes y normaliza a caracteres básicos."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def get_alpha_folder(char: str) -> str:
    """Retorna la subcarpeta alfabética correspondiente."""
    char = strip_accents(char).upper()
    if char in "0123456789": return "0-9 (NUMEROS)"
    if char in "ABC": return "A-C"
    if char in "DE": return "D-E"
    if char in "FGHIJ": return "F-J"
    if char in "KL": return "K-L"
    if char in "MNO": return "M-O"
    if char in "PQRSTU": return "P-U"
    if char in "VWXYZ": return "V-Z"
    return "Desconocido"


def first_alnum_char(value: str) -> str:
    """Retorna el primer carácter alfanumérico."""
    for ch in (value or "").strip():
        if ch.isalnum(): return ch
    return (value or "").strip()[:1] or "?"


def get_client_folder_name(client: ClientIdentity) -> str:
    """Calcula el nombre de la carpeta del cliente."""
    if client.sujeto_recurso:
        return re.sub(r"\s+", " ", client.sujeto_recurso.strip()).rstrip("!.,?;:")
    elif client.is_company:
        return client.empresa.strip().rstrip("!.,?;:")
    else:
        nombre = (client.nombre or "").strip()
        apellido1 = (client.apellido1 or "").strip().upper()
        apellido2 = (client.apellido2 or "").strip().upper()
        parts = [p for p in [nombre, apellido1, apellido2] if p]
        return " ".join(parts).strip()


def normalize_client_folder_name(value: str) -> str:
    """Normaliza el nombre para comparar rutas con diferencias menores."""
    if value is None:
        return ""
    text = value.strip().upper()
    text = strip_accents(text)
    # Tratamos los signos de puntuación como espacios para evitar unir palabras (ej: MIKEL,GOSHKA -> MIKEL GOSHKA)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def folder_name_matches(existing_name: str, target_name: str) -> bool:
    """
    Compara nombres de carpeta de forma tolerante:
    - sin acentos
    - case-insensitive
    - ignora signos/puntuacion
    - acepta variaciones singular/plural y orden por inclusion de tokens
    """
    existing_norm = normalize_client_folder_name(existing_name)
    target_norm = normalize_client_folder_name(target_name)
    if not existing_norm or not target_norm:
        return existing_norm == target_norm
    if existing_norm == target_norm:
        return True

    existing_words = set(existing_norm.split())
    target_words = set(target_norm.split())
    if target_words.issubset(existing_words):
        return True

    existing_singular = {w.rstrip("s") for w in existing_words}
    target_singular = {w.rstrip("s") for w in target_words}
    return existing_singular == target_singular


def find_or_create_normalized_subfolder(base_path: Path, folder_name: str) -> Path:
    """
    Busca una subcarpeta existente equivalente (accent-insensitive) y, si no existe,
    la crea con `folder_name`.
    """
    if not folder_name:
        return base_path
    if base_path.exists():
        # Prioridad 1: coincidencia exacta (ignorando may/min), para respetar
        # el nombre canónico cuando ya existe (p.ej. con tilde).
        for item in base_path.iterdir():
            if item.is_dir() and item.name.casefold() == folder_name.casefold():
                return item

        # Prioridad 2: coincidencia normalizada/accent-insensitive.
        for item in base_path.iterdir():
            if item.is_dir() and folder_name_matches(item.name, folder_name):
                return item
    target = base_path / folder_name
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_ruta_cliente_documentacion(client: ClientIdentity, base_path: str | Path) -> Path:
    """Calcula la ruta base del cliente (RAÍZ)."""
    base = Path(base_path)
    name = get_client_folder_name(client)
    
    # Determinamos la letra para la carpeta alfabética
    # Si hay sujeto_recurso usaremos su letra, si no, la del nombre/empresa
    char_to_use = ""
    if client.sujeto_recurso:
        char_to_use = first_alnum_char(client.sujeto_recurso)
    elif client.is_company:
        char_to_use = first_alnum_char(client.empresa)
    else:
        char_to_use = first_alnum_char(client.nombre)
        
    alpha_folder = get_alpha_folder(char_to_use)
    candidate = base / alpha_folder / name
    if candidate.exists():
        return candidate

    alpha_dir = base / alpha_folder
    if not alpha_dir.exists():
        return candidate

    target_norm = normalize_client_folder_name(name)
    matches = []
    for sub in alpha_dir.iterdir():
        if sub.is_dir() and normalize_client_folder_name(sub.name) == target_norm:
            matches.append(sub)

    if len(matches) == 1:
        return matches[0]

    # Fallback robusto SMB: si no aparece en la carpeta alfabética esperada,
    # buscar por nombre normalizado en el resto de carpetas de primer nivel.
    if not matches and base.exists():
        for top in base.iterdir():
            if not top.is_dir() or top.name == alpha_folder:
                continue
            try:
                for sub in top.iterdir():
                    if sub.is_dir() and normalize_client_folder_name(sub.name) == target_norm:
                        matches.append(sub)
            except Exception:
                continue
        if len(matches) == 1:
            return matches[0]

    return candidate


def _normalize_phase_text(value: str) -> str:
    text = strip_accents(str(value or "").strip().lower())
    return re.sub(r"\s+", " ", text)


def get_phase_folder_name(fase_procedimiento: str | None) -> str | None:
    """
    Mapea una fase de procedimiento al nombre de subcarpeta de justificantes.
    """
    fase_norm = _normalize_phase_text(fase_procedimiento or "")
    if not fase_norm:
        return None

    motivo_to_folder = {
        "identificacion": "IDENTIFICACIONES",
        "denuncia": "ALEGACIONES",
        "propuesta de resolucion": "ALEGACIONES",
        "extraordinario de revision": "EXTRAORDINARIOS DE REVISION",
        "subsanacion": "SUBSANACIONES",
        "reclamaciones": "RECLAMACIONES",
        "requerimiento embargo": "EMBARGOS",
        "sancion": "SANCIONES",
        "apremio": "APREMIOS",
        "embargo": "EMBARGOS",
    }

    for key, folder_name in motivo_to_folder.items():
        if key in fase_norm:
            return folder_name
    return None


def get_ruta_recursos_telematicos(
    *,
    client: ClientIdentity,
    base_path: str | Path,
    fase_procedimiento: str | None = None,
) -> Path:
    """
    Devuelve la ruta final de justificantes:
    <cliente>/RECURSOS TELEMATICOS[/<subcarpeta por fase>]
    """
    ruta_cliente = get_ruta_cliente_documentacion(client, base_path=base_path)
    ruta_recursos = find_or_create_normalized_subfolder(ruta_cliente, "RECURSOS TELEMATICOS")
    phase_folder = get_phase_folder_name(fase_procedimiento)
    if not phase_folder:
        return ruta_recursos
    return find_or_create_normalized_subfolder(ruta_recursos, phase_folder)
