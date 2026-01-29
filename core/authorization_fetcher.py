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


def get_client_type_from_db(numclient: int, conn_str: str) -> Literal["particular", "empresa"]:
    """
    Determina el tipo de cliente consultando SQL Server.
    
    Consulta la columna Nombrefiscal de la tabla Clientes.Clientes:
    - Si tiene valor (no NULL y no vacío) → Empresa
    - Si es NULL o vacío → Particular
    
    Args:
        numclient: Número de cliente
        conn_str: Connection string de SQL Server
    
    Returns:
        "empresa" si tiene Nombrefiscal, "particular" si no
    """
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute("SELECT Nombrefiscal FROM Clientes.Clientes WHERE numclient = ?", (numclient,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] and str(row[0]).strip():
            logger.debug(f"Cliente {numclient} es empresa (Nombrefiscal: {row[0]})")
            return "empresa"
        
        logger.debug(f"Cliente {numclient} es particular")
        return "particular"
    except Exception as e:
        logger.error(f"Error determinando tipo de cliente {numclient}: {e}")
        # Por defecto, asumir particular
        return "particular"


def find_authorization_in_tmp(
    numclient: int, 
    client_type: Optional[Literal["particular", "empresa"]] = None
) -> Optional[Path]:
    """
    Busca archivo de autorización en carpetas temporales.
    
    Patrones de búsqueda:
    - Particular: Autoriza_Particular_*_{numclient}.pdf en \\server-doc\tmp_pdf
    - Empresa: Autoriza_Empresa_solo_*_{numclient}.pdf en \\server-doc\tmp_pdf\SEDES
    
    Args:
        numclient: Número de cliente
        client_type: Tipo de cliente. Si es None, busca ambos tipos.
    
    Returns:
        Path del archivo encontrado o None
    """
    logger.debug(f"Buscando autorización para cliente {numclient} (tipo: {client_type or 'ambos'})")
    
    search_patterns = []
    
    if client_type is None or client_type == "particular":
        # Buscar en tmp_pdf (particulares)
        pattern_particular = TMP_PDF_PATH / f"Autoriza_Particular_*_{numclient}.pdf"
        search_patterns.append(("particular", pattern_particular))
    
    if client_type is None or client_type == "empresa":
        # Buscar en tmp_pdf/SEDES (empresas)
        pattern_empresa = TMP_PDF_SEDES_PATH / f"Autoriza_Empresa_solo_*_{numclient}.pdf"
        search_patterns.append(("empresa", pattern_empresa))
    
    for tipo, pattern in search_patterns:
        try:
            matches = list(glob.glob(str(pattern)))
            if matches:
                # Si hay múltiples, tomar el más reciente
                if len(matches) > 1:
                    matches.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                    logger.warning(f"Múltiples autorizaciones encontradas para {numclient}, usando la más reciente")
                
                auth_file = Path(matches[0])
                logger.info(f"✓ Autorización encontrada ({tipo}): {auth_file.name}")
                return auth_file
        except Exception as e:
            logger.warning(f"Error buscando en {pattern}: {e}")
            continue
    
    logger.debug(f"No se encontró autorización para cliente {numclient}")
    return None


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
    source_path: Path,
    expediente: str,
    numclient: int,
    client_type: Literal["particular", "empresa"]
) -> bool:
    """
    Mueve el archivo de autorización a las carpetas de destino.
    
    Destinos:
    1. \\SERVER-DOC\Documentacion recursos\{letra}\{expediente}\
    2. \\SERVER-DOC\Documentacion\{letra}\{numclient}\ (si existe)
    
    Args:
        source_path: Path del archivo de autorización en tmp
        expediente: Número de expediente
        numclient: Número de cliente
        client_type: Tipo de cliente (particular o empresa)
    
    Returns:
        True si se movió exitosamente a al menos un destino
    """
    if not source_path.exists():
        logger.error(f"Archivo fuente no existe: {source_path}")
        return False
    
    success = False
    
    # Nombre del archivo de destino (simplificado)
    if client_type == "particular":
        dest_filename = f"Autoriza_Particular_{numclient}.pdf"
    else:
        dest_filename = f"Autoriza_Empresa_{numclient}.pdf"
    
    # 1. Copiar a carpeta de expediente
    exp_folder = get_expediente_folder_path(expediente)
    if exp_folder:
        try:
            dest_path = exp_folder / dest_filename
            shutil.copy2(source_path, dest_path)
            logger.info(f"✓ Autorización copiada a expediente: {dest_path}")
            success = True
        except Exception as e:
            logger.error(f"Error copiando a carpeta de expediente: {e}")
    else:
        logger.warning(f"No se encontró carpeta de expediente para: {expediente}")
    
    # 2. Copiar a carpeta de cliente (si existe)
    client_folder = get_client_folder_path(numclient)
    if client_folder:
        try:
            dest_path = client_folder / dest_filename
            shutil.copy2(source_path, dest_path)
            logger.info(f"✓ Autorización copiada a cliente: {dest_path}")
            success = True
        except Exception as e:
            logger.error(f"Error copiando a carpeta de cliente: {e}")
    else:
        logger.debug(f"No se encontró carpeta de cliente para: {numclient}")
    
    # 3. Eliminar el archivo temporal (opcional)
    # Por ahora lo dejamos para debugging
    # try:
    #     source_path.unlink()
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
