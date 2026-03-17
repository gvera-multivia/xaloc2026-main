from __future__ import annotations

import logging
import os
import shutil
import traceback
import unicodedata
from pathlib import Path
from typing import Optional

import aiohttp
import pyodbc

from core.client_documentation import RequiredClientDocumentsError
from core.client_docs_service import get_required_client_documents
from core.contact_defaults import get_default_contact_email
from core.pdf_bundle import bundle_documents_to_single_pdf_for_palma
from core.sqlserver_utils import build_sqlserver_connection_string
from core.validation.validators import normalize_plate_with_fallback
from core.xvia_auth import mark_resource_complete
from .browser_executor import execute_browser_flow
from .document_fetcher import download_document_and_attachments
from .models import ProcessOutcome
from .runner_client import execute_via_runner_service, use_remote_playwright_runner

logger = logging.getLogger("worker.task_orchestrator")
TMP_ROOT = Path("tmp")
DEFAULT_CONTACT_EMAIL = get_default_contact_email()


def _is_placeholder_text(value: object) -> bool:
    text = str(value or "").strip().upper()
    if not text:
        return True
    return text in {".", "-", "N/A", "NA", "NULL", "NONE", "S/N", "SN"}


def _flatten_embedded_payload(payload: dict) -> None:
    """
    Algunos productores legacy envian un payload dentro de `payload`.
    Si llega asi, promovemos campos vacios del nivel raiz desde el embebido.
    """
    nested = payload.get("payload")
    if not isinstance(nested, dict) or not nested:
        return
    for key, value in nested.items():
        if payload.get(key) in (None, "", []):
            payload[key] = value


def _resolve_valencia_matricula(payload: dict) -> str:
    for key in ("matricula", "matricula2", "matricula3", "plate_number"):
        normalized = normalize_plate_with_fallback(payload.get(key))
        if normalized != ".":
            payload["matricula"] = normalized
            payload["plate_number"] = normalized
            return normalized
    payload["matricula"] = "."
    payload["plate_number"] = "."
    return "."


def _payload_has_identity_fields(payload: dict) -> bool:
    if str(payload.get("empresa") or payload.get("cliente_razon_social") or "").strip():
        return True
    nombre = str(payload.get("cliente_nombre") or payload.get("name") or "").strip()
    ap1 = str(payload.get("cliente_apellido1") or payload.get("apellido1") or "").strip()
    return bool(nombre and ap1)


