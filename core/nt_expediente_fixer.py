"""
nt_expediente_fixer.py - Corrección de expedientes con formato NT/ incorrecto.

Este módulo proporciona funciones para detectar y corregir expedientes
que tienen formato NT/ cuando el formato correcto YYYY/NNNNNN-MUL 
existe en pubExp.publicación.

Uso:
    from core.nt_expediente_fixer import is_nt_pattern, fix_nt_expediente
    
    if is_nt_pattern(expediente):
        corrected = fix_nt_expediente(conn_str, id_exp)
        if corrected:
            # Usar corrected como el expediente válido
"""

import logging
import re
from typing import Optional

import pyodbc

logger = logging.getLogger("nt_expediente_fixer")

# =============================================================================
# PATRONES
# =============================================================================

# Regex Python para detectar formato NT/
NT_PATTERN_REGEX = re.compile(r'^NT/\d{8}/\d{4}/\d{9,10}')

# Patrones SQL LIKE para detectar NT (usados en los WHERE de UPDATE)
PATRON_NT9_SQL = '%NT/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]%'
PATRON_NT10_SQL = '%NT/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]%'

# Patrón SQL para buscar el expediente correcto YYYY/NNNNNN-MUL (15 caracteres)
PATRON_BUSQUEDA_SQL = '%[0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9]-MUL%'

# Longitud del expediente correcto (YYYY/NNNNNN-MUL = 15 chars)
EXPEDIENTE_CORRECTO_LEN = 15


# =============================================================================
# FUNCIONES PÚBLICAS
# =============================================================================

def is_nt_pattern(expediente: str) -> bool:
    """
    Detecta si un expediente tiene el formato NT/ incorrecto.
    
    Args:
        expediente: El string del expediente a verificar.
        
    Returns:
        True si el expediente empieza con NT/... en el formato conocido.
    """
    if not expediente:
        return False
    return bool(NT_PATTERN_REGEX.match(expediente.strip()))


def fix_nt_expediente(conn_str: str, id_exp: int) -> Optional[str]:
    """
    Intenta corregir un expediente con formato NT/ extrayendo el valor
    correcto desde pubExp.publicación y actualizando las tablas afectadas.
    
    Esta función:
    1. Busca el patrón YYYY/NNNNNN-MUL en pubExp.publicación
    2. Si lo encuentra, actualiza: expedientes, recursos.RecursosExp, 
       ListasPresentacion, pubExp
    3. Retorna el expediente corregido o None si no fue posible
    
    Args:
        conn_str: Connection string para SQL Server.
        id_exp: ID del expediente a corregir (idexpediente en tabla expedientes).
        
    Returns:
        El expediente corregido (ej: "2024/123456-MUL") o None si no se pudo corregir.
    """
    if not id_exp:
        logger.warning("fix_nt_expediente llamado sin id_exp válido")
        return None
    
    logger.info(f"🔧 Intentando corregir expediente NT/ para idExp={id_exp}")
    
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        
        # PASO 1: Extraer el nuevo expediente desde pubExp.publicación
        cursor.execute("""
            SELECT TOP 1 
                SUBSTRING(p.publicación, PATINDEX(?, p.publicación), ?) AS nuevo_exp
            FROM pubExp p
            JOIN recursos.RecursosExp r ON r.IdPublic = p.idpublic
            WHERE r.IdExp = ?
              AND PATINDEX(?, p.publicación) > 0
        """, (PATRON_BUSQUEDA_SQL, EXPEDIENTE_CORRECTO_LEN, id_exp, PATRON_BUSQUEDA_SQL))
        
        row = cursor.fetchone()
        if not row or not row[0]:
            logger.warning(f"❌ No se encontró patrón correcto en pubExp.publicación para idExp={id_exp}")
            conn.close()
            return None
        
        nuevo_exp = row[0].strip()
        logger.info(f"✓ Patrón correcto encontrado: '{nuevo_exp}'")
        
        # PASO 2: Verificar que hay registros con formato NT/ para actualizar
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT 1 AS x FROM expedientes WHERE idexpediente = ? AND (numexpediente LIKE ? OR numexpediente LIKE ?)
                UNION ALL
                SELECT 1 AS x FROM recursos.RecursosExp WHERE IdExp = ? AND (Expedient LIKE ? OR Expedient LIKE ?)
                UNION ALL
                SELECT 1 AS x FROM ListasPresentacion WHERE Idexpediente = ? AND (numexpediente LIKE ? OR numexpediente LIKE ?)
                UNION ALL
                SELECT 1 AS x FROM pubExp p JOIN recursos.RecursosExp r ON r.IdPublic = p.idpublic 
                WHERE r.IdExp = ? AND (p.Exp LIKE ? OR p.Exp LIKE ?)
            ) AS combinados
        """, (
            id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL,
            id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL,
            id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL,
            id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL
        ))
        
        count_row = cursor.fetchone()
        if not count_row or count_row[0] == 0:
            logger.info(f"ℹ️  No hay registros con formato NT/ para actualizar en idExp={id_exp}")
            conn.close()
            return None
        
        logger.info(f"📝 Encontrados {count_row[0]} registros con formato NT/ para actualizar")
        
        # PASO 3: Ejecutar los UPDATEs (dentro de una transacción)
        cursor.execute("BEGIN TRANSACTION")
        
        try:
            # UPDATE expedientes
            cursor.execute("""
                UPDATE expedientes 
                SET numexpediente = ?
                WHERE idexpediente = ? 
                  AND (numexpediente LIKE ? OR numexpediente LIKE ?)
            """, (nuevo_exp, id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL))
            rows_exp = cursor.rowcount
            
            # UPDATE recursos.RecursosExp
            cursor.execute("""
                UPDATE recursos.RecursosExp 
                SET Expedient = ?
                WHERE IdExp = ? 
                  AND (Expedient LIKE ? OR Expedient LIKE ?)
            """, (nuevo_exp, id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL))
            rows_rec = cursor.rowcount
            
            # UPDATE ListasPresentacion
            cursor.execute("""
                UPDATE ListasPresentacion 
                SET numexpediente = ?
                WHERE Idexpediente = ? 
                  AND (numexpediente LIKE ? OR numexpediente LIKE ?)
            """, (nuevo_exp, id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL))
            rows_lp = cursor.rowcount
            
            # UPDATE pubExp
            cursor.execute("""
                UPDATE p 
                SET p.Exp = ?
                FROM pubExp p 
                JOIN recursos.RecursosExp r ON r.IdPublic = p.idpublic
                WHERE r.IdExp = ? 
                  AND (p.Exp LIKE ? OR p.Exp LIKE ?)
            """, (nuevo_exp, id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL))
            rows_pub = cursor.rowcount
            
            cursor.execute("COMMIT")
            
            logger.info(
                f"✅ Expediente corregido exitosamente: '{nuevo_exp}' "
                f"(expedientes={rows_exp}, RecursosExp={rows_rec}, "
                f"ListasPresentacion={rows_lp}, pubExp={rows_pub})"
            )
            
            conn.close()
            return nuevo_exp
            
        except Exception as e:
            cursor.execute("ROLLBACK")
            logger.error(f"❌ Error durante UPDATE, haciendo rollback: {e}")
            conn.close()
            return None
            
    except Exception as e:
        logger.error(f"❌ Error de conexión/consulta en fix_nt_expediente: {e}")
        return None
