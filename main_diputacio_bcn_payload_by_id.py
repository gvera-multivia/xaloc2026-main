from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyodbc

from core.client_documentation import build_required_client_documents_for_payload
from core.client_paths import ClientIdentity, get_ruta_cliente_documentacion
from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
from core.sqlserver_utils import build_sqlserver_connection_string
from core.validation.validators import normalize_plate_with_fallback
from core.worker_execution.browser_executor import execute_browser_flow
from core.worker_execution.document_fetcher import download_document_and_attachments
from core.xvia_auth import create_authenticated_session
from sites.diputacio_bcn.controller import DiputacioBcnController
from sites.diputacio_bcn.texts import resolve_phase_texts

HARDCODED_CLIENT_DOCS_BASE_PATH = r"\\SERVER-DOC\clientes"
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
    rs.FaseProcedimiento,
    rs.Organisme,
    rs.Matricula AS rs_matricula,
    e.matricula AS exp_matricula,
    pe.matricula AS pub_matricula,
    pe.publicación AS pub_publicacion,
    rs.SujetoRecurso,
    c.tipodecliente,
    c.nif,
    c.nifempresa,
    c.Nombre,
    c.Apellido1,
    c.Apellido2,
    c.Nombrefiscal,
    c.poblacion AS MunicipioPoblacion
FROM Recursos.RecursosExp rs
LEFT JOIN clientes c ON rs.numclient = c.numerocliente
LEFT JOIN expedientes e ON rs.idExp = e.idexpediente
LEFT JOIN pubExp pe ON pe.Idpublic = e.Idpublic
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
    return str(value).strip() if value is not None else ""


def _norm_ascii_upper(value: Any) -> str:
    raw = _clean(value).upper()
    if not raw:
        return ""
    return "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")


def _extract_municipio_from_organisme(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""

    txt = _norm_ascii_upper(raw)
    if not txt:
        return ""

    txt = txt.replace("ORGANISME DE GESTIO TRIBUTARIA", " ")
    txt = txt.replace("DIPUTACIO DE BARCELONA", " ")
    txt = txt.replace("ORGT", " ")
    txt = re.sub(r"\s+", " ", txt).strip()

    patterns = (
        r"\b(?:AJUNTAMENT|AYUNTAMENT|AYUNTAMIENTO|AYTO\.?)\s+(?:DE|DEL|DE LA|DE LES|DE LOS|DE LAS|D['’])\s+(.+)",
        r"\b(?:AJUNTAMENT|AYUNTAMENT|AYUNTAMIENTO|AYTO\.?)\s+(.+)",
    )
    candidate = ""
    for pattern in patterns:
        match = re.search(pattern, txt)
        if match:
            candidate = match.group(1)
            break

    if not candidate:
        return ""

    candidate = re.split(r"\s+-\s+|\s+\|\s+|;|,", candidate, maxsplit=1)[0]
    candidate = re.split(
        r"\b(?:SEU ELECTRONICA|SEDE ELECTRONICA|ORGANISME|ORGANISMO|POLICIA|GUARDIA|TRAFIC|TRAFICO|MULTES|SANCIONS|SANCIONES)\b",
        candidate,
        maxsplit=1,
    )[0]
    candidate = re.sub(r"\s+", " ", candidate).strip(" -'")
    return candidate


def _normalize_plate_candidate(value: Any) -> str:
    raw = _clean(value)
    if not raw or raw in {".", "-", "N/A", "NA", "NULL", "NONE"}:
        return ""
    normalized = normalize_plate_with_fallback(raw)
    return "" if normalized == "." else normalized


def _resolve_matricula_from_row(row: dict[str, Any]) -> str:
    for key in ("rs_matricula", "exp_matricula", "pub_matricula", "matricula", "Matricula"):
        normalized = _normalize_plate_candidate(row.get(key))
        if normalized:
            return normalized

    pub_text = _clean(row.get("pub_publicacion")).upper()
    if pub_text:
        match = re.search(r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4,6}(?:[\s-]*[A-Z]{1,3})?)\b", pub_text)
        if match:
            normalized = _normalize_plate_candidate(match.group(1))
            if normalized:
                return normalized

    return _normalize_plate_candidate(os.getenv("DIPUTACIO_BCN_MATRICULA"))


