from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyodbc

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.client_documentation import build_required_client_documents_for_payload
from core.client_paths import ClientIdentity, get_ruta_cliente_documentacion
from core.worker_execution.browser_executor import execute_browser_flow
from core.worker_execution.document_fetcher import download_document_and_attachments
from core.xvia_auth import create_authenticated_session
from sites.adapters.xaloc_girona import XalocAdapter
from sites.xaloc_girona.controller import XalocGironaController


DEFAULT_CLIENT_DOCS_BASE_PATH = r"\\SERVER-DOC\clientes"
DEFAULT_SQLSERVER_CONNECTION_STRING = (
    "DRIVER=SQL Server;"
    "SERVER=BD-SERVER;"
    "DATABASE=MULTIVIA;"
    "UID=Xvia-Grupo;"
    "PWD=Xvia_Grupo_Multivia_20180806;"
    "LoginTimeout=10"
)

SQL_BY_ID = """
SELECT TOP 1
    r.idRecurso,
    r.idExp,
    r.numclient,
    r.automatic_id,
    r.Expedient,
    r.FaseProcedimiento,
    r.Organisme,
    r.Estado,
    r.UsuarioAsignado,
    r.FUsuarioCompletado,
    r.SujetoRecurso,
    r.Matricula AS recurso_matricula,
    e.matricula AS expediente_matricula,
    c.tipodecliente AS cliente_tipo,
    c.nif AS cliente_nif,
    c.nifempresa,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2,
    c.Nombrefiscal,
    c.Nombrefiscal AS cliente_razon_social
FROM Recursos.RecursosExp r
LEFT JOIN clientes c ON r.numclient = c.numerocliente
LEFT JOIN expedientes e ON r.idExp = e.idexpediente
WHERE r.idRecurso = ?
"""

SQL_ATTACHMENTS_BY_AUTOMATIC_ID = """
SELECT
    att.id AS adjunto_id,
    att.Filename AS adjunto_filename
FROM attachments_resource_documents att
WHERE att.automatic_id = ?
ORDER BY att.id ASC
"""


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _resolve_sqlserver_connection_string() -> str:
    env_conn = (os.getenv("SQLSERVER_CONN_STR") or "").strip()
    if env_conn:
        return env_conn
    env_conn = (os.getenv("SQLSERVER_CONNECTION_STRING") or "").strip()
    if env_conn:
        return env_conn
    return DEFAULT_SQLSERVER_CONNECTION_STRING


def _set_client_docs_base_for_local_windows() -> None:
    os.environ.setdefault("CLIENT_DOCS_BASE_PATH", DEFAULT_CLIENT_DOCS_BASE_PATH)
    os.environ.setdefault("CLIENT_DOCS_HOST_PATH", DEFAULT_CLIENT_DOCS_BASE_PATH)


def fetch_resource_by_id(id_recurso: int) -> dict[str, Any]:
    conn = pyodbc.connect(_resolve_sqlserver_connection_string())
    try:
        cur = conn.cursor()
        cur.execute(SQL_BY_ID, id_recurso)
        row = cur.fetchone()
        if not row:
            raise LookupError(f"No existe idRecurso={id_recurso}")

        cols = [c[0] for c in cur.description]
        data = dict(zip(cols, row))

        matricula = _clean(data.get("recurso_matricula")) or _clean(data.get("expediente_matricula"))
        data["matricula"] = matricula

        automatic_id = data.get("automatic_id")
        adjuntos: list[dict[str, Any]] = []
        if automatic_id not in (None, ""):
            cur.execute(SQL_ATTACHMENTS_BY_AUTOMATIC_ID, automatic_id)
            rows = cur.fetchall()
            att_cols = [c[0] for c in cur.description]
            for item in rows:
                att = dict(zip(att_cols, item))
                att_id = att.get("adjunto_id")
                if att_id in (None, ""):
                    continue
                filename = _clean(att.get("adjunto_filename")) or f"adjunto_{att_id}.pdf"
                adjuntos.append(
                    {
                        "id": int(att_id),
                        "filename": filename,
                        "url": (
                            "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/"
                            f"servicio/recursos/expedientes/pdf-adjuntos/{att_id}"
                        ),
                    }
                )
        data["adjuntos"] = adjuntos
        return data
    finally:
        conn.close()


def _collect_docs_from_subject_folder(row: dict[str, Any]) -> list[Path]:
    identity = ClientIdentity(
        is_company=str(row.get("cliente_tipo") or "").strip() == "2",
        sujeto_recurso=_clean(row.get("SujetoRecurso")) or None,
        empresa=_clean(row.get("cliente_razon_social")) or None,
        nombre=_clean(row.get("cliente_nombre")) or None,
        apellido1=_clean(row.get("cliente_apellido1")) or None,
        apellido2=_clean(row.get("cliente_apellido2")) or None,
    )
    ruta_cliente = get_ruta_cliente_documentacion(identity, base_path=os.getenv("CLIENT_DOCS_BASE_PATH"))
    if not ruta_cliente.exists():
        return []

    candidates: list[Path] = []
    for path in ruta_cliente.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
            continue
        parent_upper = str(path.parent).upper()
        if "DOCUMENTA" not in parent_upper and "RECURSOS" not in parent_upper:
            continue
        candidates.append(path)

    def _score(path: Path) -> tuple[int, int]:
        name = path.name.upper()
        parent = str(path.parent).upper()
        score = 0
        if "DOCUMENTACION_RECURSOS" in parent or "DOCUMENTACION RECURSOS" in parent:
            score += 100
        if any(token in name for token in ("AUT", "ACREDIT", "MANDAT", "REPRESENT")):
            score += 90
        if any(token in name for token in ("RECUR", "ALEG")):
            score += 80
        if any(token in name for token in ("DNI", "NIE", "CIF")):
            score += 60
        if path.suffix.lower() == ".pdf":
            score += 20
        return score, -len(str(path))

    candidates.sort(key=_score, reverse=True)
    return candidates[:15]


