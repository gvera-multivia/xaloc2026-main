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

# Query simplificada para obtener solo lo necesario para el nuevo payload
BASE_SELECT_QUERY = """
SELECT 
    rs.idRecurso,
    rs.Expedient,
    rs.FaseProcedimiento,
    rs.Matricula,
    c.email,
    rs.automatic_id,
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
LEFT JOIN attachments_resource_documents att ON rs.automatic_id = att.automatic_id
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


def _normalize_plate(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_str(value)).upper()


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
            ("xaloc_girona", json.dumps(payload, ensure_ascii=False, default=str)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sincronizador exclusivo para XALOC GIRONA con agrupacion de adjuntos."
    )
    parser.add_argument(
        "--connection-string",
        default=None,
        help="Connection string SQL Server (si no se pasa, usa env: SQLSERVER_CONNECTION_STRING).",
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
    connection_string = args.connection_string or os.getenv("SQLSERVER_CONNECTION_STRING")
    if not connection_string:
        print(
            "ERROR: Falta connection string. Pasa --connection-string o define SQLSERVER_CONNECTION_STRING en el entorno/.env.",
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
                }

            adj_id = row_dict.get("adjunto_id")
            if adj_id:
                tasks_data[rid]["adjuntos"].append(
                    {
                        "id": adj_id,
                        "filename": _clean_str(
                            row_dict.get("adjunto_filename") or f"adjunto_{adj_id}.pdf"
                        ),
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

                expediente = _clean_str(info["row"].get("Expedient"))
                fase_raw = info["row"].get("FaseProcedimiento")
                try:
                    motivos_text = get_motivos_por_fase(
                        fase_raw,
                        expediente,
                        config_map=motivos_config,
                    )
                except Exception:
                    motivos_text = (
                        "ASUNTO: Recurso de reposicion\n\n"
                        f"EXPONE: Tramite para el expediente {expediente}.\n\n"
                        "SOLICITA: Se admita el recurso."
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