def _set_client_docs_base_for_local_windows() -> None:
    os.environ["CLIENT_DOCS_BASE_PATH"] = HARDCODED_CLIENT_DOCS_BASE_PATH
    os.environ["CLIENT_DOCS_HOST_PATH"] = HARDCODED_CLIENT_DOCS_BASE_PATH


def _resolve_sqlserver_connection_string() -> str:
    env_conn = (os.getenv("SQLSERVER_CONN_STR") or "").strip()
    if env_conn:
        return env_conn
    if HARDCODED_SQLSERVER_CONNECTION_STRING.strip():
        return HARDCODED_SQLSERVER_CONNECTION_STRING
    return build_sqlserver_connection_string()


def fetch_resource_by_id(id_recurso: int) -> dict[str, Any]:
    conn_str = _resolve_sqlserver_connection_string()
    conn = pyodbc.connect(conn_str)
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


def _collect_docs_from_subject_folder(
    *,
    is_company: bool,
    sujeto_recurso: str,
    nombre: str,
    apellido1: str,
    apellido2: str,
) -> list[Path]:
    identity = ClientIdentity(
        is_company=is_company,
        sujeto_recurso=sujeto_recurso or None,
        empresa=sujeto_recurso if is_company else None,
        nombre=nombre if not is_company else None,
        apellido1=apellido1 if not is_company else None,
        apellido2=apellido2 if not is_company else None,
    )
    ruta_cliente = get_ruta_cliente_documentacion(identity, base_path=HARDCODED_CLIENT_DOCS_BASE_PATH)
    if not ruta_cliente.exists():
        return []

    candidates: list[Path] = []
    for p in ruta_cliente.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
            continue
        parent_upper = str(p.parent).upper()
        if "DOCUMENTA" not in parent_upper and "RECURSOS" not in parent_upper:
            continue
        candidates.append(p)

    def _score(path: Path) -> tuple[int, int]:
        name = path.name.upper()
        score = 0
        if "AUT" in name:
            score += 90
        if "DNI" in name or "NIE" in name or "CIF" in name:
            score += 70
        if "ALEG" in name or "RECUR" in name:
            score += 40
        if "DOCUMENTACION RECURSOS" in str(path.parent).upper():
            score += 30
        if path.suffix.lower() == ".pdf":
            score += 20
        return score, -len(str(path))

    candidates.sort(key=_score, reverse=True)
    return candidates[:10]


