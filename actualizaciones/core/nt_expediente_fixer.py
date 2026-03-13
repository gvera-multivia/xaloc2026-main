"""
nt_expediente_fixer.py - Correccion de expedientes con formato NT/ incorrecto.

Detecta registros NT/... y sustituye por expediente valido encontrado en
pubExp.publicacion. Acepta dos formatos validos:
- YYYY/NNNNNN-MUL
- YYYY/NNNNNN (sin sufijo -MUL)
"""

import logging
import re
from typing import Optional

import pyodbc

logger = logging.getLogger("nt_expediente_fixer")

# Regex Python para detectar formato NT/
NT_PATTERN_REGEX = re.compile(r"^NT/\d{8}/\d{4}/\d{9,10}")

# Patrones SQL LIKE para detectar NT (usados en WHERE de UPDATE)
PATRON_NT9_SQL = "%NT/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]%"
PATRON_NT10_SQL = "%NT/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]%"

# Patrones SQL para localizar texto candidato en publicacion
PATRON_BUSQUEDA_MUL_SQL = "%[0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9]-MUL%"
PATRON_BUSQUEDA_BASE_SQL = "%[0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9]%"

# Extrae YYYY/NNNN... con o sin -MUL desde texto libre
EXP_EXTRACT_REGEX = re.compile(r"\b(?:19|20)\d{2}/\d+(?:-(?:MUL|SAD))?\b", re.IGNORECASE)


def is_nt_pattern(expediente: str) -> bool:
    if not expediente:
        return False
    return bool(NT_PATTERN_REGEX.match(expediente.strip()))


def _extract_valid_expediente_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    m = EXP_EXTRACT_REGEX.search(str(text).upper())
    if not m:
        return None
    return m.group(0).upper().strip()


def fix_nt_expediente(conn_str: str, id_exp: int) -> Optional[str]:
    """
    Corrige expediente NT/... buscando el valor valido en pubExp.publicacion.

    Returns:
        expediente corregido (con o sin -MUL) o None.
    """
    if not id_exp:
        logger.warning("fix_nt_expediente llamado sin id_exp valido")
        return None

    logger.info("Intentando corregir expediente NT/ para idExp=%s", id_exp)

    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        # PASO 1: obtener texto de publicacion y extraer expediente valido
        cursor.execute(
            """
            SELECT TOP 20 p.publicación
            FROM pubExp p
            JOIN recursos.RecursosExp r ON r.IdPublic = p.idpublic
            WHERE r.IdExp = ?
              AND (
                    PATINDEX(?, p.publicación) > 0
                 OR PATINDEX(?, p.publicación) > 0
              )
            ORDER BY p.idpublic DESC
            """,
            (id_exp, PATRON_BUSQUEDA_MUL_SQL, PATRON_BUSQUEDA_BASE_SQL),
        )

        nuevo_exp: Optional[str] = None
        for row in cursor.fetchall():
            raw_text = row[0] if row else None
            candidato = _extract_valid_expediente_from_text(raw_text)
            if candidato:
                nuevo_exp = candidato
                break

        if not nuevo_exp:
            logger.warning("No se encontro expediente valido en pubExp.publicacion para idExp=%s", id_exp)
            conn.close()
            return None

        logger.info("Patron correcto encontrado: '%s'", nuevo_exp)

        # PASO 2: verificar que hay registros NT para actualizar
        cursor.execute(
            """
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
            """,
            (
                id_exp,
                PATRON_NT9_SQL,
                PATRON_NT10_SQL,
                id_exp,
                PATRON_NT9_SQL,
                PATRON_NT10_SQL,
                id_exp,
                PATRON_NT9_SQL,
                PATRON_NT10_SQL,
                id_exp,
                PATRON_NT9_SQL,
                PATRON_NT10_SQL,
            ),
        )

        count_row = cursor.fetchone()
        if not count_row or count_row[0] == 0:
            logger.info("No hay registros con formato NT/ para actualizar en idExp=%s", id_exp)
            conn.close()
            return None

        logger.info("Encontrados %s registros con formato NT/ para actualizar", count_row[0])

        try:
            # UPDATE expedientes
            cursor.execute(
                """
                UPDATE expedientes
                SET numexpediente = ?
                WHERE idexpediente = ?
                  AND (numexpediente LIKE ? OR numexpediente LIKE ?)
                """,
                (nuevo_exp, id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL),
            )
            rows_exp = cursor.rowcount

            # UPDATE recursos.RecursosExp
            cursor.execute(
                """
                UPDATE recursos.RecursosExp
                SET Expedient = ?
                WHERE IdExp = ?
                  AND (Expedient LIKE ? OR Expedient LIKE ?)
                """,
                (nuevo_exp, id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL),
            )
            rows_rec = cursor.rowcount

            # UPDATE ListasPresentacion
            cursor.execute(
                """
                UPDATE ListasPresentacion
                SET numexpediente = ?
                WHERE Idexpediente = ?
                  AND (numexpediente LIKE ? OR numexpediente LIKE ?)
                """,
                (nuevo_exp, id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL),
            )
            rows_lp = cursor.rowcount

            # UPDATE pubExp
            cursor.execute(
                """
                UPDATE p
                SET p.Exp = ?
                FROM pubExp p
                JOIN recursos.RecursosExp r ON r.IdPublic = p.idpublic
                WHERE r.IdExp = ?
                  AND (p.Exp LIKE ? OR p.Exp LIKE ?)
                """,
                (nuevo_exp, id_exp, PATRON_NT9_SQL, PATRON_NT10_SQL),
            )
            rows_pub = cursor.rowcount

            conn.commit()

            logger.info(
                "Expediente corregido: '%s' (expedientes=%s, RecursosExp=%s, ListasPresentacion=%s, pubExp=%s)",
                nuevo_exp,
                rows_exp,
                rows_rec,
                rows_lp,
                rows_pub,
            )
            conn.close()
            return nuevo_exp

        except Exception as e:
            conn.rollback()
            logger.error("Error durante UPDATE, rollback: %s", e)
            conn.close()
            return None

    except Exception as e:
        logger.error("Error de conexion/consulta en fix_nt_expediente: %s", e)
        return None
