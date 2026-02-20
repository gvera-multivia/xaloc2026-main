from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path
from typing import Optional

import aiohttp

from core.client_documentation import RequiredClientDocumentsError, build_required_client_documents_for_payload
from core.pdf_bundle import bundle_documents_to_single_pdf_for_palma
from core.sqlserver_utils import build_sqlserver_connection_string
from core.xvia_auth import mark_resource_complete
from .browser_executor import execute_browser_flow
from .document_fetcher import download_document_and_attachments
from .models import ProcessOutcome
from .runner_client import execute_via_runner_service, use_remote_playwright_runner

logger = logging.getLogger("worker.task_orchestrator")


async def _append_required_client_docs(payload: dict, archivos_para_subir: list[Path]) -> list[Path]:
    require_client_docs = (os.getenv("REQUIRE_CLIENT_DOCS") or "1").strip().lower() not in {"0", "false", "no", "off"}
    disable_gesdoc = bool(payload.get("disable_gesdoc"))
    merge_client_docs = (os.getenv("CLIENT_DOCS_MERGE") or "0").strip().lower() not in {"0", "false", "no", "off"}
    if not require_client_docs or disable_gesdoc:
        return archivos_para_subir

    gesdoc_user = os.getenv("GESDOC_USER")
    gesdoc_pwd = os.getenv("GESDOC_PWD")
    extra_docs = await build_required_client_documents_for_payload(
        payload,
        gesdoc_user=gesdoc_user,
        gesdoc_pwd=gesdoc_pwd,
        sqlserver_conn_str=build_sqlserver_connection_string(),
        strict=True,
        merge_if_multiple=merge_client_docs,
    )

    existing = {str(Path(p).resolve()).lower() for p in archivos_para_subir}
    for p in extra_docs:
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
    try:
        if auth_session is None:
            raise ValueError("auth_session es requerido para descargar documentos.")

        archivos_para_subir = await download_document_and_attachments(payload=payload, auth_session=auth_session)
        archivos_para_subir = await _append_required_client_docs(payload, archivos_para_subir)

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

        if outcome.success:
            if site_id == "base_online" and not payload.get("base_justificante_descargado"):
                logger.warning("BASE finalizado sin justificante descargado; no se marca completado en XVIA.")
            elif payload.get("idRecurso") and not payload.get("skip_auto_complete"):
                success_mark = await mark_resource_complete(auth_session, payload)
                if not success_mark:
                    logger.warning("No se pudo marcar recurso como completado en XVIA.")
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
        logger.info("Finalizando procesamiento de tarea %s", task_label)
