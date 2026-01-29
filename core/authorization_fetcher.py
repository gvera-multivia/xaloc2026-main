"""
Módulo de gestión de archivos de autorización de clientes.

Maneja la búsqueda, verificación y movimiento de archivos de autorización
desde las carpetas temporales a las carpetas de destino.
"""

import os
import glob
import shutil
import logging
import pyodbc
from pathlib import Path
from typing import Optional, Literal, List
from datetime import datetime

logger = logging.getLogger("[AUTH-FETCHER]")

# Rutas de red donde GESDOC genera los PDFs
TMP_PDF_PATH = Path(r"\\server-doc\tmp_pdf")
TMP_PDF_SEDES_PATH = Path(r"\\server-doc\tmp_pdf\SEDES")

# Rutas base de documentación
DOCS_BASE_PATH = Path(r"\\SERVER-DOC\Documentacion")
DOCS_RECURSOS_BASE_PATH = Path(r"\\SERVER-DOC\Documentacion recursos")


def get_client_info_from_db(numclient: int, conn_str: str) -> dict:
    """
    Obtiene información completa del cliente desde SQL Server.
    """
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        # Usamos la tabla 'clientes' y la columna 'numerocliente' tal como se ve en el resto del proyecto
        query = """
            SELECT Nombrefiscal, Nombre, Apellido1, Apellido2 
            FROM clientes 
            WHERE numerocliente = ?
        """
        cursor.execute(query, (numclient,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            columns = [c[0] for c in cursor.description]
            return dict(zip(columns, row))
        
        return {}
    except Exception as e:
        logger.error(f"Error consultando datos del cliente {numclient}: {e}")
        return {}


def get_client_type_from_db(numclient: int, conn_str: str) -> Literal["particular", "empresa"]:
    """
    Determina el tipo de cliente consultando SQL Server.
    """
    info = get_client_info_from_db(numclient, conn_str)
    if not info:
        return "particular"
        
    nombrefiscal = info.get("Nombrefiscal")
    if nombrefiscal and str(nombrefiscal).strip():
        return "empresa"
    
    return "particular"


def find_authorization_in_tmp(
    numclient: int, 
    client_type: Optional[Literal["particular", "empresa"]] = None
) -> Optional[Path]:
    """
    Busca el archivo de autorización en las carpetas temporales de GESDOC.
    
    Busca archivos que coincidan con el patrón:
    - Particular: Autoriza_Particular_*_{numclient}.pdf en \\server-doc\tmp_pdf
    - Empresa: Autoriza_Empresa_solo_*_{numclient}.pdf en \\server-doc\tmp_pdf\SEDES
    """
    patterns = []
    if client_type == "particular" or client_type is None:
        patterns.append((TMP_PDF_PATH, f"Autoriza_Particular_*_{numclient}.pdf"))
    
    if client_type == "empresa" or client_type is None:
        patterns.append((TMP_PDF_SEDES_PATH, f"Autoriza_Empresa_solo_*_{numclient}.pdf"))

    found_files = []
    for base_path, pattern in patterns:
        if not base_path.exists():
            logger.warning(f"Ruta temporal no accesible: {base_path}")
            continue
            
        matches = list(base_path.glob(pattern))
        if matches:
            found_files.extend(matches)

    if not found_files:
        return None

    # Si hay varios, devolver el más reciente por fecha de modificación
    found_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    if len(found_files) > 1:
        logger.warning(f"Múltiples autorizaciones encontradas para {numclient}, usando la más reciente")
    
    return found_files[0]


def get_client_folder_path(numclient: int) -> Optional[Path]:
    """
    Obtiene la ruta de la carpeta del cliente en Documentacion.
    
    La estructura es: \\SERVER-DOC\Documentacion\{letra}\{numclient}
    Donde {letra} es la primera letra del apellido del cliente.
    
    Args:
        numclient: Número de cliente
    
    Returns:
        Path de la carpeta del cliente si existe, None si no
    """
    # Buscar en todas las subcarpetas alfabéticas
    for letter_folder in DOCS_BASE_PATH.iterdir():
        if letter_folder.is_dir() and len(letter_folder.name) == 1:
            client_folder = letter_folder / str(numclient)
            if client_folder.exists() and client_folder.is_dir():
                return client_folder
    
    return None


def get_expediente_folder_path(expediente: str) -> Optional[Path]:
    """
    Obtiene la ruta de la carpeta del expediente en Documentacion recursos.
    
    La estructura es: \\SERVER-DOC\Documentacion recursos\{letra}\{expediente}
    
    Args:
        expediente: Número de expediente (ej: "2025/191501-MUL")
    
    Returns:
        Path de la carpeta del expediente si existe, None si no
    """
    # Normalizar expediente para nombre de carpeta (reemplazar / por -)
    folder_name = expediente.replace("/", "-")
    
    # Buscar en todas las subcarpetas alfabéticas
    for letter_folder in DOCS_RECURSOS_BASE_PATH.iterdir():
        if letter_folder.is_dir() and len(letter_folder.name) == 1:
            exp_folder = letter_folder / folder_name
            if exp_folder.exists() and exp_folder.is_dir():
                return exp_folder
    
    return None


def move_authorization_to_destinations(
    auth_file: Path, 
    dest_folders: List[Path]
) -> bool:
    """
    Mueve/Copia la autorización a las carpetas de destino especificadas.
    
    Args:
        auth_file: Path del archivo origen
        dest_folders: Lista de carpetas destino
    
    Returns:
        True si se copió al menos a una carpeta
    """
    if not auth_file or not auth_file.exists():
        logger.error(f"Archivo de origen no existe: {auth_file}")
        return False

    success_count = 0
    for folder in dest_folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            dest_path = folder / auth_file.name
            
            logger.info(f"Copiando {auth_file.name} a {folder}")
            shutil.copy2(auth_file, dest_path)
            success_count += 1
        except Exception as e:
            logger.error(f"Error copiando a {folder}: {e}")

    return success_count > 0
    #     logger.debug(f"Archivo temporal eliminado: {source_path}")
    # except Exception as e:
    #     logger.warning(f"No se pudo eliminar archivo temporal: {e}")
    
    return success


def verify_network_access() -> bool:
    """
    Verifica que tengamos acceso a las rutas de red necesarias.
    
    Returns:
        True si todas las rutas son accesibles
    """
    paths_to_check = [
        TMP_PDF_PATH,
        TMP_PDF_SEDES_PATH,
        DOCS_BASE_PATH,
        DOCS_RECURSOS_BASE_PATH
    ]
    
    all_accessible = True
    for path in paths_to_check:
        if not path.exists():
            logger.error(f"Ruta de red no accesible: {path}")
            all_accessible = False
        else:
            logger.debug(f"✓ Ruta accesible: {path}")
    
    return all_accessible
