from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyodbc

from core.sqlserver_utils import build_sqlserver_connection_string
from core.worker_execution.browser_executor import execute_browser_flow
from sites.diputacio_bcn.controller import DiputacioBcnController


SQL_BY_ID = """
SELECT TOP 1
    rs.idRecurso,
    rs.idExp,
    rs.Expedient
FROM Recursos.RecursosExp rs
WHERE rs.idRecurso = ?
"""


def fetch_resource_by_id(id_recurso: int) -> dict[str, Any]:
    conn_str = build_sqlserver_connection_string()
    conn = pyodbc.connect(conn_str)
    try:
        cur = conn.cursor()
        cur.execute(SQL_BY_ID, id_recurso)
        row = cur.fetchone()
        if not row:
            raise LookupError(f"No existe idRecurso={id_recurso}")
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def build_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    expediente = str(row.get("Expedient") or "").strip()
    expediente_digits = "".join(ch for ch in expediente if ch.isdigit())
    default_phone = (os.getenv("DIPUTACIO_BCN_TELEFON") or "600000000").strip()
    default_email = (os.getenv("DIPUTACIO_BCN_EMAIL") or "notificacions@example.com").strip()
    doc_acreditativa = (os.getenv("DIPUTACIO_BCN_DOC_ACREDITATIVA") or "").strip()
    doc_tramite = (os.getenv("DIPUTACIO_BCN_DOC_TRAMITE") or "").strip()
    comentari = (
        os.getenv("DIPUTACIO_BCN_COMENTARI")
        or f"Presentacio documentacio expedient sancionador {expediente or 'N/A'}"
    ).strip()
    nif_default = (os.getenv("DIPUTACIO_BCN_NIF_INTERESSAT") or "00000000T").strip().upper()

    archivos = [p for p in [doc_acreditativa, doc_tramite] if p]
    return {
        "idRecurso": row.get("idRecurso"),
        "idExp": row.get("idExp"),
        "expediente": expediente,
        "exp_sancionador": (os.getenv("DIPUTACIO_BCN_EXP_SANCIONADOR") or expediente).strip(),
        "matricula": (os.getenv("DIPUTACIO_BCN_MATRICULA") or "").strip().upper(),
        "municipio": (os.getenv("DIPUTACIO_BCN_MUNICIPIO") or "08019").strip(),
        "tipo_representado": (os.getenv("DIPUTACIO_BCN_TIPO_REPRESENTADO") or "fisica").strip().lower(),
        "nif_interessat": nif_default,
        "nom_cr4": (os.getenv("DIPUTACIO_BCN_NOM_CR4") or "Nom").strip(),
        "cognom1": (os.getenv("DIPUTACIO_BCN_COGNOM1") or "Cognom1").strip(),
        "cognom2": (os.getenv("DIPUTACIO_BCN_COGNOM2") or "Cognom2").strip(),
        "nom_juridica": (os.getenv("DIPUTACIO_BCN_NOM_JURIDICA") or "Empresa SL").strip(),
        "doc_acreditativa": doc_acreditativa,
        "doc_tramite": doc_tramite,
        "comentari": comentari,
        "telefon": default_phone,
        "email": default_email,
        "archivos": archivos,
        "trace_tag": f"id{row.get('idRecurso')}_{expediente_digits or 'sinexp'}",
    }


async def run_flow(payload: dict[str, Any]) -> dict[str, Any]:
    outcome = await execute_browser_flow(
        site_id="diputacio_bcn",
        protocol=None,
        payload=payload,
        archivos_para_subir=[],
    )
    return {
        "success": bool(outcome.success),
        "error": outcome.error,
        "screenshot": outcome.screenshot,
        "payload_updates": outcome.payload_updates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone smoke test for diputacio_bcn.")
    parser.add_argument("--id", type=int, required=True, help="idRecurso en SQL Server")
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local")
    args = parser.parse_args()

    row = fetch_resource_by_id(args.id)
    payload = build_payload_from_row(row)

    controller = DiputacioBcnController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / "diputacio_bcn_raw_{}.json".format(args.id)
    payload_path = out / "diputacio_bcn_payload_{}.json".format(args.id)
    mapped_path = out / "diputacio_bcn_mapped_{}.json".format(args.id)
    raw_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mapped_path.write_text(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] SQL raw: {raw_path}")
    print(f"[OK] payload: {payload_path}")
    print(f"[OK] mapped target: {mapped_path}")

    if args.dump_only and not args.run_flow:
        return

    if args.run_flow:
        result = asyncio.run(run_flow(payload))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