def _to_int_like(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        pass
    try:
        as_float = float(str(value).strip())
        if as_float.is_integer():
            return int(as_float)
    except Exception:
        pass
    return None


def _backfill_identity_from_sqlserver(payload: dict) -> None:
    """
    Fallback defensivo:
    Si el payload llega recortado desde cola (sin identidad cliente),
    recuperar campos base desde SQL por idRecurso.
    """
    rid = _to_int_like(payload.get("idRecurso"))
    if rid is None:
        rid = _to_int_like(payload.get("external_resource_id"))
    if rid is None:
        rid = _to_int_like(payload.get("resource_id"))
    if rid is None:
        return

    payload["idRecurso"] = rid

    if _payload_has_identity_fields(payload) and payload.get("numclient") is not None:
        return

    with pyodbc.connect(build_sqlserver_connection_string(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT TOP 1
                    rs.idRecurso,
                    rs.idExp,
                    rs.numclient,
                    rs.Expedient,
                    rs.SujetoRecurso,
                    rs.FaseProcedimiento,
                    rs.Empresa,
                    rs.cif,
                    e.matricula,
                    c.nif,
                    c.nifempresa,
                    c.tipodecliente,
                    c.Nombre,
                    c.Apellido1,
                    c.Apellido2,
                    c.Nombrefiscal,
                    c.provincia,
                    c.poblacion,
                    c.calle,
                    c.numero,
                    c.piso,
                    c.puerta,
                    c.Cpostal,
                    c.email,
                    c.telefono1,
                    c.telefono2,
                    c.movil
                FROM Recursos.RecursosExp rs
                LEFT JOIN clientes c ON rs.numclient = c.numerocliente
                LEFT JOIN expedientes e ON rs.idExp = e.idexpediente
                WHERE rs.idRecurso = ?
                """,
                (rid,),
            )
            row = cur.fetchone()
            if not row:
                return

            colnames = [d[0] for d in cur.description]
            data = dict(zip(colnames, row))

        defaults = {
            "idRecurso": data.get("idRecurso"),
            "idExp": data.get("idExp"),
            "numclient": data.get("numclient"),
            "expediente": data.get("Expedient"),
            "Expedient": data.get("Expedient"),
            "expediente_num": data.get("Expedient"),
            "num_expediente": data.get("Expedient"),
            "denuncia_num": data.get("Expedient"),
            "num_denuncia": data.get("Expedient"),
            "matricula": data.get("matricula"),
            "plate_number": data.get("matricula"),
            "SujetoRecurso": data.get("SujetoRecurso"),
            "sujeto_recurso": data.get("SujetoRecurso"),
            "fase_procedimiento": data.get("FaseProcedimiento"),
            "FaseProcedimiento": data.get("FaseProcedimiento"),
            "empresa": data.get("Empresa"),
            "cif": data.get("cif"),
            "cliente_nif": data.get("nif"),
            "cliente_nif_empresa": data.get("nifempresa"),
            "cliente_tipo": data.get("tipodecliente"),
            "cliente_nombre": data.get("Nombre"),
            "cliente_apellido1": data.get("Apellido1"),
            "cliente_apellido2": data.get("Apellido2"),
            "cliente_razon_social": data.get("Nombrefiscal"),
            "cliente_provincia": data.get("provincia"),
            "cliente_municipio": data.get("poblacion"),
            "cliente_domicilio": data.get("calle"),
            "cliente_numero": data.get("numero"),
            "cliente_planta": data.get("piso"),
            "cliente_puerta": data.get("puerta"),
            "cliente_cp": data.get("Cpostal"),
            "cliente_email": data.get("email"),
            "email": data.get("email"),
            "user_email": data.get("email"),
            "cliente_tel1": data.get("telefono1"),
            "cliente_tel2": data.get("telefono2"),
            "cliente_movil": data.get("movil"),
            "name": data.get("Nombre"),
            "apellido1": data.get("Apellido1"),
            "apellido2": data.get("Apellido2"),
            "razon_social": data.get("Nombrefiscal"),
        }
        for key, value in defaults.items():
            if payload.get(key) in (None, "", []):
                payload[key] = value

        # Fallback operativo: muchos sites (xaloc/base/palma) usan correo fijo corporativo.
        if str(payload.get("email") or "").strip() == "":
            payload["email"] = str(payload.get("user_email") or payload.get("cliente_email") or DEFAULT_CONTACT_EMAIL)
        if str(payload.get("user_email") or "").strip() == "":
            payload["user_email"] = str(payload.get("email") or DEFAULT_CONTACT_EMAIL)

def _normalize_site_minimum_payload(site_id: str, payload: dict) -> None:
    site = str(site_id or "").strip().lower()
    if site != "xaloc_girona":
        return

    def _pick(*keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def _set_if_empty(key: str, value: str) -> None:
        if payload.get(key) in (None, "", []):
            payload[key] = value

    # Correo de contacto
    email = _pick("email", "user_email", "cliente_email")
    if not email:
        email = DEFAULT_CONTACT_EMAIL
    _set_if_empty("email", email)
    _set_if_empty("user_email", email)

    # Expediente / denuncia (Xaloc los trata de forma equivalente en P1)
    expediente = _pick("num_expediente", "expediente_num", "expediente", "Expedient", "denuncia_num", "num_denuncia")
    if expediente:
        _set_if_empty("num_expediente", expediente)
        _set_if_empty("expediente_num", expediente)
        _set_if_empty("num_denuncia", expediente)
        _set_if_empty("denuncia_num", expediente)

    # Matricula
    matricula = _pick("matricula", "plate_number", "rs_matricula")
    if not matricula:
        matricula = "."
    _set_if_empty("matricula", matricula)
    _set_if_empty("plate_number", matricula)

    # Motivos
    motivos = _pick("motivos", "body", "texto_recurso")
    if not motivos and expediente:
        motivos = f"ASUNTO: Recurso expediente {expediente}\n\nEXPONE: ...\n\nSOLICITA: ..."
    if motivos:
        _set_if_empty("motivos", motivos)


def _validate_valencia_preconditions(payload: dict) -> Optional[str]:
    def _pick(*keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def _norm(value: object) -> str:
        raw = str(value or "").strip().upper()
        if not raw:
            return ""
        return "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")

    expediente = str(
        _pick("expediente", "Expedient", "expediente_num", "num_expediente", "denuncia_num", "num_denuncia", "nExp")
    ).strip()
    if not expediente:
        rid = (
            payload.get("idRecurso")
            or payload.get("resource_id")
            or payload.get("external_resource_id")
            or ""
        )
        return f"[NON_RETRY] valencia: expediente vacio [idRecurso={rid}]"

    tramite_tipo = _pick("tramite_tipo")
    tramite_code = _pick("tramite_code")
    if not (tramite_tipo and tramite_code):
        fase = _norm(payload.get("fase_procedimiento") or payload.get("FaseProcedimiento"))
        if "IDENTIFIC" in fase:
            payload.setdefault("tramite_tipo", "identificacion_conductor")
            payload.setdefault("tramite_code", "MU.DE.50")
        elif "DENUNCIA" in fase or "PROPUESTA" in fase:
            payload.setdefault("tramite_tipo", "alegaciones_denuncia_transito")
            payload.setdefault("tramite_code", "MU.DE.30")
        else:
            payload.setdefault("tramite_tipo", "recurso_reposicion")
            payload.setdefault("tramite_code", "MU.SA.40")

    if not _pick("expone"):
        payload["expone"] = f"Se presenta escrito en relacion con el expediente {expediente} y se exponen los hechos para su valoracion."
    if not _pick("solicita"):
        payload["solicita"] = f"Se solicita la admision y tramitacion del presente escrito relativo al expediente {expediente}."

    if payload.get("tramite_code") == "MU.SA.40":
        _resolve_valencia_matricula(payload)
    return None


async def _append_required_client_docs(
    payload: dict,
    archivos_para_subir: list[Path],
    *,
    site_id: Optional[str] = None,
) -> list[Path]:
    require_client_docs = (os.getenv("REQUIRE_CLIENT_DOCS") or "1").strip().lower() not in {"0", "false", "no", "off"}
    disable_gesdoc = bool(payload.get("disable_gesdoc"))
    merge_client_docs = (os.getenv("CLIENT_DOCS_MERGE") or "0").strip().lower() not in {"0", "false", "no", "off"}
    if not require_client_docs or disable_gesdoc:
        return archivos_para_subir

    gesdoc_user = os.getenv("GESDOC_USER")
    gesdoc_pwd = os.getenv("GESDOC_PWD")
    extra_docs = await get_required_client_documents(
        payload,
        gesdoc_user=gesdoc_user,
        gesdoc_pwd=gesdoc_pwd,
        sqlserver_conn_str=build_sqlserver_connection_string(),
        strict=True,
        merge_if_multiple=merge_client_docs,
    )

    existing = {str(Path(p).resolve()).lower() for p in archivos_para_subir}
    is_madrid = str(site_id or "").strip().lower() == "madrid"
    max_madrid_doc_bytes = 10 * 1024 * 1024
    for p in extra_docs:
        if is_madrid:
            try:
                size_bytes = int(p.stat().st_size)
            except Exception as e:
                logger.warning(
                    "Madrid: no se pudo leer tamano de documento de cliente, se omite: %s (%s)",
                    p,
                    e,
                )
                continue
            if size_bytes >= max_madrid_doc_bytes:
                logger.info(
                    "Madrid: documento de cliente omitido por tamano >=10MB: %s (%s bytes)",
                    p,
                    size_bytes,
                )
                continue
        key = str(Path(p).resolve()).lower()
        if key not in existing:
            archivos_para_subir.append(p)
            existing.add(key)
    return archivos_para_subir


async def process_task(
    task_id: Optional[int],
    site_id: str,
    protocol: Optional[str],
    payload: dict,
    auth_session: Optional[aiohttp.ClientSession] = None,
) -> ProcessOutcome:
    task_label = str(
        task_id
        if task_id is not None
        else payload.get("idRecurso")
        or payload.get("resource_id")
        or payload.get("idExp")
        or payload.get("expediente")
        or "NO_ID"
    )
    logger.info("Procesando tarea ID=%s site=%s protocol=%s", task_label, site_id, protocol)

    def _cleanup_tmp_workspace() -> None:
        """
        Limpia tmp tras cada recurso para evitar basura local/contenedor.
        """
        try:
            root = TMP_ROOT.resolve()
        except Exception:
            root = TMP_ROOT
        if not root.exists():
            return

        # Safety belt: nunca borrar fuera de .../tmp
        if root.name.lower() != "tmp":
            logger.warning("Se omite limpieza tmp por ruta insegura: %s", root)
            return

        for child in list(root.iterdir()):
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("No se pudo limpiar temporal %s: %s", child, exc)

    try:
        if auth_session is None:
            raise ValueError("auth_session es requerido para descargar documentos.")

        _flatten_embedded_payload(payload)
        _backfill_identity_from_sqlserver(payload)
        _normalize_site_minimum_payload(site_id, payload)
        if str(site_id or "").strip().lower() == "valencia":
            validation_error = _validate_valencia_preconditions(payload)
            if validation_error:
                return ProcessOutcome(
                    success=False,
                    error=validation_error,
                    release_without_attempt=True,
                )
        archivos_para_subir = await download_document_and_attachments(payload=payload, auth_session=auth_session)
        archivos_para_subir = await _append_required_client_docs(
            payload,
            archivos_para_subir,
            site_id=site_id,
        )
        payload["archivos"] = [str(p) for p in archivos_para_subir if p]

        if site_id == "ayunta_palma":
            pdf_unico = bundle_documents_to_single_pdf_for_palma(
                archivos_para_subir,
                id_recurso=payload.get("idRecurso"),
            )
            archivos_para_subir = [pdf_unico]
            payload["archivos"] = [str(pdf_unico)]

        if use_remote_playwright_runner():
            outcome = await execute_via_runner_service(
                site_id=site_id,
                protocol=protocol,
                payload=payload,
                archivos_para_subir=archivos_para_subir,
            )
        else:
            outcome = await execute_browser_flow(
                site_id=site_id,
                protocol=protocol,
                payload=payload,
                archivos_para_subir=archivos_para_subir,
            )

        if outcome.payload_updates:
            payload.update(outcome.payload_updates)

        if (not outcome.success) and site_id == "xaloc_girona":
            logger.critical(
                "CRITICAL_XALOC_GIRONA: flujo fallido (firma/envio/PDF). idRecurso=%s error=%s",
                payload.get("idRecurso"),
                outcome.error or "unknown_error",
            )

        if outcome.success:
            xaloc_justificante_ok = bool(payload.get("xaloc_justificante_descargado", True))
            if site_id == "xaloc_girona" and not xaloc_justificante_ok:
                logger.critical(
                    "CRITICAL_XALOC_GIRONA: tramite sin PDF de justificante. idRecurso=%s",
                    payload.get("idRecurso"),
                )
                return ProcessOutcome(
                    success=False,
                    error="xaloc_girona: tramite enviado pero justificante no descargado; cierre no confirmado",
                )
            if site_id == "base_online" and not payload.get("base_justificante_descargado"):
                logger.warning("BASE finalizado sin justificante descargado; no se marca completado en XVIA.")
            elif payload.get("idRecurso") and (site_id == "redsara" or not payload.get("skip_auto_complete")):
                success_mark = await mark_resource_complete(auth_session, payload)
                if not success_mark:
                    if site_id == "xaloc_girona":
                        logger.critical(
                            "CRITICAL_XALOC_GIRONA: fallo marcando completado XVIA. idRecurso=%s",
                            payload.get("idRecurso"),
                        )
                    else:
                        logger.error(
                            "Fallo marcando completado XVIA. site=%s idRecurso=%s",
                            site_id,
                            payload.get("idRecurso"),
                        )
        return outcome

    except RequiredClientDocumentsError as e:
        logger.error("Error documentacion cliente: %s", e)
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=f"Documentacion del cliente faltante: {e}")
    except ValueError as e:
        logger.error("Error de validacion en tarea %s: %s", task_label, e)
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=str(e))
    except RuntimeError as e:
        logger.error("Error de ejecucion en tarea %s: %s", task_label, e)
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=str(e))
    except FileNotFoundError as e:
        logger.error("Archivo no encontrado en tarea %s: %s", task_label, e)
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=f"Archivo no encontrado: {e}")
    except Exception as e:
        logger.error("Error inesperado en tarea %s: %s", task_label, e)
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=f"{type(e).__name__}: {e}")
    finally:
        _cleanup_tmp_workspace()
        logger.info("Finalizando procesamiento de tarea %s", task_label)
