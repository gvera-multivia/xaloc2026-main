import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import pyodbc  # type: ignore
except Exception:  # pragma: no cover
    pyodbc = None

# Query simplificada para obtener solo lo necesario para el nuevo payload
BASE_SELECT_QUERY = """
SELECT DISTINCT
    rs.idRecurso,
    rs.Expedient,
    rs.Matricula,
    c.email
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
WHERE 
    -- Validar idRecurso (suele ser numérico, basta con NOT NULL)
    rs.idRecurso IS NOT NULL 
    
    -- Validar Expediente (que no sea null ni espacios)
    AND rs.Expedient IS NOT NULL 
    AND LTRIM(RTRIM(rs.Expedient)) <> ''
    
    -- Validar Matricula (que no sea null ni espacios)
    AND rs.Matricula IS NOT NULL 
    AND LTRIM(RTRIM(rs.Matricula)) <> ''
    
    -- Validar Email (fundamental para el envío posterior)
    AND c.email IS NOT NULL 
    AND LTRIM(RTRIM(c.email)) <> ''
"""

def build_query(*, fase: str | None) -> tuple[str, list[Any]]:
    """Construye la query filtrando por estado pendiente y tipo de expediente."""
    query = BASE_SELECT_QUERY.strip()
    params: list[Any] = []

    where_clauses = [
        "rs.Estado = 0",           # Solo pendientes
        "rs.TExp IN (2, 3)"        # Solo documentos generados/servidor
        
    ]

    fase_norm = (fase or "").strip()
    if fase_norm:
        where_clauses.append("LTRIM(RTRIM(rs.FaseProcedimiento)) = ?")
        params.append(fase_norm)

    query += "\nWHERE " + " AND ".join(where_clauses)
    return query, params

def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""

def _normalize_plate(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_str(value)).upper()

def _is_xaloc_organisme(organisme: Any) -> bool:
    """Verifica si el organismo pertenece a Xaloc / Girona."""
    org = _clean_str(organisme).upper()
    return "XALOC" in org or "GIRONA" in org

def _map_xaloc_payload(row: dict[str, Any], motivos: str, archivos: list[str]) -> dict[str, Any]:
    """
    Genera el payload estricto para Xaloc.
    Estructura requerida: user_email, denuncia_num, plate_number, expediente_num, motivos, archivos.
    """
    expediente = _clean_str(row.get("Expedient"))
    
    return {
        "user_email": _clean_str(row.get("email")),
        "denuncia_num": expediente,
        "plate_number": _normalize_plate(row.get("Matricula")),
        "expediente_num": expediente,
        "motivos": motivos,
        "archivos": archivos
    }

def _init_sqlite(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tramite_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                payload JSON NOT NULL,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                error_log TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

def _insert_task(db_path: str, payload: dict[str, Any]) -> int:
    conn = sqlite3.connect(Path(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tramite_queue (site_id, payload) VALUES (?, ?)",
            ("xaloc_girona", json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sincronizador exclusivo para XALOC GIRONA con payload simplificado."
    )
    parser.add_argument("--connection-string", required=True, help="Connection string SQL Server.")
    parser.add_argument("--fase", default="", help="Filtro opcional rs.FaseProcedimiento.")
    parser.add_argument("--sqlite-db", default="db/xaloc_database.db", help="Ruta SQLite.")
    parser.add_argument("--motivos", default="Presentación de alegaciones estándar.", help="Texto para el campo 'motivos'.")
    parser.add_argument("--archivos", help="Lista de archivos separados por coma.")
    parser.add_argument("--dry-run", action="store_true", help="No inserta tareas en la base de datos.")
    parser.add_argument("--limit", type=int, default=0, help="Límite de registros a procesar.")
    parser.add_argument("--verbose", action="store_true", help="Log detallado de errores.")

    args = parser.parse_args(argv)

    if pyodbc is None:
        print("ERROR: pyodbc no instalado. Ejecuta 'pip install pyodbc'.", file=sys.stderr)
        return 2

    # Preparación de datos constantes para el payload
    lista_archivos = [a.strip() for a in args.archivos.split(",") if a.strip()]
    
    query, query_params = build_query(fase=args.fase)
    _init_sqlite(args.sqlite_db)

    scanned = 0
    matched = 0
    row_errors = 0
    inserted_ids = []

    conn = pyodbc.connect(args.connection_string)
    try:
        cursor = conn.cursor()
        cursor.execute(query, tuple(query_params))
        columns = [c[0] for c in cursor.description]

        for row in cursor:
            scanned += 1
            try:
                row_dict = dict(zip(columns, row))
                
                # Opcional: Si la query base no filtrara el organismo, lo haríamos aquí.
                # Pero en esta versión simplificada confiamos en la lógica de selección.

                if args.limit and matched >= args.limit:
                    break

                payload = _map_xaloc_payload(row_dict, args.motivos, lista_archivos)
                matched += 1

                if not args.dry_run:
                    task_id = _insert_task(args.sqlite_db, payload)
                    inserted_ids.append(task_id)

            except Exception as e:
                row_errors += 1
                if args.verbose:
                    print(f"Error procesando fila: {e}", file=sys.stderr)

    finally:
        conn.close()

    print("\n=== Sincronización XALOC GIRONA (Payload Estricto) ===")
    print(f"- Filas SQL Server leídas: {scanned}")
    print(f"- Registros mapeados: {matched}")
    print(f"- Tareas encoladas: {len(inserted_ids)}")
    if row_errors:
        print(f"- Errores detectados: {row_errors}")
    
    return 0 if row_errors == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())