def build_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    expediente = _clean(row.get("Expedient"))
    expediente_digits = "".join(ch for ch in expediente if ch.isdigit())

    tipodecliente = _clean(row.get("tipodecliente"))
    is_company = tipodecliente == "2"
    nombre = _clean(row.get("Nombre"))
    apellido1 = _clean(row.get("Apellido1"))
    apellido2 = _clean(row.get("Apellido2"))
    nombrefiscal = _clean(row.get("Nombrefiscal"))
    sujeto_recurso = _clean(row.get("SujetoRecurso")) or nombrefiscal or " ".join(
        [p for p in [nombre, apellido1, apellido2] if p]
    ).strip()

    nif_persona = _clean(row.get("nif")).upper()
    nif_empresa = _clean(row.get("nifempresa")).upper()
    nif_interessat = nif_empresa if is_company else nif_persona
    if not nif_interessat:
        nif_interessat = nif_persona or nif_empresa or (os.getenv("DIPUTACIO_BCN_NIF_INTERESSAT") or "00000000T").strip().upper()

    default_phone = (os.getenv("DIPUTACIO_BCN_TELEFON") or "").strip() or get_default_contact_mobile()
    default_email = (os.getenv("DIPUTACIO_BCN_EMAIL") or "").strip() or get_default_contact_email()
    comentari = (
        os.getenv("DIPUTACIO_BCN_COMENTARI")
        or f"Presentacio documentacio expedient sancionador {expediente or 'N/A'}"
    ).strip()
    organisme_db = _clean(row.get("Organisme") or row.get("organisme") or row.get("Organismo"))
    municipio_organisme = _extract_municipio_from_organisme(organisme_db)
    municipio_db = municipio_organisme or _clean(row.get("MunicipioPoblacion") or row.get("poblacion") or row.get("municipio"))
    matricula = _resolve_matricula_from_row(row)
    fase_procedimiento = _clean(row.get("FaseProcedimiento") or row.get("fase_procedimiento"))
    asunto, expone, solicita = resolve_phase_texts(
        fase_procedimiento=fase_procedimiento,
        expediente=expediente,
        sujeto_recurso=sujeto_recurso,
    )

    return {
        "idRecurso": row.get("idRecurso"),
        "idExp": row.get("idExp"),
        "numclient": row.get("numclient"),
        "automatic_id": row.get("automatic_id"),
        "expediente": expediente,
        "exp_sancionador": (os.getenv("DIPUTACIO_BCN_EXP_SANCIONADOR") or expediente).strip(),
        "fase_procedimiento": fase_procedimiento,
        "matricula": matricula,
        "municipio": (os.getenv("DIPUTACIO_BCN_MUNICIPIO") or municipio_db or "").strip(),
        "organismo": organisme_db,
        "tipo_representado": "juridica" if is_company else "fisica",
        "tipodecliente": tipodecliente,
        "sujeto_recurso": sujeto_recurso,
        "nif": nif_persona,
        "nifempresa": nif_empresa,
        "nif_interessat": nif_interessat,
        "nom_cr4": nombre or (os.getenv("DIPUTACIO_BCN_NOM_CR4") or "Nom").strip(),
        "cognom1": apellido1 or (os.getenv("DIPUTACIO_BCN_COGNOM1") or "Cognom1").strip(),
        "cognom2": apellido2 or (os.getenv("DIPUTACIO_BCN_COGNOM2") or "Cognom2").strip(),
        "nom_juridica": nombrefiscal or sujeto_recurso or (os.getenv("DIPUTACIO_BCN_NOM_JURIDICA") or "Empresa SL").strip(),
        "asunto": asunto,
        "expone": expone,
        "solicita": solicita,
        "comentari": comentari,
        "telefon": default_phone,
        "email": default_email,
        "docs_base_path": HARDCODED_CLIENT_DOCS_BASE_PATH,
        "adjuntos": list(row.get("adjuntos") or []),
        "archivos": [],
        "doc_acreditativa": "",
        "doc_tramite": "",
        "trace_tag": f"id{row.get('idRecurso')}_{expediente_digits or 'sinexp'}",
    }


async def collect_client_docs_into_payload(payload: dict[str, Any]) -> list[str]:
    _set_client_docs_base_for_local_windows()

    conn_str = _resolve_sqlserver_connection_string()
    docs: list[Path] = []
    try:
        docs = await build_required_client_documents_for_payload(
            payload,
            sqlserver_conn_str=conn_str,
            strict=False,
        )
    except Exception:
        docs = []

    if not docs:
        docs = _collect_docs_from_subject_folder(
            is_company=(str(payload.get("tipodecliente") or "").strip() == "2"),
            sujeto_recurso=_clean(payload.get("sujeto_recurso")),
            nombre=_clean(payload.get("nom_cr4")),
            apellido1=_clean(payload.get("cognom1")),
            apellido2=_clean(payload.get("cognom2")),
        )

    out: list[str] = []
    for p in docs:
        txt = str(p).strip()
        if not txt:
            continue
        if Path(txt).exists():
            out.append(txt)
    return out


async def download_xvia_docs_into_payload(payload: dict[str, Any], *, strict: bool) -> list[str]:
    email = (os.getenv("XVIA_EMAIL") or "").strip()
    password = (os.getenv("XVIA_PASSWORD") or "").strip()
    if not email or not password:
        if strict:
            raise RuntimeError("Faltan XVIA_EMAIL/XVIA_PASSWORD para descargar recurso y adjuntos desde XVIA.")
        return []

    session = await create_authenticated_session(email, password)
    try:
        archivos = await download_document_and_attachments(payload=payload, auth_session=session)
    finally:
        await session.close()
    return [str(p) for p in archivos if p]


