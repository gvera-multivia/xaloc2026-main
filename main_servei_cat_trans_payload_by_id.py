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
from core.worker_execution.browser_executor import execute_browser_flow
from sites.servei_cat_trans.controller import ServeiCatTransController


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
    r.idRecurso,
    r.idExp AS IdExp,
    r.numclient,
    r.automatic_id,
    r.Expedient,
    r.FaseProcedimiento,
    r.SujetoRecurso,
    r.ConducNom,
    r.ConducDni,
    r.ConducCodpost,
    r.ConducAdr,
    c.tipodecliente,
    c.Nombre,
    c.Apellido1,
    c.Apellido2,
    c.Nombrefiscal,
    c.nif,
    c.nifempresa
FROM Recursos.RecursosExp r
LEFT JOIN clientes c ON r.numclient = c.numerocliente
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


def _clean(v: Any) -> str:
    return str(v or "").strip()


def _norm(v: Any) -> str:
    txt = _clean(v).lower()
    if not txt:
        return ""
    txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", txt).strip()


def _sanitize_document(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", _clean(v).upper())


def _split_expediente(expediente: str) -> tuple[str, str, str]:
    raw = _clean(expediente)
    if not raw:
        return "", "", ""
    match = re.search(r"(\d{2})[/-](\d{7,10})-(\d{1,2})", raw)
    if match:
        return match.group(1), match.group(2), match.group(3)
    digits = re.findall(r"\d+", raw)
    if len(digits) >= 3:
        return digits[0][-2:], digits[1], digits[2]
    return "", "", ""


def _infer_tipo_escrito(fase: str) -> str:
    norm = _norm(fase)
    if "extraordin" in norm and "revis" in norm:
        return "revision"
    if "reposicion" in norm:
        return "reposicion"
    return "alegaciones"


def _load_motivos() -> dict[str, dict[str, Any]]:
    cfg_path = Path("config_motivos.json")
    if not cfg_path.exists():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {_norm(key): value for key, value in raw.items() if isinstance(value, dict)}


def _build_texts(expediente: str, fase: str, sujeto_recurso: str) -> tuple[str, str]:
    cfg = _load_motivos().get(_norm(fase))
    if cfg:
        context = {
            "expediente": expediente,
            "sujeto_recurso": sujeto_recurso,
        }
        expone_tpl = _clean(cfg.get("expone"))
        solicita_tpl = _clean(cfg.get("solicita"))
        try:
            expone = expone_tpl.format(**context) if expone_tpl else ""
        except Exception:
            expone = expone_tpl
        try:
            solicita = solicita_tpl.format(**context) if solicita_tpl else ""
        except Exception:
            solicita = solicita_tpl
        if expone and solicita:
            return expone, solicita

    expone = f"Se presenta escrito relacionado con el expediente {expediente}."
    solicita = f"Se solicita la admision y tramitacion del expediente {expediente}."
    return expone, solicita


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
            score += 100
        if "DNI" in name or "NIE" in name or "CIF" in name:
            score += 80
        if "ALEG" in name or "RECUR" in name:
            score += 50
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
        attachments: list[dict[str, Any]] = []
        if automatic_id not in (None, ""):
            cur.execute(SQL_ATTACHMENTS_BY_AUTOMATIC_ID, automatic_id)
            rows = cur.fetchall()
            att_cols = [c[0] for c in cur.description]
            for item_row in rows:
                item = dict(zip(att_cols, item_row))
                att_id = item.get("adjunto_id")
                if att_id in (None, ""):
                    continue
                filename = _clean(item.get("adjunto_filename")) or f"adjunto_{att_id}.pdf"
                attachments.append(
                    {
                        "id": int(att_id),
                        "filename": filename,
                        "url": (
                            "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/"
                            f"servicio/recursos/expedientes/pdf-adjuntos/{att_id}"
                        ),
                    }
                )
        data["adjuntos"] = attachments
        return data
    finally:
        conn.close()


async def build_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    expediente = _clean(row.get("Expedient"))
    servicio, expediente_num, digito_control = _split_expediente(expediente)
    fase = _clean(row.get("FaseProcedimiento"))
    tipodecliente = _clean(row.get("tipodecliente"))
    is_company = tipodecliente == "2" or bool(_clean(row.get("nifempresa")))
    tipo_persona = "juridica" if is_company else "fisica"

    nombre = _clean(row.get("Nombre") or row.get("SujetoRecurso"))
    apellido1 = _clean(row.get("Apellido1"))
    apellido2 = _clean(row.get("Apellido2"))
    razon_social = _clean(row.get("Nombrefiscal") or row.get("SujetoRecurso"))
    nif_persona = _sanitize_document(row.get("nif"))
    nif_empresa = _sanitize_document(row.get("nifempresa"))
    sujeto_recurso = _clean(row.get("SujetoRecurso") or razon_social or nombre)
    expone, solicita = _build_texts(expediente, fase, sujeto_recurso)

    payload: dict[str, Any] = {
        "idRecurso": row.get("idRecurso"),
        "idExp": row.get("IdExp"),
        "numclient": row.get("numclient"),
        "expediente": expediente,
        "servicio_territorial": servicio,
        "expediente_numero": expediente_num,
        "digito_control": digito_control,
        "fase_procedimiento": fase,
        "tipo_escrito": _infer_tipo_escrito(fase),
        "tipodecliente": tipodecliente,
        "tipo_persona": tipo_persona,
        "sujeto_recurso": sujeto_recurso,
        "nombre": nombre,
        "apellido1": apellido1,
        "apellido2": apellido2,
        "razon_social": razon_social,
        "nif": nif_persona,
        "nifempresa": nif_empresa,
        "email": get_default_contact_email(),
        "telefono_movil": get_default_contact_mobile(),
        "direccion_nombre_via": _clean(row.get("ConducAdr")),
        "direccion_cp": _clean(row.get("ConducCodpost")),
        "codigo_personal": _clean(row.get("idRecurso")),
        "expongo": expone,
        "solicito": solicita,
        "adjuntos": list(row.get("adjuntos") or []),
        "docs_base_path": HARDCODED_CLIENT_DOCS_BASE_PATH,
        "archivos": [],
    }

    manual_docs_raw = _clean(os.getenv("SERVEI_CAT_TRANS_DOC_PATHS"))
    if manual_docs_raw:
        payload["archivos"] = [item.strip() for item in manual_docs_raw.split(";") if item.strip()]

    if not payload["archivos"]:
        try:
            files = await build_required_client_documents_for_payload(
                payload,
                sqlserver_conn_str=HARDCODED_SQLSERVER_CONNECTION_STRING,
                strict=False,
            )
        except Exception:
            files = []

        if not files:
            files = _collect_docs_from_subject_folder(
                is_company=is_company,
                sujeto_recurso=sujeto_recurso,
                nombre=nombre,
                apellido1=apellido1,
                apellido2=apellido2,
            )
        payload["archivos"] = [str(path) for path in files if str(path).strip()]

    if tipo_persona == "juridica" and payload["archivos"]:
        payload["acreditacion_path"] = payload["archivos"][-1]

    return payload


async def run_flow(payload: dict[str, Any]) -> dict[str, Any]:
    archivos = [Path(str(path)) for path in (payload.get("archivos") or []) if str(path).strip()]
    outcome = await execute_browser_flow(
        site_id="servei_cat_trans",
        protocol=None,
        payload=payload,
        archivos_para_subir=archivos,
    )
    return {
        "success": bool(outcome.success),
        "error": outcome.error,
        "screenshot": outcome.screenshot,
        "payload_updates": outcome.payload_updates,
    }


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Standalone smoke test for servei_cat_trans.")
    parser.add_argument("--id", type=int, required=True, help="idRecurso en SQL Server")
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local")
    args = parser.parse_args()

    row = fetch_resource_by_id(args.id)
    payload = await build_payload_from_row(row)

    controller = ServeiCatTransController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / "servei_cat_trans_raw_{}.json".format(args.id)
    payload_path = out / "servei_cat_trans_payload_{}.json".format(args.id)
    mapped_path = out / "servei_cat_trans_mapped_{}.json".format(args.id)
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


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
