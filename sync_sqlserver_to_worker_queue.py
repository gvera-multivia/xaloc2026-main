import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

try:
    import pyodbc  # type: ignore
except Exception:  # pragma: no cover
    pyodbc = None


BASE_SELECT_QUERY = """
SELECT
    rs.idRecurso,
    rs.Expedient,
    rs.Matricula,
    rs.DtaDenuncia,
    rs.Organisme,
    c.Nombre,
    c.Apellido1,
    c.Apellido2,
    c.nif,
    c.email,
    c.movil,
    c.telefono1,
    c.calle,
    c.numero,
    c.Cpostal,
    c.poblacion,
    c.provincia,
    d.ConducDni
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
LEFT JOIN DadesIdentif d ON rs.Expedient = d.Expedient
"""


def build_query(*, fase: str | None) -> tuple[str, list[Any]]:
    """
    Construye la query y parámetros.

    Nota: en algunos entornos `FaseProcedimiento` no es un "estado" tipo PENDIENTE,
    sino un tipo (denuncia/apremio/embargo/sancion/identificacion). Por eso el filtro es opcional.
    """
    query = BASE_SELECT_QUERY.strip()
    params: list[Any] = []
    fase_norm = (fase or "").strip()
    if fase_norm:
        query += "\nWHERE LTRIM(RTRIM(rs.FaseProcedimiento)) = ?"
        params.append(fase_norm)
    return query, params

DEFAULT_MADRID_EXPONE = "Alegación automática basada en registros de base de datos."
DEFAULT_MADRID_SOLICITA = "Solicitud automática basada en registros de base de datos."
DEFAULT_XALOC_MOTIVOS = "Presentación de alegaciones según procedimiento estándar."


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_phone(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_str(value))


def _normalize_plate(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_str(value)).upper()


def _format_ddmmyyyy(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).strftime("%d/%m/%Y")
    return ""


