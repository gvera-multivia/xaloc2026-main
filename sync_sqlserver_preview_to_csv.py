import csv
import json
import sys
from pathlib import Path
from typing import Any

try:
    import pyodbc  # type: ignore
except Exception:  # pragma: no cover
    pyodbc = None

from sync_sqlserver_to_worker_queue import build_query, _infer_protocol, _infer_site_id, map_to_preview_payload


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_connection_string(cfg: dict[str, Any]) -> str:
    if "connection_string" in cfg and cfg["connection_string"]:
        return str(cfg["connection_string"])

    sql = cfg.get("sqlserver") or {}
    driver = sql.get("driver") or "SQL Server"
    server = sql.get("server") or ""
    database = sql.get("database") or ""
    username = sql.get("username") or ""
    password = sql.get("password") or ""

    if not (server and database and username and password):
        raise ValueError("Faltan datos de conexión. Rellena sqlserver.{server,database,username,password} en el config.")

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password}"
    )


def _prompt_site_filter() -> str:
    opciones = {
        "1": "madrid",
        "2": "xaloc_girona",
        "3": "base_online",
        "4": "auto",
    }
    print("¿Qué web quieres previsualizar?")
    print("  1) Madrid")
    print("  2) Xaloc Girona")
    print("  3) BASE On-line")
    print("  4) Todas (auto)")
    while True:
        raw = input("Selecciona (1-4): ").strip()
        if raw in opciones:
            return opciones[raw]
        if raw in {"madrid", "xaloc_girona", "base_online", "auto"}:
            return raw
        print("Opción inválida.")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if pyodbc is None:
        print("ERROR: Falta pyodbc. Instala el driver y el paquete: `pip install pyodbc`.", file=sys.stderr)
        return 2

    cfg_path = Path("sync_sqlserver_config.json")
    cfg = _load_config(cfg_path)

    site_filter = _prompt_site_filter()
    fase = str(cfg.get("fase") or "").strip()
    limit = int(cfg.get("limit") or 0)

    default_protocol = str(cfg.get("default_protocol_base_online") or "P1").strip().upper()

    output_csv = Path(str(cfg.get("output_csv") or "out/sync_preview.csv"))
    _ensure_parent(output_csv)

    cs = _build_connection_string(cfg)

    rows_out: list[dict[str, Any]] = []
    processed = 0
    skipped = 0

    conn = pyodbc.connect(cs)
    try:
        cur = conn.cursor()
        query, params = build_query(fase=fase)
        cur.execute(query, tuple(params))
        columns = [c[0] for c in cur.description]

        for row in cur:
            if limit and processed >= limit:
                break

            row_dict = dict(zip(columns, row))
            inferred_site = _infer_site_id(row_dict.get("Organisme"))

            if site_filter != "auto" and inferred_site != site_filter:
                skipped += 1
                continue

            protocol = _infer_protocol(inferred_site, default_protocol=default_protocol)
            payload = map_to_preview_payload(row_dict, inferred_site)

            rows_out.append(
                {
                    "site_id": inferred_site,
                    "protocol": protocol or "",
                    "idRecurso": row_dict.get("idRecurso"),
                    "Expedient": row_dict.get("Expedient"),
                    "Matricula": row_dict.get("Matricula"),
                    "Organisme": row_dict.get("Organisme"),
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                }
            )
            processed += 1
    finally:
        conn.close()

    fieldnames = ["site_id", "protocol", "idRecurso", "Expedient", "Matricula", "Organisme", "payload_json"]
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    print("Previsualización generada")
    print(f"- Config: {cfg_path}")
    print(f"- Fase: {fase}")
    print(f"- Filtro: {site_filter}")
    print(f"- Filas exportadas: {len(rows_out)} (skipped={skipped})")
    print(f"- CSV: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