async def build_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    adapter = XalocAdapter()
    payloads = await adapter.build_payloads([row])
    if not payloads:
        raise RuntimeError(f"No se pudo construir payload XALOC para idRecurso={row.get('idRecurso')}")
    payload = payloads[0]
    payload["docs_base_path"] = os.getenv("CLIENT_DOCS_BASE_PATH") or DEFAULT_CLIENT_DOCS_BASE_PATH
    return payload


async def enrich_documents(payload: dict[str, Any], row: dict[str, Any], *, strict: bool) -> dict[str, list[str]]:
    _set_client_docs_base_for_local_windows()

    client_docs: list[Path] = []
    try:
        client_docs = await build_required_client_documents_for_payload(
            payload,
            sqlserver_conn_str=_resolve_sqlserver_connection_string(),
            strict=False,
        )
    except Exception:
        client_docs = []
    if not client_docs:
        client_docs = _collect_docs_from_subject_folder(row)

    payload["required_client_doc_paths"] = [str(p) for p in client_docs if p and Path(p).exists()]
    payload["archivos"] = list(payload["required_client_doc_paths"])

    xvia_docs: list[Path] = []
    email = (os.getenv("XVIA_EMAIL") or "").strip()
    password = (os.getenv("XVIA_PASSWORD") or "").strip()
    if email and password:
        session = await create_authenticated_session(email, password)
        try:
            xvia_docs = await download_document_and_attachments(payload=payload, auth_session=session)
        finally:
            await session.close()
    elif strict:
        raise RuntimeError("Faltan XVIA_EMAIL/XVIA_PASSWORD para descargar recurso y adjuntos desde XVIA.")

    merged: list[str] = []
    seen: set[str] = set()
    for raw in [*xvia_docs, *client_docs]:
        path = Path(raw)
        if not path.exists():
            continue
        key = os.path.normcase(os.path.normpath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        merged.append(str(path))

    if strict:
        if not payload.get("xvia_recurso_path"):
            raise RuntimeError("No se ha podido descargar el recurso principal desde XVIA.")
        if not payload.get("required_client_doc_paths"):
            raise RuntimeError("No se ha encontrado documentacion/autorizacion del cliente.")

    payload["archivos"] = merged
    return {
        "xvia_docs": [str(p) for p in xvia_docs],
        "client_docs": [str(p) for p in client_docs],
        "merged_docs": merged,
    }


async def run_flow(payload: dict[str, Any]) -> dict[str, Any]:
    prev_confirm = os.getenv("XALOC_CONFIRM_BEFORE_SEND")
    prev_close_sleep = os.getenv("XALOC_CLOSE_SLEEP_SECONDS")
    try:
        os.environ["XALOC_CONFIRM_BEFORE_SEND"] = "1"
        os.environ.setdefault("XALOC_CLOSE_SLEEP_SECONDS", "0")
        archivos = [Path(str(path)) for path in payload.get("archivos", []) if str(path).strip()]
        outcome = await execute_browser_flow(
            site_id="xaloc_girona",
            protocol=None,
            payload=payload,
            archivos_para_subir=archivos,
        )
    finally:
        if prev_confirm is None:
            os.environ.pop("XALOC_CONFIRM_BEFORE_SEND", None)
        else:
            os.environ["XALOC_CONFIRM_BEFORE_SEND"] = prev_confirm
        if prev_close_sleep is None:
            os.environ.pop("XALOC_CLOSE_SLEEP_SECONDS", None)
        else:
            os.environ["XALOC_CLOSE_SLEEP_SECONDS"] = prev_close_sleep

    return {
        "success": bool(outcome.success),
        "error": outcome.error,
        "screenshot": outcome.screenshot,
        "payload_updates": outcome.payload_updates,
    }


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Standalone smoke test controlado para xaloc_girona.")
    parser.add_argument("--id", type=int, required=True, help="idRecurso en SQL Server")
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local con pausa antes de presentar")
    args = parser.parse_args()

    row = fetch_resource_by_id(args.id)
    payload = await build_payload_from_row(row)
    doc_stats = await enrich_documents(payload, row, strict=bool(args.run_flow))

    controller = XalocGironaController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / f"xaloc_girona_raw_{args.id}.json"
    payload_path = out / f"xaloc_girona_payload_{args.id}.json"
    mapped_path = out / f"xaloc_girona_mapped_{args.id}.json"
    docs_path = out / f"xaloc_girona_docs_{args.id}.json"
    raw_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mapped_path.write_text(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    docs_path.write_text(json.dumps(doc_stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"[OK] SQL raw: {raw_path}")
    print(f"[OK] payload: {payload_path}")
    print(f"[OK] mapped target: {mapped_path}")
    print(f"[OK] docs merged: {docs_path}")
    print(
        "[INFO] docs -> xvia=%s client_mount=%s total=%s"
        % (
            len(doc_stats.get("xvia_docs") or []),
            len(doc_stats.get("client_docs") or []),
            len(doc_stats.get("merged_docs") or []),
        )
    )

    if args.dump_only and not args.run_flow:
        return

    if args.run_flow:
        result = await run_flow(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
