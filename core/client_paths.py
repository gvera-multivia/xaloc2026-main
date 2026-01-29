"""
Utilidades compartidas para el cálculo de rutas de clientes.
"""

import re
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


def get_alpha_folder(char: str) -> str:
    """Retorna la subcarpeta alfabética correspondiente."""
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
        
    return base / get_alpha_folder(char_to_use) / name