def _merge_unique_paths(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            value = str(raw or "").strip()
            if not value:
                continue
            key = os.path.normcase(os.path.normpath(value))
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
    return merged


def _normalize_path_for_runtime(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str((Path.cwd() / p).resolve())


def _pick_doc_acreditativa(client_docs: list[str], merged_docs: list[str]) -> str:
    if not client_docs:
        return merged_docs[0] if merged_docs else ""
    for doc in client_docs:
        name = Path(doc).name.upper()
        if "AUT" in name:
            return doc
    return client_docs[0]


def _pick_doc_tramite(xvia_docs: list[str], merged_docs: list[str]) -> str:
    if not xvia_docs:
        return merged_docs[0] if merged_docs else ""
    for doc in xvia_docs:
        name = Path(doc).name.upper()
        if "RECURSO EXP -" in name:
            return doc
    return xvia_docs[0]


async def enrich_documents(payload: dict[str, Any], *, strict: bool) -> dict[str, list[str]]:
    xvia_docs = await download_xvia_docs_into_payload(payload, strict=strict)
    client_docs = await collect_client_docs_into_payload(payload)

    if strict:
        if not xvia_docs:
            raise RuntimeError("No se han podido obtener documentos de XVIA (recurso + adjuntos).")
        if not client_docs:
            raise RuntimeError("No se ha podido obtener documentacion del cliente desde el mount.")

    merged = _merge_unique_paths(xvia_docs, client_docs)
    merged_norm = [_normalize_path_for_runtime(p) for p in merged]
    xvia_norm = [_normalize_path_for_runtime(p) for p in xvia_docs]
    client_norm = [_normalize_path_for_runtime(p) for p in client_docs]

    payload["archivos"] = merged_norm
    payload["doc_acreditativa"] = _normalize_path_for_runtime(_pick_doc_acreditativa(client_norm, merged_norm))
    payload["doc_tramite"] = _normalize_path_for_runtime(_pick_doc_tramite(xvia_norm, merged_norm))
    return {"xvia_docs": xvia_norm, "client_docs": client_norm, "merged_docs": merged_norm}


async def run_flow(payload: dict[str, Any]) -> dict[str, Any]:
    prev_ephemeral = os.getenv("XALOC_EPHEMERAL_PROFILE")
    prev_disable_keep = os.getenv("XALOC_DISABLE_KEEP_BROWSER_OPEN")
    prev_close_sleep = os.getenv("XALOC_CLOSE_SLEEP_SECONDS")
    try:
        # Evita perfiles persistentes corruptos (tu log muestra --restore-last-session/--restart).
        os.environ["XALOC_EPHEMERAL_PROFILE"] = "1"
        os.environ["XALOC_DISABLE_KEEP_BROWSER_OPEN"] = "1"
        # Mantener sesion abierta para inspeccion manual.
        os.environ["XALOC_CLOSE_SLEEP_SECONDS"] = "999"
        outcome = await execute_browser_flow(
            site_id="diputacio_bcn",
            protocol=None,
            payload=payload,
            archivos_para_subir=[],
        )
    finally:
        if prev_ephemeral is None:
            os.environ.pop("XALOC_EPHEMERAL_PROFILE", None)
        else:
            os.environ["XALOC_EPHEMERAL_PROFILE"] = prev_ephemeral
        if prev_disable_keep is None:
            os.environ.pop("XALOC_DISABLE_KEEP_BROWSER_OPEN", None)
        else:
            os.environ["XALOC_DISABLE_KEEP_BROWSER_OPEN"] = prev_disable_keep
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
    parser = argparse.ArgumentParser(description="Standalone smoke test for diputacio_bcn.")
    parser.add_argument("--id", type=int, required=True, help="idRecurso en SQL Server")
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local")
    args = parser.parse_args()

    row = fetch_resource_by_id(args.id)
    payload = build_payload_from_row(row)
    doc_stats = await enrich_documents(payload, strict=bool(args.run_flow))

    controller = DiputacioBcnController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / f"diputacio_bcn_raw_{args.id}.json"
    payload_path = out / f"diputacio_bcn_payload_{args.id}.json"
    mapped_path = out / f"diputacio_bcn_mapped_{args.id}.json"
    docs_path = out / f"diputacio_bcn_docs_{args.id}.json"
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