def _year(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return str(value.year)
    if isinstance(value, date):
        return str(value.year)
    return ""


@dataclass(frozen=True)
class MadridExpedienteParsed:
    exp_tipo: str  # opcion1|opcion2
    exp_nnn: str = ""
    exp_eeeeeeeee: str = ""
    exp_d: str = ""
    exp_lll: str = ""
    exp_aaaa: str = ""
    exp_exp_num: str = ""


_MADRID_OP1_RE = re.compile(r"^\s*(\d{1,3})\s*/\s*(\d{1,9})\s*\.\s*(\d{1,2})\s*$")
_MADRID_OP2_RE = re.compile(r"^\s*([A-Z]{3})\s*/\s*(\d{4})\s*/\s*(\d{1,9})\s*$")


def _parse_madrid_expediente(expedient_raw: Any) -> MadridExpedienteParsed:
    raw = _clean_str(expedient_raw).upper()
    if not raw:
        return MadridExpedienteParsed(exp_tipo="opcion1")

    m1 = _MADRID_OP1_RE.match(raw)
    if m1:
        return MadridExpedienteParsed(
            exp_tipo="opcion1",
            exp_nnn=m1.group(1),
            exp_eeeeeeeee=m1.group(2),
            exp_d=m1.group(3),
        )

    m2 = _MADRID_OP2_RE.match(raw)
    if m2:
        return MadridExpedienteParsed(
            exp_tipo="opcion2",
            exp_lll=m2.group(1),
            exp_aaaa=m2.group(2),
            exp_exp_num=m2.group(3),
        )

    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if len(parts) >= 2 and "." in parts[1]:
        exp, d = (parts[1].split(".", 1) + [""])[:2]
        return MadridExpedienteParsed(exp_tipo="opcion1", exp_nnn=parts[0], exp_eeeeeeeee=exp, exp_d=d)

    if len(parts) >= 3:
        return MadridExpedienteParsed(exp_tipo="opcion2", exp_lll=parts[0], exp_aaaa=parts[1], exp_exp_num=parts[2])

    return MadridExpedienteParsed(exp_tipo="opcion1")


def _infer_site_id(organisme: Any) -> str:
    org = _clean_str(organisme).upper()
    if "MADRID" in org:
        return "madrid"
    # Girona: el portal implementado es XALOC Girona (no SCT/otros organismos de Girona).
    if "XALOC" in org or "GIRONA" in org:
        return "xaloc_girona"
    if "TARRAGONA" in org:
        return "base_online"

@dataclass(frozen=True)
class PayloadDefaults:
    archivos: list[str]
    madrid_representative_email: str = ""
    madrid_representative_phone: str = ""
    madrid_naturaleza: str = "A"
    madrid_expone: str = DEFAULT_MADRID_EXPONE
    madrid_solicita: str = DEFAULT_MADRID_SOLICITA
    xaloc_motivos: str = DEFAULT_XALOC_MOTIVOS


def _map_common_payload(row: dict[str, Any]) -> dict[str, Any]:
    nombre = _clean_str(row.get("Nombre"))
    apellido1 = _clean_str(row.get("Apellido1"))
    apellido2 = _clean_str(row.get("Apellido2"))

    full_name = " ".join(p for p in [nombre, apellido1, apellido2] if p).strip()

    payload: dict[str, Any] = {
        "user_phone": _clean_phone(row.get("movil")) or _clean_phone(row.get("telefono1")),
        "user_email": _clean_str(row.get("email")),
        "plate_number": _normalize_plate(row.get("Matricula")),
        "nif": _clean_str(row.get("nif")),
        "name": full_name,
        "address_street": _clean_str(row.get("calle")),
        "address_number": _clean_str(row.get("numero")),
        "address_zip": _clean_str(row.get("Cpostal")),
        "address_city": _clean_str(row.get("poblacion")),
        "address_province": _clean_str(row.get("provincia")),
    }
    return payload


def map_to_worker_payload(row: dict[str, Any], site_id: str, *, defaults: PayloadDefaults) -> dict[str, Any]:
    payload = _map_common_payload(row)
    payload["archivos"] = list(defaults.archivos)

    expediente_raw = row.get("Expedient")

    if site_id == "base_online":
        nif = payload.get("nif") or ""
        payload.update(
            {
                "expediente_id_ens": _clean_str(row.get("idRecurso")),
                "expediente_any": _year(row.get("DtaDenuncia")),
                "expediente_num": _clean_str(expediente_raw),
                "num_butlleti": "",
                "data_denuncia": _format_ddmmyyyy(row.get("DtaDenuncia")),
                "llicencia_conduccio": _clean_str(row.get("ConducDni")) or nif,
            }
        )

    elif site_id == "madrid":
        parsed = _parse_madrid_expediente(expediente_raw)
        notif_name_parts = (_clean_str(row.get("Nombre")).upper(), _clean_str(row.get("Apellido1")).upper(), _clean_str(row.get("Apellido2")).upper())
        payload.update(
            {
                "expediente_tipo": parsed.exp_tipo,
                "expediente_nnn": parsed.exp_nnn,
                "expediente_eeeeeeeee": parsed.exp_eeeeeeeee,
                "expediente_d": parsed.exp_d,
                "expediente_lll": parsed.exp_lll,
                "expediente_aaaa": parsed.exp_aaaa,
                "expediente_exp_num": parsed.exp_exp_num,
                "naturaleza": defaults.madrid_naturaleza,
                "expone": defaults.madrid_expone,
                "solicita": defaults.madrid_solicita,
                "notif_name": notif_name_parts[0],
                "notif_surname1": notif_name_parts[1],
                "notif_surname2": notif_name_parts[2],
            }
        )
        if defaults.madrid_representative_email:
            payload["representative_email"] = defaults.madrid_representative_email
        if defaults.madrid_representative_phone:
            payload["representative_phone"] = defaults.madrid_representative_phone

    elif site_id == "xaloc_girona":
        payload.update(
            {
                "denuncia_num": _clean_str(expediente_raw),
                "expediente_num": _clean_str(expediente_raw),
                "motivos": defaults.xaloc_motivos,
            }
        )

    cleaned: dict[str, Any] = {"archivos": payload.get("archivos", [])}
    for key, value in payload.items():
        if key == "archivos":
            continue
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        cleaned[key] = value
    return cleaned


def map_to_preview_payload(row: dict[str, Any], site_id: str) -> dict[str, Any]:
    """
    Genera un payload "mínimo" para previsualización:
    - Solo incluye campos derivados de columnas de DB.
    - NO añade `archivos` por defecto.
    - NO añade textos/representante/motivos por defecto.
    """
    payload = _map_common_payload(row)

    expediente_raw = row.get("Expedient")

    if site_id == "base_online":
        nif = payload.get("nif") or ""
        llic = _clean_str(row.get("ConducDni")) or nif
        payload.update(
            {
                "expediente_id_ens": _clean_str(row.get("idRecurso")),
                "expediente_any": _year(row.get("DtaDenuncia")),
                "expediente_num": _clean_str(expediente_raw),
                "data_denuncia": _format_ddmmyyyy(row.get("DtaDenuncia")),
                "llicencia_conduccio": llic,
            }
        )

    elif site_id == "madrid":
        parsed = _parse_madrid_expediente(expediente_raw)
        notif_name_parts = (
            _clean_str(row.get("Nombre")).upper(),
            _clean_str(row.get("Apellido1")).upper(),
            _clean_str(row.get("Apellido2")).upper(),
        )
        payload.update(
            {
                "expediente_tipo": parsed.exp_tipo,
                "expediente_nnn": parsed.exp_nnn,
                "expediente_eeeeeeeee": parsed.exp_eeeeeeeee,
                "expediente_d": parsed.exp_d,
                "expediente_lll": parsed.exp_lll,
                "expediente_aaaa": parsed.exp_aaaa,
                "expediente_exp_num": parsed.exp_exp_num,
                "notif_name": notif_name_parts[0],
                "notif_surname1": notif_name_parts[1],
                "notif_surname2": notif_name_parts[2],
            }
        )

    elif site_id == "xaloc_girona":
        payload.update(
            {
                "denuncia_num": _clean_str(expediente_raw),
                "expediente_num": _clean_str(expediente_raw),
            }
        )

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        cleaned[key] = value
    return cleaned


def _infer_protocol(site_id: str, *, default_protocol: str) -> Optional[str]:
    if site_id != "base_online":
        return None
    return default_protocol


def _read_query_from_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


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
                    result JSON
                );
                """
            )
        conn.commit()
    finally:
        conn.close()


def _insert_task(db_path: str, site_id: str, protocol: Optional[str], payload: dict[str, Any]) -> int:
    conn = sqlite3.connect(Path(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tramite_queue (site_id, protocol, payload) VALUES (?, ?, ?)",
            (site_id, protocol, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sincroniza trámites desde SQL Server (solo lectura) a la cola SQLite del worker."
    )
    parser.add_argument("--connection-string", required=True, help="Connection string para pyodbc (SQL Server).")
    parser.add_argument(
        "--site",
        default="auto",
        choices=["auto", "madrid", "xaloc_girona", "base_online"],
        help="Filtra qué portal encolar (default: auto = según Organisme).",
    )
    parser.add_argument(
        "--fase",
        default="",
        help="Filtro opcional por rs.FaseProcedimiento (ej: denuncia, apremio, embargo, sancion, identificacion).",
    )
    parser.add_argument("--query-file", default=None, help="Ruta a un .sql (si se quiere reemplazar la query default).")
    parser.add_argument("--sqlite-db", default="db/xaloc_database.db", help="Ruta a la SQLite del worker.")
    parser.add_argument("--default-protocol", default="P1", help="Protocolo por defecto para base_online (P1/P2/P3).")
    parser.add_argument(
        "--default-archivos",
        default="pdfs-prueba/test1.pdf",
        help="Lista CSV de adjuntos por defecto (rutas relativas).",
    )
    parser.add_argument("--madrid-representative-email", default="", help="Email fijo para representante (Madrid).")
    parser.add_argument("--madrid-representative-phone", default="", help="Teléfono fijo para representante (Madrid).")
    parser.add_argument("--madrid-naturaleza", default="A", help="Naturaleza (Madrid): A|R|I (default: A).")
    parser.add_argument("--madrid-expone", default=None, help="Texto 'expone' (Madrid).")
    parser.add_argument("--madrid-solicita", default=None, help="Texto 'solicita' (Madrid).")
    parser.add_argument("--xaloc-motivos", default=None, help="Texto 'motivos' (Xaloc Girona).")
    parser.add_argument("--dry-run", action="store_true", help="No inserta; solo muestra el resumen.")
    parser.add_argument("--limit", type=int, default=0, help="Máximo de filas a procesar (0 = sin límite).")
    parser.add_argument("--verbose", action="store_true", help="Muestra errores de filas en stderr.")

    args = parser.parse_args(argv)

    if pyodbc is None:
        print("ERROR: Falta pyodbc. Instala el driver y el paquete: `pip install pyodbc`.", file=sys.stderr)
        return 2

    query, query_params = build_query(fase=args.fase) if not args.query_file else (_read_query_from_file(args.query_file), [args.fase] if args.fase else [])
    default_archivos = [a.strip() for a in str(args.default_archivos).split(",") if a.strip()]
    default_protocol = str(args.default_protocol).strip().upper() or "P1"
    defaults = PayloadDefaults(
        archivos=default_archivos,
        madrid_representative_email=_clean_str(args.madrid_representative_email),
        madrid_representative_phone=_clean_phone(args.madrid_representative_phone),
        madrid_naturaleza=_clean_str(args.madrid_naturaleza).upper() or "A",
        madrid_expone=_clean_str(args.madrid_expone) if args.madrid_expone is not None else DEFAULT_MADRID_EXPONE,
        madrid_solicita=_clean_str(args.madrid_solicita) if args.madrid_solicita is not None else DEFAULT_MADRID_SOLICITA,
        xaloc_motivos=_clean_str(args.xaloc_motivos) if args.xaloc_motivos is not None else DEFAULT_XALOC_MOTIVOS,
    )

    _init_sqlite(args.sqlite_db)

    counts_by_site: Counter[str] = Counter()
    counts_by_site_protocol: dict[str, Counter[str]] = defaultdict(Counter)
    inserted_ids: list[int] = []
    row_errors = 0

    conn = pyodbc.connect(args.connection_string)
    try:
        cursor = conn.cursor()
        cursor.execute(query, tuple(query_params))
        columns = [c[0] for c in cursor.description]

        scanned = 0
        matched = 0
        for row in cursor:
            scanned += 1

            try:
                row_dict = dict(zip(columns, row))
                site_id = _infer_site_id(row_dict.get("Organisme"))
                if args.site != "auto" and site_id != args.site:
                    continue
                if args.limit and matched >= args.limit:
                    break
                protocol = _infer_protocol(site_id, default_protocol=default_protocol)
                payload = map_to_worker_payload(row_dict, site_id, defaults=defaults)

                counts_by_site[site_id] += 1
                counts_by_site_protocol[site_id][protocol or "-"] += 1
                matched += 1

                if not args.dry_run:
                    task_id = _insert_task(args.sqlite_db, site_id, protocol, payload)
                    inserted_ids.append(task_id)

            except Exception:
                row_errors += 1
                if args.verbose:
                    rid = row_dict.get("idRecurso") if "row_dict" in locals() else None
                    exp = row_dict.get("Expedient") if "row_dict" in locals() else None
                    print(f"[fila error] idRecurso={rid} Expedient={exp}", file=sys.stderr)

    finally:
        conn.close()

    print("Resumen de sincronización")
    print(f"- SQLite: {args.sqlite_db}")
    print(f"- Fase: {args.fase}")
    print(f"- Filas leídas: {scanned}")
    print(f"- Filas procesadas: {sum(counts_by_site.values())}")
    print(f"- Errores de fila: {row_errors}")
    for site_id, count in counts_by_site.items():
        print(f"  - {site_id}: {count} ({dict(counts_by_site_protocol[site_id])})")

    if args.dry_run:
        print("- Modo: dry-run (no se insertaron tareas)")
    else:
        print(f"- Tareas insertadas: {len(inserted_ids)}")

    return 0 if row_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
