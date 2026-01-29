import argparse
import html
import json
import os
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

# Query para obtener un único registro por idRecurso sin filtros de lógica de negocio
SINGLE_ID_QUERY = """
SELECT 
    rs.idRecurso,
    rs.Expedient,
    rs.FaseProcedimiento,
    e.matricula,       -- Ahora viene de la tabla expedientes
	    rs.automatic_id,
	    rs.SujetoRecurso AS sujeto_recurso,
	    -- NUEVOS CAMPOS PARA MANDATARIO --
    rs.cif,              -- Para determinar JURIDICA vs FISICA - puede ser NULL
    c.nifempresa,        -- Fallback para CIF si rs.cif es NULL
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
WHERE rs.idRecurso = ?
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


def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_literal_newlines(s: str) -> str:
    """
    Convierte '\\n' literal (dos caracteres: barra + n) a salto real '\n'.
    Útil si el JSON tiene "\\n\\n" o si algún paso lo escapa.
    """
    return s.replace("\\n", "\n")


def _text_to_tinymce_html(text: str) -> str:
    """
    Convierte texto con saltos a HTML robusto para TinyMCE:
    - doble salto => nuevo párrafo
    - salto simple => <br />
    - escape HTML para evitar inyección / markup accidental
    """
    text = _normalize_literal_newlines(text).replace("\r\n", "\n").replace("\r", "\n")

    blocks = re.split(r"\n\s*\n", text.strip())
    out: list[str] = []
    for b in blocks:
        b = html.escape(b)
        b = b.replace("\n", "<br />")
        out.append(f"<p>{b}</p>")
    return "".join(out)

def get_motivos_por_fase(
    fase_raw: Any,
    expediente: str,
    sujeto_recurso: str = "", 
    *,
    config_map: dict[str, Any],
    output: str = "text",
) -> str:
    expediente_txt = _clean_str(expediente)
    # Forzamos MAYÚSCULAS para que quede bien en el documento legal
    sujeto_txt = _clean_str(sujeto_recurso).upper() 
    fase_norm = normalize_text(fase_raw)

    selected: dict[str, Any] | None = None
    for key, value in (config_map or {}).items():
        if key and key in fase_norm:
            selected = value
            break

    if not selected:
        raise ValueError(f"No se encontró configuración para la fase: {fase_raw}")

    # Extraemos y limpiamos los campos
    asunto = _clean_str(selected.get("asunto"))
    expone = _clean_str(selected.get("expone"))
    solicita = _clean_str(selected.get("solicita"))

    # Función interna para limpiar etiquetas en bloque
    def _rellenar(t: str) -> str:
        return t.replace("{expediente}", expediente_txt).replace("{sujeto_recurso}", sujeto_txt)

    asunto = _rellenar(asunto)
    expone = _rellenar(expone)
    solicita = _rellenar(solicita)

    if not (asunto and expone and solicita):
        raise ValueError(f"Datos incompletos en el JSON para la fase: {fase_raw}")

    text = f"ASUNTO: {asunto}\n\nEXPONE: {expone}\n\nSOLICITA: {solicita}"

    if output == "html":
        return text.replace("\n", "<br />")

    return text

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


def _detectar_tipo_documento(doc: str) -> Literal["NIF", "PS"]:
    """
    Detecta el tipo de documento.
    - PS (Pasaporte): Si cumple el patrón de 3 letras iniciales seguidas de números.
    - NIF: Para DNI estándar y NIE (X, Y, Z), tratándolos como identificadores fiscales.
    """
    if not doc:
        return "NIF"

    # Limpieza básica
    doc = doc.strip().upper()

    # 1. Patrón Pasaporte (PS): 3 letras + números
    # Ejemplo: 'ABC123456'
    if re.match(r'^[A-Z]{3}[0-9]+', doc):
        return "PS"

    # 2. Todo lo demás (incluyendo NIEs con X, Y, Z) se clasifica como NIF
    # ya que no cumplen el patrón específico de pasaporte de 3 letras.
    return "NIF"


def _build_mandatario_data(row: dict) -> dict:
    """Construye el diccionario de mandatario a partir de una fila de DB."""
    import logging
    
    # Usar rs.cif si existe, sino usar c.nifempresa como fallback
    cif_raw = row.get("cif") or row.get("nifempresa")
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


def _map_payload(
    row: dict[str, Any],
    motivos: str,
    adjuntos_list: list | None = None,
) -> dict[str, Any]:
    expediente = _clean_str(row.get("Expedient"))
    
    # NUEVO: Construir datos del mandatario
    mandatario = _build_mandatario_data(row)

    return {
        "idRecurso": row.get("idRecurso"),
        "user_email": "INFO@XVIA-SERVICIOSJURIDICOS.COM",
        "denuncia_num": expediente,
        "plate_number": _normalize_plate(row.get("matricula")) or FALLBACKS["Matricula"],
        "expediente_num": expediente,
        "sujeto_recurso": _clean_str(row.get("sujeto_recurso")),
        # OJO: aquí ya va HTML (si output="html"), para insertarlo como HTML en TinyMCE
        "motivos": motivos,
        "adjuntos": adjuntos_list or [],
        "mandatario": mandatario,  # NUEVO
        "fase_procedimiento": _clean_str(row.get("FaseProcedimiento")),  # NUEVO: Para organizar justificantes
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


def _insert_task(db_path: str, site_id: str, payload: dict[str, Any]) -> int:
    conn = sqlite3.connect(Path(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tramite_queue (site_id, protocol, payload) VALUES (?, ?, ?)",
            (site_id, None, json.dumps(payload, ensure_ascii=False, default=str)),
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
    trusted = (os.getenv("SQLSERVER_TRUSTED_CONNECTION") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }

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
        help="El idRecurso que queremos buscar (obligatorio).",
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
        print(f"ERROR: No se pudo construir la conexión a SQL Server: {e}", file=sys.stderr)
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
            print(f"ERROR: No se encontró ningún registro con idRecurso = {args.id}", file=sys.stderr)
            return 1

        # Agrupar adjuntos por idRecurso (aunque solo hay uno, puede tener múltiples adjuntos)
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
            if adj_id:
                filename_clean = _clean_str(adj_filename)
                if not filename_clean:
                    raise ValueError(
                        f"Adjunto {adj_id} sin filename en SQL Server (no se permite fallback)."
                    )
                task_data["adjuntos"].append(
                    {
                        "id": adj_id,
                        "filename": filename_clean,
                        "url": (
                            "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/"
                            "recursos/expedientes/pdf-adjuntos/{id}"
                        ).format(id=adj_id),
                    }
                )

        # Mapear el payload
        try:
            expediente = _clean_str(task_data["row"].get("Expedient"))
            fase_raw = task_data["row"].get("FaseProcedimiento")
            sujeto_recurso = _clean_str(task_data["row"].get("sujeto_recurso"))

            # Motivos en HTML para TinyMCE (saltos visibles)
            motivos_html = get_motivos_por_fase(
                fase_raw,
                expediente,
                config_map=motivos_config,
                sujeto_recurso=sujeto_recurso,
                output="text",
            )

            payload = _map_payload(
                task_data["row"],
                motivos_html,
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
                print("\nPayload completo:")
                print(json.dumps(payload, indent=2, ensure_ascii=False))

            return 0

        except Exception as e:
            print(f"ERROR procesando idRecurso {args.id}: {e}", file=sys.stderr)
            if args.verbose:
                traceback.print_exc()
            return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
