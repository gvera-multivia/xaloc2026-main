from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import unicodedata
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyodbc

from core.client_docs_service import get_required_client_documents
from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
from core.worker_execution.browser_executor import execute_browser_flow
from core.worker_execution.document_fetcher import download_document_and_attachments
from core.xvia_auth import create_authenticated_session
from sites.atc.controller import AtcController

HARDCODED_SQLSERVER_CONNECTION_STRING = (
    "DRIVER=SQL Server;"
    "SERVER=BD-SERVER;"
    "DATABASE=MULTIVIA;"
    "UID=Xvia-Grupo;"
    "PWD=Xvia_Grupo_Multivia_20180806;"
    "LoginTimeout=10"
)


SQL_BY_ID = """
SELECT TOP 1
    rs.idRecurso,
    rs.idExp,
    rs.numclient,
    rs.automatic_id,
    rs.Expedient,
    rs.Procedim,
    rs.FaseProcedimiento,
    rs.fecpres,
    e.ExpedientePublicacion,
    c.tipodecliente,
    c.nif,
    c.nifempresa,
    c.Nombre,
    c.Apellido1,
    c.Apellido2,
    c.Nombrefiscal
FROM Recursos.RecursosExp rs
LEFT JOIN expedientes e ON rs.idExp = e.idexpediente
LEFT JOIN clientes c ON rs.numclient = c.numerocliente
WHERE rs.idRecurso = ?
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
    return str(value or "").strip()


_EXPEDIENT_PATTERNS = (
    re.compile(r"\b\d{14}\b"),
    re.compile(r"\b\d{5,}-\d{4}/\d{1,10}-[A-Z]{2,5}\b", re.IGNORECASE),
    re.compile(r"\b\d-\d{4}/\d{1,10}-[A-Z]{2,5}\b", re.IGNORECASE),
    re.compile(r"\b\d{4}/\d{6,}\b"),
)


def _normalize_expediente(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    text = " ".join(raw.split())
    for rx in _EXPEDIENT_PATTERNS:
        m = rx.search(text)
        if m:
            return m.group(0).strip()
    return text


def _parse_date(value: Any) -> date | None:
    raw = _clean(value)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(raw.split("+")[0], fmt).date()
        except Exception:
            continue
    return None


def _infer_protocol(csv_acto: str, procedim: str) -> str:
    if not csv_acto:
        return "registro_sin_csv"
    rea_re = re.compile(r"(RECLAMACION\s+(ECONOMICO|ECO)[- ]*(ADMINISTRATIVA|ADVA)|(?<!\w)REA(?!\w))", re.IGNORECASE)
    repos_re = re.compile(r"(RECURSO\s+(EXTRAORDINARIO|REVISION|DE\s+REPOSICION)|(?<!\w)REPOSICION(?!\w))", re.IGNORECASE)
    if rea_re.search(procedim or ""):
        return "rea"
    if repos_re.search(procedim or ""):
        return "reposicio"
    return "reposicio"


def _norm(value: Any) -> str:
    txt = _clean(value).lower()
    if not txt:
        return ""
    txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
    return " ".join(txt.split())


def _resolve_organo_from_phase(fase_procedimiento: Any, fallback: str = "") -> str:
    fase = _norm(fase_procedimiento)
    if any(token in fase for token in ("apremio", "embargo", "recaudacion")):
        return "Oficina Central de Recaudacion"
    if "inspeccion" in fase:
        return "Oficina Central de Inspeccion"
    if fase:
        return "Oficina Central de Gestion Tributaria"
    return _clean(fallback) or "Oficina Central de Gestion Tributaria"


def _is_empresa_tipodecliente(value: Any) -> bool | None:
    raw = _clean(value)
    if raw == "2":
        return True
    if raw == "1":
        return False
    return None


def _env_docs() -> list[str]:
    raw = _clean(os.getenv("ATC_DOC_PATHS"))
    if not raw:
        return []
    return [p.strip() for p in raw.split(";") if p.strip()]


def _build_documentos(paths: list[str], *, protocol: str) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for idx, path_str in enumerate(paths):
        p = Path(path_str)
        if protocol == "rea":
            tipus = "Al-legacions" if idx == 0 else "Documentacio acreditativa"
        elif protocol == "reposicio":
            tipus = "Documentacio acreditativa si escau"
        else:
            tipus = "Otros"
        docs.append({"fitxer": str(p), "tipus": tipus, "descripcio": p.stem[:80] or "Documento"})
    return docs


def _merge_paths(existing: list[str], incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw in [*existing, *incoming]:
        value = str(raw or "").strip()
        if not value:
            continue
        key = os.path.normcase(os.path.normpath(value))
        if key in seen:
            continue
        seen.add(key)
        merged.append(value)
    return merged


def fetch_resource_by_id(id_recurso: int) -> dict[str, Any]:
    conn = pyodbc.connect(HARDCODED_SQLSERVER_CONNECTION_STRING)
    try:
        cur = conn.cursor()
        cur.execute(SQL_BY_ID, id_recurso)
        row = cur.fetchone()
        if not row:
            raise LookupError(f"No existe idRecurso={id_recurso}")
        cols = [c[0] for c in cur.description]
        data = dict(zip(cols, row))

        automatic_id = data.get("automatic_id")
        adjuntos: list[dict[str, Any]] = []
        if automatic_id not in (None, ""):
            cur.execute(SQL_ATTACHMENTS_BY_AUTOMATIC_ID, automatic_id)
            rows = cur.fetchall()
            att_cols = [c[0] for c in cur.description]
            for r in rows:
                item = dict(zip(att_cols, r))
                att_id = item.get("adjunto_id")
                if att_id in (None, ""):
                    continue
                filename = _clean(item.get("adjunto_filename")) or f"adjunto_{att_id}.pdf"
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


def build_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    expediente = _normalize_expediente(row.get("Expedient"))
    csv_acto = _clean(row.get("ExpedientePublicacion"))
    procedim = _clean(row.get("Procedim"))
    protocol = _infer_protocol(csv_acto, procedim)
    fase_procedimiento = _clean(row.get("FaseProcedimiento"))
    nombre = _clean(row.get("Nombre"))
    apellido1 = _clean(row.get("Apellido1"))
    apellido2 = _clean(row.get("Apellido2"))
    nombre_fiscal = _clean(row.get("Nombrefiscal"))
    nombre_persona = " ".join([p for p in [nombre, apellido1, apellido2] if p]).strip()
    nif_empresa = _clean(row.get("nifempresa")).upper()
    nif_persona = _clean(row.get("nif")).upper()
    es_empresa = _is_empresa_tipodecliente(row.get("tipodecliente"))
    if es_empresa is True:
        representado_nombre = nombre_fiscal or nombre_persona
        nif_repr = nif_empresa or nif_persona
    elif es_empresa is False:
        representado_nombre = nombre_persona or nombre_fiscal
        nif_repr = nif_persona or nif_empresa
    else:
        representado_nombre = nombre_fiscal or nombre_persona
        nif_repr = nif_empresa or nif_persona
    fecpres = _parse_date(row.get("fecpres"))
    env_docs = _env_docs()

    return {
        "idRecurso": row.get("idRecurso"),
        "idExp": row.get("idExp"),
        "numclient": row.get("numclient"),
        "automatic_id": row.get("automatic_id"),
        "expediente": expediente,
        "procedim": procedim,
        "csv_acto": csv_acto,
        "protocol": protocol,
        "fecpres": fecpres.isoformat() if fecpres else "",
        "tipodecliente": _clean(row.get("tipodecliente")),
        "nif": _clean(row.get("nif")),
        "nifempresa": _clean(row.get("nifempresa")),
        "Nombre": nombre,
        "Apellido1": apellido1,
        "Apellido2": apellido2,
        "Nombrefiscal": nombre_fiscal,
        "representado_nif": nif_repr,
        "representado_nombre": representado_nombre,
        "alegaciones": f"Se formulan alegaciones en relacion con el expediente {expediente or 'N/A'} y se solicita su estimacion.",
        "motivo_reposicion": os.getenv("ATC_MOTIVO_REPOSICION", "Altres motius diferents dels anteriors."),
        "tipo_tramite": os.getenv("ATC_TIPO_TRAMITE", "Aporte de documentos"),
        "tipo_documento": os.getenv("ATC_TIPO_DOCUMENTO", "Expediente"),
        "impuesto": os.getenv("ATC_IMPUESTO", "Impuesto sobre sucesiones y donaciones"),
        "num_documento": os.getenv("ATC_NUM_DOCUMENTO", expediente),
        "email": (os.getenv("ATC_EMAIL") or "").strip() or get_default_contact_email(),
        "telefono": (os.getenv("ATC_TELEFONO") or "").strip() or get_default_contact_mobile(),
        "nif_interesado": os.getenv("ATC_NIF_INTERESADO", nif_repr),
        "nombre_interesado": os.getenv("ATC_NOMBRE_INTERESADO", representado_nombre),
        "fase_procedimiento": fase_procedimiento,
        "FaseProcedimiento": fase_procedimiento,
        "organo": _resolve_organo_from_phase(
            fase_procedimiento,
            fallback=os.getenv("ATC_ORGANO", "Oficina Central de Gestion Tributaria"),
        ),
        "asunto": os.getenv("ATC_ASUNTO", f"Aportacion de documentacion expediente {expediente or 'N/A'}"),
        "adjuntos": list(row.get("adjuntos") or []),
        "archivos": env_docs,
        "documentos": _build_documentos(env_docs, protocol=protocol),
    }


async def append_client_docs_into_payload(payload: dict[str, Any], *, strict: bool = True) -> None:
    require_client_docs = (os.getenv("REQUIRE_CLIENT_DOCS") or "1").strip().lower() not in {"0", "false", "no", "off"}
    disable_gesdoc = bool(payload.get("disable_gesdoc"))
    if not require_client_docs or disable_gesdoc:
        return

    merge_client_docs = (os.getenv("CLIENT_DOCS_MERGE") or "0").strip().lower() not in {"0", "false", "no", "off"}
    gesdoc_user = os.getenv("GESDOC_USER")
    gesdoc_pwd = os.getenv("GESDOC_PWD")
    try:
        extra_docs = await get_required_client_documents(
            payload,
            gesdoc_user=gesdoc_user,
            gesdoc_pwd=gesdoc_pwd,
            sqlserver_conn_str=HARDCODED_SQLSERVER_CONNECTION_STRING,
            strict=strict,
            merge_if_multiple=merge_client_docs,
            output_label=str(payload.get("idRecurso") or "atc"),
        )
    except Exception:
        if strict:
            raise
        extra_docs = []
    if not extra_docs:
        return

    merged_paths = _merge_paths(payload.get("archivos") or [], [str(p) for p in extra_docs])
    payload["archivos"] = merged_paths
    payload["documentos"] = _build_documentos(merged_paths, protocol=str(payload.get("protocol") or "registro_sin_csv"))


async def download_xvia_docs_into_payload(payload: dict[str, Any], *, strict: bool) -> None:
    email = (os.getenv("XVIA_EMAIL") or "").strip()
    password = (os.getenv("XVIA_PASSWORD") or "").strip()
    if not email or not password:
        if strict:
            raise RuntimeError("Faltan XVIA_EMAIL/XVIA_PASSWORD para descargar recurso y adjuntos desde Xvia.")
        return

    session = await create_authenticated_session(email, password)
    try:
        archivos = await download_document_and_attachments(payload=payload, auth_session=session)
    finally:
        await session.close()

    merged_paths = _merge_paths([str(p) for p in archivos if p], payload.get("archivos") or [])
    payload["archivos"] = merged_paths
    payload["documentos"] = _build_documentos(merged_paths, protocol=str(payload.get("protocol") or "registro_sin_csv"))


async def run_flow(payload: dict[str, Any]) -> dict[str, Any]:
    outcome = await execute_browser_flow(
        site_id="atc",
        protocol=payload.get("protocol"),
        payload=payload,
        archivos_para_subir=[Path(str(p)) for p in (payload.get("archivos") or []) if str(p).strip()],
    )
    return {
        "success": bool(outcome.success),
        "error": outcome.error,
        "screenshot": outcome.screenshot,
        "payload_updates": outcome.payload_updates,
    }


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Standalone smoke test for atc.")
    parser.add_argument("--id", type=int, required=True, help="idRecurso en SQL Server")
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local")
    args = parser.parse_args()

    row = fetch_resource_by_id(args.id)
    payload = build_payload_from_row(row)
    await download_xvia_docs_into_payload(payload, strict=bool(args.run_flow))
    await append_client_docs_into_payload(payload, strict=True)

    controller = AtcController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / f"atc_raw_{args.id}.json"
    payload_path = out / f"atc_payload_{args.id}.json"
    mapped_path = out / f"atc_mapped_{args.id}.json"
    raw_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mapped_path.write_text(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[ATC] idRecurso={payload.get('idRecurso')} expediente={payload.get('expediente')} protocol={payload.get('protocol')}")
    print(f"[ATC] csv_acto='{payload.get('csv_acto')}' numclient={payload.get('numclient')} fecpres={payload.get('fecpres')}")
    print("[ATC] payload:")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    print("[ATC] mapped_target:")
    print(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str))
    print(f"[OK] SQL raw: {raw_path}")
    print(f"[OK] payload: {payload_path}")
    print(f"[OK] mapped target: {mapped_path}")

    if args.dump_only and not args.run_flow:
        return

    if args.run_flow:
        result = await run_flow(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
