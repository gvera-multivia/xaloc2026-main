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
from typing import Any, Optional, Literal

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
	    rs.SujetoRecurso AS sujeto_recurso,
	    -- NUEVOS CAMPOS PARA MANDATARIO --
	    rs.cif,              -- Para determinar JURIDICA vs FISICA
	    rs.Empresa,          -- Razón social (persona jurídica) - puede ser NULL
	    c.Nombrefiscal,      -- Fallback para razón social si rs.Empresa es NULL
	    c.nif AS cliente_nif,       -- NIF/NIE de persona física
	    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    -- FIN NUEVOS CAMPOS --
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente  -- Join para obtener la matrícula
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
    output: str = "text",
) -> str:
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

    # Construimos el texto con saltos de línea reales (\n)
    # Usamos \n para un salto simple o \n\n para separar bloques
    text = f"ASUNTO: {asunto}\n\nEXPONE: {expone}\n\nSOLICITA: {solicita}"

    # Si por alguna razón necesitas procesar saltos para un sistema que use HTML 
    # pero NO quieres etiquetas <p>, podrías usar solo <br />, 
    # pero para texto plano lo normal es devolver 'text'.
    if output == "html":
        # Esta es una versión alternativa si el destino final es una web 
        # pero no quieres párrafos, solo saltos de línea.
        return text.replace("\n", "<br />")

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
        # Email validation removed - using fixed company email instead
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


def _determinar_tipo_persona(cif_value: str | None, empresa_value: str | None = None) -> Literal["FISICA", "JURIDICA"]:
    """Determina el tipo de persona basándose en el CIF y/o nombre de empresa.
    
    Si CUALQUIERA de los dos tiene valor, se considera JURIDICA.
    Esto evita problemas cuando el CIF está vacío pero sí hay nombre de empresa.
    """
    cif_clean = (cif_value or "").strip()
    empresa_clean = (empresa_value or "").strip()
    
    if cif_clean or empresa_clean:
        return "JURIDICA"
    return "FISICA"


def _extraer_documento_control(documento: str) -> tuple[str, str]:
    """
    Separa un documento (NIF/NIE/CIF) en número + dígito de control.
    
    Reglas:
    - NIF: 12345678Z → ("12345678", "Z")
    - NIE: Y7654321G → ("Y7654321", "G")
    - CIF: A12345674 → ("A1234567", "4")
    """
    doc_clean = documento.strip().upper()
    if len(doc_clean) < 2:
        raise ValueError(f"Documento demasiado corto: {documento}")
    
    # Los primeros 8 caracteres son el documento, el último es el control
    doc_numero = doc_clean[:-1]
    doc_control = doc_clean[-1]
    
    return doc_numero, doc_control


def _detectar_tipo_documento(nif_nie: str) -> Literal["NIF", "PS"]:
    """
    Detecta si un documento es NIF o NIE (Pasaporte no aplica aquí).
    NIE empieza con X, Y o Z.
    """
    first_char = (nif_nie or "").strip().upper()[:1]
    if first_char in ("X", "Y", "Z"):
        return "PS"  # NIE se marca como PS (Pasaporte) según el formulario
    return "NIF"


def _build_mandatario_data(row: dict) -> dict:
    """Construye el diccionario de mandatario a partir de una fila de DB."""
    import logging
    
    cif_raw = row.get("cif")
    # Usar rs.Empresa si existe, sino usar c.Nombrefiscal como fallback
    empresa_raw = row.get("Empresa") or row.get("Nombrefiscal")
    
    # Determinar tipo de persona usando AMBOS campos
    tipo_persona = _determinar_tipo_persona(cif_raw, empresa_raw)
    
    mandatario: dict = {"tipo_persona": tipo_persona}
    
    if tipo_persona == "JURIDICA":
        # Persona jurídica: usar CIF (si existe) y Razón Social
        razon_social = (empresa_raw or "").strip().upper()
        if not razon_social:
            raise ValueError("Persona jurídica sin razón social válida")
        
        cif_clean = (cif_raw or "").strip().upper()
        
        # Si hay CIF, lo separamos en documento + control
        if cif_clean:
            doc_numero, doc_control = _extraer_documento_control(cif_clean)
            mandatario.update({
                "cif_documento": doc_numero,
                "cif_control": doc_control,
            })
        else:
            # Si no hay CIF, dejamos los campos vacíos (el formulario puede permitirlo)
            logging.warning(f"Empresa '{razon_social}' sin CIF en la base de datos")
            mandatario.update({
                "cif_documento": "",
                "cif_control": "",
            })
        
        mandatario["razon_social"] = razon_social
        
    else:
        # Persona física: usar NIF/NIE de la tabla clientes
        nif_raw = row.get("cliente_nif")
        nif_clean = (nif_raw or "").strip().upper()
        if not nif_clean:
            raise ValueError("Persona física sin NIF/NIE válido")
        
        doc_numero, doc_control = _extraer_documento_control(nif_clean)
        tipo_doc = _detectar_tipo_documento(nif_clean)
        
        mandatario.update({
            "tipo_doc": tipo_doc,
            "doc_numero": doc_numero,
            "doc_control": doc_control,
            "nombre": (row.get("cliente_nombre") or "").strip().upper(),
            "apellido1": (row.get("cliente_apellido1") or "").strip().upper(),
            "apellido2": (row.get("cliente_apellido2") or "").strip().upper(),
        })
    
    return mandatario


def _map_xaloc_payload(
    row: dict[str, Any],
    motivos: str,
    adjuntos_list: list | None = None,
) -> dict[str, Any]:
    expediente = _clean_str(row.get("Expedient"))
    
    # NUEVO: Construir datos del mandatario
    mandatario = _build_mandatario_data(row)

    return {
        "idRecurso": row.get("idRecurso"),
        "user_email": "INFO@XVIA-SERVICIOSJURIDICOS.COM",  # Email fijo de la empresa
        "denuncia_num": expediente,
        "plate_number": _normalize_plate(row.get("matricula")),
        "expediente_num": expediente,
        "sujeto_recurso": _clean_str(row.get("sujeto_recurso")),
        "motivos": motivos,
        "adjuntos": adjuntos_list or [],
        "mandatario": mandatario,  # NUEVO
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
                    output="text",
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
