import argparse
import json
import os
import re
import sqlite3
import sys
import traceback
import unicodedata
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

try:
    import pyodbc  # type: ignore
except Exception:  # pragma: no cover
    pyodbc = None

# Query para obtener un único registro por idExp sin filtros de lógica de negocio
SINGLE_ID_QUERY = """
SELECT 
    rs.idRecurso,
    rs.Expedient,
    rs.FaseProcedimiento,
    rs.Matricula,
    rs.automatic_id,
    c.email,
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id
WHERE rs.idExp = ?
"""


def normalize_text(text: Any) -> str:
    if not text:
        return ""
    text = str(text).strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def load_config_motivos(path: Path = Path("config_motivos.json")) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_motivos_por_fase(
    fase_raw: Any,
    expediente: str,
    *,
    config_map: dict[str, Any],
) -> str:
    """Lee config_motivos.json y compone el texto final para el campo motivos."""
    expediente_txt = str(expediente or "").strip()

    def _default() -> str:
        return (
            "ASUNTO: Recurso de reposicion\n\n"
            f"EXPONE: Tramite para el expediente {expediente_txt}.\n\n"
            "SOLICITA: Se admita el recurso."
        )

    try:
        fase_norm = normalize_text(fase_raw)

        selected: dict[str, Any] | None = None
        for key, value in (config_map or {}).items():
            # Coincidencia parcial (p. ej. "propuesta de resolucion" matchea variantes)
            if key and key in fase_norm:
                selected = value
                break

        if not selected:
            return _default()

        asunto = str(selected.get("asunto") or "").strip()
        expone = str(selected.get("expone") or "").strip()
        solicita = (
            str(selected.get("solicita") or "").replace("{expediente}", expediente_txt).strip()
        )

        if not (asunto and expone and solicita):
            return _default()

        return f"ASUNTO: {asunto}\n\nEXPONE: {expone}\n\nSOLICITA: {solicita}"
    except Exception:
        return _default()


def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_plate(value: Any) -> str:
    cleaned = re.sub(r"\s+", "", _clean_str(value)).upper()
    # Si la matrícula está vacía o es NULL, usar "." porque no es necesaria
    return cleaned if cleaned else "."


