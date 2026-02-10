"""
Utilidades compartidas para el cálculo de rutas de clientes.
"""

import re
import unicodedata
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class ClientIdentity:
    is_company: bool
    sujeto_recurso: Optional[str] = None
    empresa: Optional[str] = None
    nombre: Optional[str] = None
    apellido1: Optional[str] = None
    apellido2: Optional[str] = None


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
        return f"{client.nombre} {client.apellido1.upper()} {client.apellido2.upper()}".strip()


def normalize_client_folder_name(value: str) -> str:
    """Normaliza el nombre para comparar rutas con diferencias menores."""
    if value is None:
        return ""
    text = value.strip().upper().replace("_", " ")
    text = strip_accents(text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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

    return candidate
