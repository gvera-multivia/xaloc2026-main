from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import unicodedata
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pyodbc

from core.base_automation import BaseAutomation
from core.client_documentation import build_required_client_documents_for_payload
from core.client_paths import ClientIdentity, get_ruta_cliente_documentacion
from core.worker_execution.document_fetcher import download_document_and_attachments
from core.worker_execution.browser_executor import execute_browser_flow
from core.xvia_auth import create_authenticated_session
from sites.terrassa.controller import TerrassaController


HARDCODED_SQLSERVER_CONNECTION_STRING = (
    "DRIVER=SQL Server;"
    "SERVER=BD-SERVER;"
    "DATABASE=MULTIVIA;"
    "UID=Xvia-Grupo;"
    "PWD=Xvia_Grupo_Multivia_20180806;"
    "LoginTimeout=10"
)

HARDCODED_CLIENT_DOCS_BASE_PATH = r"\\SERVER-DOC\clientes"


SQL_BY_ID = """
SELECT TOP 1
    rs.idRecurso,
    rs.idExp,
    rs.numclient,
    rs.automatic_id,
    rs.Expedient,
    rs.FAlta,
    rs.FaseProcedimiento,
    rs.Matricula AS rs_matricula,
    rs.SujetoRecurso,
    c.tipodecliente AS c_tipo_cliente,
    c.nif AS c_nif,
    c.nifempresa AS c_nifempresa,
    c.Nombre AS c_nombre,
    c.Apellido1 AS c_apellido1,
    c.Apellido2 AS c_apellido2,
    c.Nombrefiscal AS c_nombrefiscal,
    e.matricula AS exp_matricula,
    pe.matricula AS pub_matricula,
    pe.[publicación] AS pub_publicacion
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


def _clean(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _norm(v: Any) -> str:
    txt = _clean(v).lower()
    if not txt:
        return ""
    return "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")


def _normalize_doc(v: Any) -> str:
    doc = _clean(v).upper()
    if doc.startswith("ES") and len(doc) > 2:
        doc = doc[2:]
    return re.sub(r"[^A-Z0-9]+", "", doc)


def _format_date_ddmmyyyy(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    raw = _clean(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.split("+")[0], fmt).strftime("%d/%m/%Y")
        except Exception:
            continue
    return raw


def _resolve_plate(row: dict[str, Any]) -> tuple[str, str]:
    for key, src in (
        ("rs_matricula", "Recursos.RecursosExp.Matricula"),
        ("exp_matricula", "expedientes.matricula"),
        ("pub_matricula", "pubExp.matricula"),
    ):
        value = _clean(row.get(key))
        if value:
            return re.sub(r"[^A-Z0-9]+", "", value.upper()), src

    txt = _clean(row.get("pub_publicacion")).upper()
    if txt:
        # Patrones típicos: 1234ABC, B1234AB, AB1234CD
        m = re.search(r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4}[\s-]*[A-Z]{1,2})\b", txt)
        if m:
            return re.sub(r"[^A-Z0-9]+", "", m.group(1).upper()), "pubExp.publicación(regex)"
    return "", ""


def _load_motivos() -> dict[str, dict[str, str]]:
    path = Path("config_motivos.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_texts_by_fase(*, fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str, str]:
    cfg = _load_motivos()
    fase = _norm(fase_raw)
    selected: dict[str, str] | None = None
    for key, value in cfg.items():
        if _norm(key) in fase:
            selected = value
            break

    if selected:
        asunto = _clean(selected.get("asunto")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto)
        expone = _clean(selected.get("expone")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto)
        solicita = _clean(selected.get("solicita")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto)
    else:
        asunto = f"Alegaciones expediente {expediente}"
        expone = f"Se presentan alegaciones en relación con el expediente {expediente}."
        solicita = f"Se solicita que se admita el escrito para el expediente {expediente}."

    alegaciones = f"ASUNTO: {asunto}\n\nEXPONE: {expone}"
    observaciones = f"SOLICITA: {solicita}"
    return asunto, alegaciones, observaciones


def _infer_document_type_value(document: str, is_company: bool) -> str:
    if is_company:
        if re.match(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$", document):
            return "7"  # CIF o entitats
        return "10"  # Doc. identificació jurídic estranger

    if re.match(r"^[XYZ]\d{7}[A-Z]$", document):
        return "3"  # NIE
    if re.match(r"^[0-9]{8}[A-Z]$", document):
        return "1"  # DNI / NIF
    return "2"  # Passaport/identificació estranger


def _set_client_docs_base_for_local_windows() -> None:
    os.environ["CLIENT_DOCS_BASE_PATH"] = HARDCODED_CLIENT_DOCS_BASE_PATH
    os.environ["CLIENT_DOCS_HOST_PATH"] = HARDCODED_CLIENT_DOCS_BASE_PATH


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
    return candidates[:6]


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


async def build_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    _set_client_docs_base_for_local_windows()

    tipo_cliente_raw = _clean(row.get("c_tipo_cliente"))
    is_company = tipo_cliente_raw == "2"

    doc = _normalize_doc(row.get("c_nifempresa") if is_company else row.get("c_nif"))

    if is_company:
        nombre = _clean(row.get("c_nombrefiscal") or row.get("SujetoRecurso"))
        apellido1 = ""
        apellido2 = ""
    else:
        nombre = _clean(row.get("c_nombre") or row.get("SujetoRecurso"))
        apellido1 = _clean(row.get("c_apellido1"))
        apellido2 = _clean(row.get("c_apellido2"))

    expediente = _clean(row.get("Expedient"))
    fecha_infraccion = _format_date_ddmmyyyy(row.get("FAlta"))
    matricula, matricula_source = _resolve_plate(row)
    if not matricula:
        raise ValueError("No se pudo inferir la matrícula (RecursosExp/expedientes/pubExp/publicación).")

    sujeto = _clean(row.get("SujetoRecurso") or nombre)
    asunto, alegaciones, observaciones = _build_texts_by_fase(
        fase_raw=_clean(row.get("FaseProcedimiento")),
        expediente=expediente,
        sujeto=sujeto,
    )

    base_payload: dict[str, Any] = {
        "idRecurso": row.get("idRecurso"),
        "idExp": row.get("idExp"),
        "numclient": row.get("numclient"),
        "expediente": expediente,
        "is_company": is_company,
        "document_type_value": _infer_document_type_value(doc, is_company),
        "document_number": doc,
        "nombre": nombre,
        "apellido1": apellido1,
        "apellido2": apellido2,
        "fecha_infraccion": fecha_infraccion,
        "matricula": matricula,
        "matricula_source": matricula_source,
        "marca": "Otros",
        "asunto": asunto,
        "alegaciones": alegaciones,
        "observaciones": observaciones,
        "fase_procedimiento": _clean(row.get("FaseProcedimiento")),
        "sujeto_recurso": sujeto,
        "docs_base_path": HARDCODED_CLIENT_DOCS_BASE_PATH,
        "adjuntos": list(row.get("adjuntos") or []),
        "archivos": [],
        "documentos": [],
    }

    try:
        files = await build_required_client_documents_for_payload(
            base_payload,
            sqlserver_conn_str=HARDCODED_SQLSERVER_CONNECTION_STRING,
            strict=False,
        )
    except Exception:
        files = []

    if not files:
        files = _collect_docs_from_subject_folder(
            is_company=is_company,
            sujeto_recurso=sujeto,
            nombre=nombre,
            apellido1=apellido1,
            apellido2=apellido2,
        )

    archivos = [str(p) for p in files if str(p).strip()]
    documentos = [
        {
            "fitxer": p,
            "descripcio": Path(p).stem[:70] or "Documento",
            "tipus": "Al·legació",
        }
        for p in archivos
    ]

    base_payload["archivos"] = archivos
    base_payload["documentos"] = documentos
    return base_payload


def _build_document_entries(paths: list[str]) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for item in paths:
        p = Path(str(item))
        name_u = p.name.upper()
        if "AUT" in name_u:
            desc = "Autorizacion"
            tipus = "Autorització"
        elif "DNI" in name_u or "NIE" in name_u or "CIF" in name_u:
            desc = "Documento identidad"
            tipus = "Document Nacional Identitat - NIF"
        else:
            desc = p.stem[:70] or "Alegacion"
            tipus = "Al·legació"
        docs.append({"fitxer": str(p), "descripcio": desc, "tipus": tipus})
    return docs


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

    paths = [str(p) for p in archivos if p]
    if paths:
        payload["archivos"] = paths
        payload["documentos"] = _build_document_entries(paths)


async def run_flow(payload: dict[str, Any]) -> dict[str, Any]:
    outcome = await execute_browser_flow(
        site_id="terrassa",
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


async def close_shared_browser_resources() -> None:
    ctx = BaseAutomation._shared_context
    pw = BaseAutomation._shared_playwright
    if ctx is not None:
        try:
            await ctx.close()
        except Exception:
            pass
        BaseAutomation._shared_context = None
        BaseAutomation._shared_home_page = None
    if pw is not None:
        try:
            await pw.stop()
        except Exception:
            pass
        BaseAutomation._shared_playwright = None
        BaseAutomation._shared_fingerprint = None


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Lee SQL por idRecurso y genera payload Terrassa.")
    parser.add_argument("--id", type=int, required=True, help="idRecurso en SQL Server")
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local")
    args = parser.parse_args()

    row = fetch_resource_by_id(args.id)
    payload = await build_payload_from_row(row)
    await download_xvia_docs_into_payload(payload, strict=bool(args.run_flow))

    controller = TerrassaController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / f"terrassa_raw_{args.id}.json"
    payload_path = out / f"terrassa_payload_{args.id}.json"
    mapped_path = out / f"terrassa_mapped_{args.id}.json"
    raw_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mapped_path.write_text(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] SQL raw: {raw_path}")
    print(f"[OK] payload: {payload_path}")
    print(f"[OK] mapped target: {mapped_path}")

    if args.dump_only and not args.run_flow:
        return

    if args.run_flow:
        result = await run_flow(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

        # Safety net: close any leftover browser resources to avoid pipe errors on exit
        if BaseAutomation._shared_playwright is not None:
            await close_shared_browser_resources()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