def _map_payload(
    row: dict[str, Any],
    motivos: str,
    adjuntos_list: list | None = None,
) -> dict[str, Any]:
    expediente = _clean_str(row.get("Expedient"))

    return {
        "idRecurso": row.get("idRecurso"),
        "user_email": _clean_str(row.get("email")),
        "denuncia_num": expediente,
        "plate_number": _normalize_plate(row.get("Matricula")),
        "expediente_num": expediente,
        "motivos": motivos,
        "adjuntos": adjuntos_list or [],
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


def _insert_task(db_path: str, site_id: str, payload: dict[str, Any]) -> int:
    conn = sqlite3.connect(Path(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tramite_queue (site_id, payload) VALUES (?, ?)",
            (site_id, json.dumps(payload, ensure_ascii=False, default=str)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _build_sqlserver_connection_string(
    *,
    direct: str | None,
) -> str:
    """
    Devuelve un connection string para pyodbc.

    Prioridad:
    1) --connection-string
    2) SQLSERVER_CONNECTION_STRING
    3) Variables separadas (evita problemas con ';' en .env):
       SQLSERVER_DRIVER, SQLSERVER_SERVER, SQLSERVER_DATABASE, SQLSERVER_USERNAME, SQLSERVER_PASSWORD
       (opcional) SQLSERVER_TRUSTED_CONNECTION=1
    """
    if direct:
        return str(direct).strip()

    cs_env = (os.getenv("SQLSERVER_CONNECTION_STRING") or "").strip()
    if cs_env:
        return cs_env

    driver = (os.getenv("SQLSERVER_DRIVER") or "SQL Server").strip()
    server = (os.getenv("SQLSERVER_SERVER") or "").strip()
    database = (os.getenv("SQLSERVER_DATABASE") or "").strip()
    username = (os.getenv("SQLSERVER_USERNAME") or "").strip()
    password = (os.getenv("SQLSERVER_PASSWORD") or "").strip()
    trusted = (os.getenv("SQLSERVER_TRUSTED_CONNECTION") or "").strip().lower() in {"1", "true", "yes", "y"}

    if not (server and database):
        raise ValueError(
            "Faltan datos de conexión. Define SQLSERVER_SERVER y SQLSERVER_DATABASE (o SQLSERVER_CONNECTION_STRING)."
        )

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
    ]

    if trusted:
        parts.append("Trusted_Connection=yes")
    else:
        if not (username and password):
            raise ValueError(
                "Faltan credenciales. Define SQLSERVER_USERNAME y SQLSERVER_PASSWORD (o SQLSERVER_TRUSTED_CONNECTION=1)."
            )
        parts.append(f"UID={username}")
        parts.append(f"PWD={password}")

    return ";".join(parts)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sincroniza un único registro por idRecurso sin aplicar filtros de lógica de negocio."
    )
    parser.add_argument(
        "--id",
        type=int,
        required=True,
        help="El idExp que queremos buscar (obligatorio).",
    )
    parser.add_argument(
        "--site-id",
        type=str,
        required=True,
        help="Identificador del sitio (ej. 'madrid', 'xaloc_girona', 'base_online').",
    )
    parser.add_argument(
        "--connection-string",
        default=None,
        help=(
            "Connection string SQL Server. Si no se pasa: usa SQLSERVER_CONNECTION_STRING o bien "
            "SQLSERVER_{DRIVER,SERVER,DATABASE,USERNAME,PASSWORD} (opcional SQLSERVER_TRUSTED_CONNECTION=1)."
        ),
    )
    parser.add_argument("--sqlite-db", default="db/xaloc_database.db", help="Ruta SQLite.")
    parser.add_argument("--verbose", action="store_true", help="Log detallado de errores.")

    args = parser.parse_args(argv)

    if pyodbc is None:
        print("ERROR: pyodbc no instalado. Ejecuta 'pip install pyodbc'.", file=sys.stderr)
        return 2

    load_dotenv()
    try:
        connection_string = _build_sqlserver_connection_string(direct=args.connection_string)
    except Exception as e:
        print(
            f"ERROR: No se pudo construir la conexión a SQL Server: {e}",
            file=sys.stderr,
        )
        return 2

    # Inicializar SQLite
    _init_sqlite(args.sqlite_db)

    # Cargar config de motivos
    try:
        motivos_config = load_config_motivos()
    except Exception as e:
        print(f"ERROR: no se pudo cargar config_motivos.json: {e}", file=sys.stderr)
        return 2

    # Conectar a SQL Server y buscar el idRecurso
    conn = pyodbc.connect(connection_string)
    try:
        cursor = conn.cursor()
        cursor.execute(SINGLE_ID_QUERY, (args.id,))
        columns = [c[0] for c in cursor.description]

        rows = cursor.fetchall()
        if not rows:
            print(f"ERROR: No se encontró ningún registro con idExp = {args.id}", file=sys.stderr)
            return 1

        # Agrupar adjuntos por idExp (aunque solo hay uno, puede tener múltiples adjuntos)
        task_data = {
            "row": None,
            "adjuntos": [],
        }

        for row in rows:
            row_dict = dict(zip(columns, row))
            
            # Guardar la primera fila como base
            if task_data["row"] is None:
                task_data["row"] = row_dict

            # Agregar adjuntos si existen (solo datos de la consulta)
            adj_id = row_dict.get("adjunto_id")
            adj_filename = row_dict.get("adjunto_filename")
            if adj_id and adj_filename:
                task_data["adjuntos"].append(
                    {
                        "id": adj_id,
                        "filename": _clean_str(adj_filename),
                        "url": "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}".format(
                            id=adj_id
                        ),
                    }
                )

        # Mapear el payload
        try:
            expediente = _clean_str(task_data["row"].get("Expedient"))
            fase_raw = task_data["row"].get("FaseProcedimiento")
            
            # Obtener motivos sin fallback - solo lo que viene de config_motivos.json
            motivos_text = get_motivos_por_fase(
                fase_raw,
                expediente,
                config_map=motivos_config,
            )

            payload = _map_payload(
                task_data["row"],
                motivos_text,
                adjuntos_list=task_data["adjuntos"],
            )

            # Insertar en SQLite
            task_id = _insert_task(args.sqlite_db, args.site_id, payload)

            print("\n=== Sincronización por ID ===")
            print(f"✓ idRecurso encontrado: {args.id}")
            print(f"✓ Site ID: {args.site_id}")
            print(f"✓ Expediente: {expediente}")
            print(f"✓ Email: {payload['user_email']}")
            print(f"✓ Matrícula: {payload['plate_number']}")
            print(f"✓ Adjuntos encontrados: {len(task_data['adjuntos'])}")
            print(f"✓ Tarea insertada en SQLite con ID: {task_id}")
            
            if args.verbose:
                print(f"\nPayload completo:")
                print(json.dumps(payload, indent=2, ensure_ascii=False))

            return 0

        except Exception as e:
            print(f"ERROR procesando idExp {args.id}: {e}", file=sys.stderr)
            if args.verbose:
                traceback.print_exc()
            return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
