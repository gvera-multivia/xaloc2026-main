import argparse
import json
import os
from pydoc import html
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

# Query simplificada para obtener solo lo necesario para el nuevo payload
BASE_SELECT_QUERY = """
SELECT 
    rs.idRecurso,
    rs.Expedient,
    rs.FaseProcedimiento,
    e.matricula,       -- Ahora viene de la tabla expedientes
    rs.automatic_id,
    c.email,
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente  -- Join para obtener la matrícula
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


def _normalize_literal_newlines(s: str) -> str:
    # Convierte "\\n" literal a salto real, por si llega escapado desde JSON/otros
    return s.replace("\\n", "\n")


def _text_to_tinymce_html(text: str) -> str:
    """
    Convierte texto con saltos a HTML robusto para TinyMCE:
    - doble salto => nuevo párrafo
    - salto simple => <br>
    - escapado HTML para evitar que se inyecte markup accidental
    """
    text = _normalize_literal_newlines(text).replace("\r\n", "\n").replace("\r", "\n")

    blocks = re.split(r"\n\s*\n", text.strip())
    out: list[str] = []
    for b in blocks:
        b = html.escape(b)              # evita que < > & rompan el editor
        b = b.replace("\n", "<br />")   # saltos dentro del bloque
        out.append(f"<p>{b}</p>")
    return "".join(out)


def get_motivos_por_fase(
    fase_raw: Any,
    expediente: str,
    *,
    config_map: dict[str, Any],
    output: str = "text",  # "text" o "html"
) -> str:
    """
    Lee config_motivos.json y compone el texto final para el campo motivos.

    output="text": devuelve texto con \\n\\n
    output="html": devuelve HTML <p>..</p> con <br /> para TinyMCE

    Raises:
        ValueError: Si no se encuentra la fase en config_motivos.json o los datos están incompletos.
    """
    expediente_txt = _clean_str(expediente)
    fase_norm = normalize_text(fase_raw)

    selected: dict[str, Any] | None = None
    for key, value in (config_map or {}).items():
        if key and key in fase_norm:
            selected = value
            break

    if not selected:
        raise ValueError(f"No se encontró configuración para la fase: {fase_raw}")

    asunto = _clean_str(selected.get("asunto"))
    expone = _clean_str(selected.get("expone"))
    solicita = _clean_str(selected.get("solicita")).replace("{expediente}", expediente_txt)

    if not (asunto and expone and solicita):
        raise ValueError(f"Datos incompletos en config_motivos.json para la fase: {fase_raw}")

    text = f"ASUNTO: {asunto}\n\nEXPONE: {expone}\n\nSOLICITA: {solicita}"

    if output == "html":
        return _text_to_tinymce_html(text)

    return text

def build_query(*, fase: str | None) -> tuple[str, list[Any]]:
    """Construye la query filtrando por estado pendiente y tipo de expediente."""
    query = BASE_SELECT_QUERY.strip()
    params: list[Any] = []

    where_clauses = [
        "rs.Organisme LIKE '%xaloc%'",
        "rs.Estado = 0",
        "rs.TExp IN (2, 3)",
        "rs.idRecurso IS NOT NULL",
        "rs.Expedient IS NOT NULL AND LTRIM(RTRIM(rs.Expedient)) <> ''",
        "rs.Matricula IS NOT NULL AND LTRIM(RTRIM(rs.Matricula)) <> ''",
        "c.email IS NOT NULL AND LTRIM(RTRIM(c.email)) <> ''",
    ]

    fase_norm = (fase or "").strip()
    if fase_norm:
        where_clauses.append("LTRIM(RTRIM(rs.FaseProcedimiento)) = ?")
        params.append(fase_norm)

    full_query = f"{query}\nWHERE " + " AND ".join(where_clauses)
    return full_query, params


def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


FALLBACKS: dict[str, str] = {
    # Solo se permiten fallbacks declarados explícitamente aquí.
    "Matricula": ".",
}


def _normalize_plate(value: Any) -> str:
    cleaned = re.sub(r"\s+", "", _clean_str(value)).upper()
    if not cleaned:
        return FALLBACKS["Matricula"]
    return cleaned


def _map_xaloc_payload(
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
        schema_path = Path("db/schema.sql")
        if schema_path.exists():
            conn.executescript(schema_path.read_text(encoding="utf-8"))
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tramite_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id TEXT NOT NULL,
                    protocol TEXT,
                    payload JSON NOT NULL,
                    status TEXT DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    screenshot_path TEXT,
                    error_log TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP,
                    result JSON,
                    attachments_count INTEGER DEFAULT 0,
                    attachments_metadata JSON
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
            "INSERT INTO tramite_queue (site_id, protocol, payload) VALUES (?, ?, ?)",
            ("xaloc_girona", None, json.dumps(payload, ensure_ascii=False, default=str)),
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
            "Faltan datos de conexiÃ³n. Define SQLSERVER_SERVER y SQLSERVER_DATABASE (o SQLSERVER_CONNECTION_STRING)."
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
        description="Sincronizador exclusivo para XALOC GIRONA con agrupacion de adjuntos."
    )
    parser.add_argument(
        "--connection-string",
        default=None,
        help=(
            "Connection string SQL Server. Si no se pasa: usa SQLSERVER_CONNECTION_STRING o bien "
            "SQLSERVER_{DRIVER,SERVER,DATABASE,USERNAME,PASSWORD} (opcional SQLSERVER_TRUSTED_CONNECTION=1)."
        ),
    )
    parser.add_argument("--fase", default="", help="Filtro opcional rs.FaseProcedimiento.")
    parser.add_argument("--sqlite-db", default="db/xaloc_database.db", help="Ruta SQLite.")
    parser.add_argument("--dry-run", action="store_true", help="No inserta tareas en la base de datos.")
    parser.add_argument("--limit", type=int, default=0, help="Limite de registros a procesar.")
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
            f"ERROR: No se pudo construir la conexiÃ³n a SQL Server: {e}",
            file=sys.stderr,
        )
        return 2

    # 1. Preparar Query, cargar config de motivos e iniciar SQLite
    query, query_params = build_query(fase=args.fase)
    _init_sqlite(args.sqlite_db)

    try:
        motivos_config = load_config_motivos()
    except Exception as e:
        print(f"ERROR: no se pudo cargar config_motivos.json: {e}", file=sys.stderr)
        return 2

    scanned = 0
    matched = 0
    row_errors = 0
    inserted_ids: list[int] = []

    tasks_data: dict[Any, dict[str, Any]] = {}

    conn = pyodbc.connect(connection_string)
    try:
        cursor = conn.cursor()
        cursor.execute(query, tuple(query_params))
        columns = [c[0] for c in cursor.description]

        # 2. Fase de Lectura y Agrupacion
        for row in cursor:
            scanned += 1
            row_dict = dict(zip(columns, row))
            rid = row_dict.get("idRecurso")

            if not rid:
                continue

            if rid not in tasks_data:
                tasks_data[rid] = {
                    "row": row_dict,
                    "adjuntos": [],
                    "errors": [],
                }

            adj_id = row_dict.get("adjunto_id")
            if adj_id:
                filename_clean = _clean_str(row_dict.get("adjunto_filename"))
                if not filename_clean:
                    tasks_data[rid]["errors"].append(
                        f"Adjunto {adj_id} sin filename en SQL Server (no se permite fallback)."
                    )
                    continue
                tasks_data[rid]["adjuntos"].append(
                    {
                        "id": adj_id,
                        "filename": filename_clean,
                        "url": "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}".format(
                            id=adj_id
                        ),
                    }
                )

        # 3. Fase de Mapeo e Insercion en SQLite
        for rid, info in tasks_data.items():
            try:
                if args.limit and matched >= args.limit:
                    break

                if info.get("errors"):
                    raise ValueError("; ".join(info["errors"]))

                expediente = _clean_str(info["row"].get("Expedient"))
                fase_raw = info["row"].get("FaseProcedimiento")
                motivos_text = get_motivos_por_fase(
                    fase_raw,
                    expediente,
                    config_map=motivos_config,
                )

                payload = _map_xaloc_payload(
                    info["row"],
                    motivos_text,
                    adjuntos_list=info["adjuntos"],
                )

                matched += 1

                if not args.dry_run:
                    task_id = _insert_task(args.sqlite_db, payload)
                    inserted_ids.append(task_id)
                else:
                    if args.verbose:
                        print(
                            f"[DRY-RUN] Tarea detectada para ID {rid} con {len(info['adjuntos'])} adjuntos."
                        )

            except Exception as e:
                row_errors += 1
                if args.verbose:
                    print(f"Error procesando idRecurso {rid}: {e}", file=sys.stderr)
                    traceback.print_exc()

    finally:
        conn.close()

    print("\n=== Sincronizacion XALOC GIRONA (Con Adjuntos) ===")
    print(f"- Filas SQL Server leidas: {scanned}")
    print(f"- Recursos unicos encontrados: {len(tasks_data)}")
    print(f"- Tareas mapeadas/encoladas: {matched}")
    if not args.dry_run:
        print(f"- IDs insertados en SQLite: {len(inserted_ids)}")
    if row_errors:
        print(f"- Errores detectados: {row_errors}")

    return 0 if row_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
