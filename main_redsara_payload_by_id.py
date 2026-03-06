from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyodbc

from core.address_classifier import classify_address_fallback
from core.sqlserver_utils import build_sqlserver_connection_string
from sites.redsara.controller import RedsaraController


SQL_BY_ID = """
SELECT TOP 1
    rs.idRecurso,
    rs.idExp,
    rs.Expedient,
    rs.SujetoRecurso,
    rs.cif,
    c.nif AS cliente_nif,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    c.provincia AS cliente_provincia,
    c.poblacion AS cliente_municipio,
    c.calle AS cliente_domicilio,
    c.Cpostal AS cliente_cp,
    c.email AS cliente_email,
    c.telefono1 AS cliente_tel1,
    c.telefono2 AS cliente_tel2,
    c.movil AS cliente_movil
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
WHERE rs.idRecurso = ?
"""


def _clean(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _normalize_doc(v: Any) -> str:
    doc = _clean(v).upper()
    if doc.startswith("ES") and len(doc) > 2:
        doc = doc[2:]
    return re.sub(r"[^A-Z0-9]+", "", doc)


def _normalize_cp(v: Any) -> str:
    cp = re.sub(r"\D+", "", _clean(v))
    if not cp:
        return ""
    return cp[:5].zfill(5)


def _pick_phone(row: dict[str, Any]) -> str:
    for key in ("cliente_movil", "cliente_tel1", "cliente_tel2"):
        value = _clean(row.get(key))
        if value:
            return value
    return ""


def _build_brain_like_payload(row: dict[str, Any]) -> dict[str, Any]:
    domicilio_raw = _clean(row.get("cliente_domicilio"))
    clasif = classify_address_fallback(domicilio_raw)

    tipo_via = _clean(clasif.get("tipo_via") or "CALLE").upper()
    calle = _clean(clasif.get("calle") or domicilio_raw).upper()
    provincia = _clean(row.get("cliente_provincia")).upper()
    municipio = _clean(row.get("cliente_municipio")).upper()
    cp = _normalize_cp(row.get("cliente_cp"))
    nif = _normalize_doc(row.get("cif") or row.get("cliente_nif"))
    name = _clean(row.get("SujetoRecurso") or row.get("cliente_nombre")).upper()
    surname1 = _clean(row.get("cliente_apellido1")).upper()
    surname2 = _clean(row.get("cliente_apellido2")).upper()
    email = _clean(row.get("cliente_email")).lower()
    phone = _pick_phone(row)

    # Payload en formato compatible con el orquestador/base + aliases redsara.
    payload: dict[str, Any] = {
        "idRecurso": row.get("idRecurso"),
        "idExp": row.get("idExp"),
        "expediente": _clean(row.get("Expedient")),
        "nif": nif,
        "name": name,
        "surname1": surname1,
        "surname2": surname2,
        "address_sigla": tipo_via,
        "address_street": calle,
        "address_zip": cp,
        "address_city": municipio,
        "address_province": provincia,
        "user_phone": phone,
        "user_email": email,
        # Claves directas REDSARA para representante
        "rep_tipo_via": tipo_via,
        "rep_direccion": calle,
        "rep_provincia": provincia,
        "rep_poblacion": municipio,
        "rep_cp": cp,
        "rep_phone": phone,
        "rep_email": email,
        # Campos no directamente en SQL (se pueden sobreescribir por env)
        "tipo_doc_interesado": os.getenv("REDSARA_INT_DOC_TYPE", "NIF"),
        "destination_organism_code": os.getenv("REDSARA_DEST_ORGANISM_CODE", "LA0007892"),
        "subject": os.getenv("REDSARA_SUBJECT", "PRUEBA REDSARA"),
        "exposes": os.getenv("REDSARA_EXPOSES", "Texto de prueba para el campo expone."),
        "solicit": os.getenv("REDSARA_SOLICIT", "Texto de prueba para el campo solicita."),
    }
    return payload


def _fetch_resource_by_id(id_recurso: int) -> dict[str, Any]:
    conn_str = build_sqlserver_connection_string()
    conn = pyodbc.connect(conn_str)
    try:
        cur = conn.cursor()
        cur.execute(SQL_BY_ID, id_recurso)
        row = cur.fetchone()
        if not row:
            raise LookupError(f"No existe idRecurso={id_recurso} en SQL Server")
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lee SQL por idRecurso y genera payload REDSARA mapeado.")
    parser.add_argument("--id", type=int, default=91216, help="idRecurso a consultar en SQL Server")
    args = parser.parse_args()

    try:
        row = _fetch_resource_by_id(args.id)
    except pyodbc.Error as exc:
        print(f"[ERROR] No se pudo leer SQL Server: {exc}")
        try:
            print(f"[INFO] Drivers ODBC detectados: {pyodbc.drivers()}")
        except Exception:
            pass
        return
    payload = _build_brain_like_payload(row)

    controller = RedsaraController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out_dir = Path("redsara-doc")
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"redsara_sql_raw_{args.id}.json"
    payload_path = out_dir / f"redsara_payload_brain_like_{args.id}.json"
    mapped_path = out_dir / f"redsara_mapped_target_{args.id}.json"

    raw_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mapped_path.write_text(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"[OK] SQL raw guardado: {raw_path}")
    print(f"[OK] Payload brain-like guardado: {payload_path}")
    print(f"[OK] Target REDSARA guardado: {mapped_path}")


if __name__ == "__main__":
    main()
