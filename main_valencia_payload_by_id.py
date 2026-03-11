from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyodbc

from core.client_documentation import build_required_client_documents_for_payload
from core.client_paths import ClientIdentity, get_ruta_cliente_documentacion
from core.worker_execution.document_fetcher import download_document_and_attachments
from core.xvia_auth import create_authenticated_session
from sites.valencia.automation import ValenciaAutomation
from sites.valencia.controller import ValenciaController

logger = logging.getLogger("xaloc_automation.valencia")

HARDCODED_SQLSERVER_CONNECTION_STRING = (
    "DRIVER=SQL Server;"
    "SERVER=BD-SERVER;"
    "DATABASE=MULTIVIA;"
    "UID=Xvia-Grupo;"
    "PWD=Xvia_Grupo_Multivia_20180806;"
    "LoginTimeout=10"
)

HARDCODED_CLIENT_DOCS_BASE_PATH = r"\\SERVER-DOC\clientes"
# Override manual para pruebas locales de scraping (None para desactivar).
FORCE_FASE_FOR_TEST: str | None = None


SQL_BY_ID = """
SELECT TOP 1
    r.idRecurso,
    r.IdExp,
    r.Expedient,
    r.Matricula,
    r.Organisme,
    r.numclient,
    r.IdPublic,
    r.TExp,
    r.ConducNom,
    r.Conducdni,
    r.ConducCodpost,
    r.ConducAdr,
    r.FaseProcedimiento,
    r.SujetoRecurso,
    r.automatic_id,
    e.matricula AS Matricula2,
    c.tipodecliente,
    c.Nombre,
    c.Apellido1,
    c.Apellido2,
    c.Nombrefiscal,
    c.nif,
    c.nifempresa,
    p.matricula AS Matricula3,
    d.ConducNom AS ConducNom2,
    d.ConducDni AS Conducdni2,
    d.ConducCodpost AS ConducCodpost2,
    d.ConducAdr AS ConducAdr2
FROM Recursos.RecursosExp r
LEFT JOIN expedientes e ON r.IdExp = e.idexpediente
LEFT JOIN clientes c ON r.numclient = c.numerocliente
LEFT JOIN pubexp p ON r.IdPublic = p.idpublic
LEFT JOIN DadesIdentif d ON r.IdExp = d.idExp
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

_MOTIVOS_CACHE: dict[str, dict[str, Any]] | None = None


def _clean(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _norm(v: Any) -> str:
    txt = _clean(v).lower()
    if not txt:
        return ""
    txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
    return " ".join(txt.split())


def _sanitize_document(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", _clean(v).upper())


def _infer_tramite(fase_raw: str) -> tuple[str, str]:
    fase = _norm(fase_raw)
    if "identific" in fase:
        return "identificacion_conductor", "MU.DE.50"
    if "denuncia" in fase or "propuesta" in fase:
        return "alegaciones_denuncia_transito", "MU.DE.30"
    if "sancion" in fase or "embargo" in fase or "apremio" in fase:
        return "recurso_reposicion", "MU.SA.40"
    return "alegaciones_denuncia_transito", "MU.DE.30"


def _load_motivos() -> dict[str, dict[str, Any]]:
    global _MOTIVOS_CACHE
    if _MOTIVOS_CACHE is not None:
        return _MOTIVOS_CACHE
    config_path = Path(__file__).resolve().parent / "config_motivos.json"
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        _MOTIVOS_CACHE = {_norm(k): v for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        _MOTIVOS_CACHE = {}
    return _MOTIVOS_CACHE


def _build_texts(expediente: str, fase: str, sujeto_recurso: str) -> tuple[str, str]:
    motivo = _load_motivos().get(_norm(fase))
    if motivo:
        context = {"expediente": expediente, "sujeto_recurso": sujeto_recurso}
        expone_tpl = _clean(motivo.get("expone"))
        solicita_tpl = _clean(motivo.get("solicita"))
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

    fase_txt = _clean(fase) or "tramite"
    expone = f"Se presenta escrito relacionado con el expediente {expediente} en fase {fase_txt}."
    solicita = f"Se solicita la admision y tramitacion del expediente {expediente}."
    return expone, solicita


def _pick_conductor_fields(row: dict[str, Any]) -> tuple[str, str, str, str]:
    texp = int(row.get("TExp") or 0)
    primary = (
        _clean(row.get("ConducNom")),
        _sanitize_document(row.get("Conducdni")),
        _clean(row.get("ConducCodpost")),
        _clean(row.get("ConducAdr")),
    )
    secondary = (
        _clean(row.get("ConducNom2")),
        _sanitize_document(row.get("Conducdni2")),
        _clean(row.get("ConducCodpost2")),
        _clean(row.get("ConducAdr2")),
    )

    def _merge(preferred: tuple[str, str, str, str], fallback: tuple[str, str, str, str]) -> tuple[str, str, str, str]:
        return tuple(preferred[i] or fallback[i] for i in range(4))  # type: ignore[return-value]

    if texp in (3, 4):
        return _merge(secondary, primary)
    return _merge(primary, secondary)


def _env_docs() -> list[str]:
    raw = _clean(os.getenv("VALENCIA_DOC_PATHS"))
    if not raw:
        return []
    return [p.strip() for p in raw.split(";") if p.strip()]


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

    expediente = _clean(row.get("Expedient"))
    fase = _clean(row.get("FaseProcedimiento"))
    tramite_tipo, tramite_code = _infer_tramite(fase)
    sujeto = _clean(row.get("SujetoRecurso")) or _clean(row.get("Nombrefiscal")) or _clean(row.get("Nombre"))
    expone, solicita = _build_texts(expediente, fase, sujeto)
    conduc_nom, conduc_dni, conduc_cp, conduc_adr = _pick_conductor_fields(row)
    tipodecliente = _clean(row.get("tipodecliente"))
    is_company = tipodecliente == "2"

    payload = {
        "idRecurso": row.get("idRecurso"),
        "idExp": row.get("IdExp"),
        "numclient": row.get("numclient"),
        "expediente": expediente,
        "fase_procedimiento": fase,
        "sujeto_recurso": sujeto,
        "tramite_tipo": tramite_tipo,
        "tramite_code": tramite_code,
        "tipodecliente": tipodecliente,
        "nif": _sanitize_document(row.get("nif")),
        "nifempresa": _sanitize_document(row.get("nifempresa")),
        "nombre": _clean(row.get("Nombre") or row.get("SujetoRecurso")),
        "apellido1": _clean(row.get("Apellido1")),
        "apellido2": _clean(row.get("Apellido2")),
        "nombrefiscal": _clean(row.get("Nombrefiscal") or row.get("SujetoRecurso")),
        "texp": int(row.get("TExp") or 0),
        "matricula": _clean(row.get("Matricula")),
        "matricula2": _clean(row.get("Matricula2")),
        "matricula3": _clean(row.get("Matricula3")),
        "conduc_nom": conduc_nom,
        "conduc_dni": conduc_dni,
        "conduc_codpost": conduc_cp,
        "conduc_adr": conduc_adr,
        "expone": expone,
        "solicita": solicita,
        "adjuntos": list(row.get("adjuntos") or []),
        "docs_base_path": HARDCODED_CLIENT_DOCS_BASE_PATH,
        "archivos": [],
    }

    # 1) Archivos manuales por variable de entorno (override local)
    env_docs = [p for p in _env_docs() if p]
    if env_docs:
        payload["archivos"] = env_docs

    # 2) Documentacion cliente por ruta compartida
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
                sujeto_recurso=sujeto,
                nombre=_clean(row.get("Nombre")),
                apellido1=_clean(row.get("Apellido1")),
                apellido2=_clean(row.get("Apellido2")),
            )
        payload["archivos"] = [str(p) for p in files if str(p).strip()]

    return payload


async def run_flow(payload: dict[str, Any]) -> dict[str, Any]:
    files = [Path(str(p)) for p in (payload.get("archivos") or []) if str(p).strip()]
    logger.info(
        "valencia.run_flow payload idRecurso=%s idExp=%s expediente=%s tipodecliente=%s nif=%s conduc_dni=%s archivos=%s",
        _clean(payload.get("idRecurso")),
        _clean(payload.get("idExp")),
        _clean(payload.get("expediente")),
        _clean(payload.get("tipodecliente")),
        _clean(payload.get("nif")),
        _clean(payload.get("conduc_dni")),
        len(files),
    )
    controller = ValenciaController()
    headless = os.getenv("XALOC_HEADLESS") == "1"
    config = controller.create_config(headless=headless)
    config.navegador.perfil_path = Path("profiles/worker").absolute()

    mapped = controller.map_data(payload)
    mapped["archivos"] = files
    mapped["headless"] = headless
    datos = controller.create_target(**mapped)

    logger.info(
        "valencia.run_flow direct target idRecurso=%s expediente=%s tipodecliente=%s nif=%s conduc_dni=%s archivos=%s",
        _clean(getattr(datos, "idRecurso", "")),
        _clean(getattr(datos, "expediente", "")),
        _clean(getattr(datos, "tipodecliente", "")),
        _clean(getattr(datos, "nif", "")),
        _clean(getattr(datos, "conduc_dni", "")),
        len(getattr(datos, "archivos_para_subir", []) or []),
    )

    try:
        async with ValenciaAutomation(config) as bot:
            screenshot = await bot.ejecutar_flujo_completo(datos)
        return {
            "success": True,
            "error": None,
            "screenshot": screenshot,
            "payload_updates": {},
        }
    except Exception as exc:
        logger.exception("valencia.run_flow direct ERROR: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "screenshot": None,
            "payload_updates": {},
        }


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

    if not archivos:
        return
    # Merge sin duplicados, priorizando el recurso principal descargado
    merged: list[str] = []
    seen: set[str] = set()
    for p in [str(x) for x in archivos] + [str(x) for x in (payload.get("archivos") or [])]:
        key = os.path.normcase(os.path.normpath(str(p)))
        if not p or key in seen:
            continue
        seen.add(key)
        merged.append(str(p))
    payload["archivos"] = merged


def main() -> None:
    log_path = Path("logs/valencia.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    has_file_handler = any(
        isinstance(h, logging.FileHandler) and Path(getattr(h, "baseFilename", "")).resolve() == log_path.resolve()
        for h in logger.handlers
    )
    if not has_file_handler:
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    stream_logger = logging.getLogger("main.valencia.payload_by_id.stdout")
    if not stream_logger.handlers:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        stream_logger.addHandler(sh)
    stream_logger.setLevel(logging.INFO)
    stream_logger.propagate = False

    logger.info("valencia.main START")
    parser = argparse.ArgumentParser(description="Lee SQL por idRecurso y genera payload Valencia.")
    parser.add_argument("--id", type=int, required=True, help="idRecurso en SQL Server")
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local")
    args = parser.parse_args()

    row = fetch_resource_by_id(args.id)
    if FORCE_FASE_FOR_TEST:
        row["FaseProcedimiento"] = FORCE_FASE_FOR_TEST
        logger.info("valencia.main TEST override fase_procedimiento=%s", FORCE_FASE_FOR_TEST)
    logger.info("valencia.main SQL row loaded idRecurso=%s", _clean(row.get("idRecurso")))
    payload = asyncio.run(build_payload_from_row(row))
    logger.info(
        "valencia.main payload built idRecurso=%s expediente=%s tipodecliente=%s nif=%s conduc_dni=%s archivos=%s",
        _clean(payload.get("idRecurso")),
        _clean(payload.get("expediente")),
        _clean(payload.get("tipodecliente")),
        _clean(payload.get("nif")),
        _clean(payload.get("conduc_dni")),
        len(payload.get("archivos") or []),
    )
    asyncio.run(download_xvia_docs_into_payload(payload, strict=bool(args.run_flow)))
    logger.info("valencia.main xvia/docs merge done archivos=%s", len(payload.get("archivos") or []))

    controller = ValenciaController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)
    logger.info(
        "valencia.main target created idRecurso=%s expediente=%s nif=%s conduc_dni=%s",
        _clean(getattr(target, "idRecurso", "")),
        _clean(getattr(target, "expediente", "")),
        _clean(getattr(target, "nif", "")),
        _clean(getattr(target, "conduc_dni", "")),
    )

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / f"valencia_raw_{args.id}.json"
    payload_path = out / f"valencia_payload_{args.id}.json"
    mapped_path = out / f"valencia_mapped_{args.id}.json"
    raw_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mapped_path.write_text(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] SQL raw: {raw_path}")
    print(f"[OK] payload: {payload_path}")
    print(f"[OK] mapped target: {mapped_path}")

    if args.dump_only and not args.run_flow:
        return

    if args.run_flow:
        logger.info("valencia.main run_flow START")
        result = asyncio.run(run_flow(payload))
        logger.info("valencia.main run_flow END success=%s error=%s", result.get("success"), result.get("error"))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
