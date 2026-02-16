import asyncio
import contextlib
import logging
import inspect
import traceback
import os
import signal
import time
import uuid
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import subprocess

import aiohttp
from dotenv import load_dotenv
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

from core.sqlite_db import SQLiteDatabase
from core.queue_gateway import build_queue_gateway
from core.errors import RestartRequiredError, RestartWithProfileResetError, RetryWithoutAttemptError
from core.site_registry import get_site, get_site_controller
from core.validation import ValidationEngine, DiscrepancyReporter, DocumentDownloader
from core.attachments import AttachmentDownloader, AttachmentInfo
from core.client_documentation import RequiredClientDocumentsError, build_required_client_documents_for_payload
from core.xvia_auth import create_authenticated_session_in_place, mark_resource_complete
from core.sqlserver_utils import build_sqlserver_connection_string
from core.xvia_deselect import deselect_resource
from core.worker_logging import setup_worker_logging
from core.realtime_store import build_realtime_store
from core.pdf_bundle import bundle_documents_to_single_pdf_for_palma

# Configuracion de URLs y Directorios
DOCUMENT_URL_TEMPLATE = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/{idRecurso}"
DOWNLOAD_DIR = Path("tmp/downloads")

logger = logging.getLogger("worker")

# Cargar credenciales GESDOC desde .env
GESDOC_USER = os.getenv("GESDOC_USER")
GESDOC_PWD = os.getenv("GESDOC_PWD")

@dataclass
class ProcessOutcome:
    success: bool
    error: Optional[str] = None
    screenshot: Optional[str] = None
    release_without_attempt: bool = False


def _extraer_n_expediente(payload: dict) -> str:
    # 1) Claves directas (varios sites)
    keys = (
        "expediente",
        "expediente_num",
        "denuncia_num",
        "Expedient",
        "nExp",
        "numero_expediente",
    )
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    # 2) Madrid opcion 1: nnn/eeeeeeeee.d
    exp_nnn = str(payload.get("exp_nnn") or payload.get("expediente_nnn") or "").strip()
    exp_eeeeeeeee = str(payload.get("exp_eeeeeeeee") or payload.get("expediente_eeeeeeeee") or "").strip()
    exp_d = str(payload.get("exp_d") or payload.get("expediente_d") or "").strip()
    if exp_nnn and exp_eeeeeeeee and exp_d:
        return f"{exp_nnn}/{exp_eeeeeeeee}.{exp_d}"

    # 3) Madrid opcion 2: lll/aaaa/exp_num
    exp_lll = str(payload.get("exp_lll") or payload.get("expediente_lll") or "").strip()
    exp_aaaa = str(payload.get("exp_aaaa") or payload.get("expediente_aaaa") or "").strip()
    exp_exp_num = str(payload.get("exp_exp_num") or payload.get("expediente_exp_num") or "").strip()
    if exp_lll and exp_aaaa and exp_exp_num:
        return f"{exp_lll}/{exp_aaaa}/{exp_exp_num}"

    return "UNKNOWN"


def _sanitize_filename_component(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r'[<>:"|?*\x00-\x1F]', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(". ")
    return text or "UNKNOWN"

def _call_with_supported_kwargs(fn, **kwargs):
    """Llama a fn solo con los argumentos que acepta."""
    sig = inspect.signature(fn)
    supported = {k: v for k, v in kwargs.items() if k in sig.parameters and v is not None}
    return fn(**supported)

async def _download_document_and_attachments(
    *,
    payload: dict,
    auth_session: aiohttp.ClientSession,
) -> list[Path]:
    # Preservar archivos que ya vengan en payload (p.ej. docs de cliente precargados por adapters).
    payload_file_keys = ("archivos", "archivos_adjuntos", "p1_archivos", "p2_archivos", "p3_archivos")
    payload_files_raw: list[Path] = []
    for key in payload_file_keys:
        raw_val = payload.get(key)
        if not raw_val:
            continue
        if isinstance(raw_val, (str, Path)):
            payload_files_raw.append(Path(raw_val))
            continue
        if isinstance(raw_val, list):
            for item in raw_val:
                if isinstance(item, (str, Path)):
                    payload_files_raw.append(Path(item))

    id_recurso = payload.get("idRecurso")
    if not id_recurso:
        raise ValueError("Falta 'idRecurso' en el payload para descargar el documento.")

    target_url = DOCUMENT_URL_TEMPLATE.format(idRecurso=id_recurso)
    logger.info(f"Iniciando descarga autenticada desde: {target_url}")

    n_expediente = _sanitize_filename_component(_extraer_n_expediente(payload))
    local_pdf_path = DOWNLOAD_DIR / f"RECURSO exp - {n_expediente}.pdf"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Nombre documento principal (subida): %s", local_pdf_path.name)

    async with auth_session.get(target_url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"El servidor respondió con status {resp.status} al pedir el PDF.")

        content = await resp.read()

        if content.startswith(b"%PDF"):
            logger.info(f"Documento PDF validado correctamente ({len(content)} bytes).")
            local_pdf_path.write_bytes(content)
        else:
            sample = content[:200].decode(errors="ignore")
            logger.error(f"CONTENIDO NO VÁLIDO. Se esperaba PDF pero se recibió: {sample}...")
            if "login" in sample.lower() or "password" in sample.lower():
                raise RuntimeError("Sesión inválida o expirada (el servidor redirigió al login).")
            raise RuntimeError("El archivo descargado no es un PDF válido (posible error de intranet).")

    archivos_para_subir: list[Path] = [local_pdf_path]

    adjuntos_metadata = payload.get("adjuntos", [])
    if adjuntos_metadata:
        logger.info(f"Descargando {len(adjuntos_metadata)} adjunto(s)...")

        attachment_downloader = AttachmentDownloader()
        attachments_info = [
            AttachmentInfo(id=adj["id"], filename=adj["filename"], url=adj["url"])
            for adj in adjuntos_metadata
        ]

        download_results = await attachment_downloader.download_batch(
            attachments_info,
            str(id_recurso),
            session=auth_session,
        )

        for result in download_results:
            if result.success and result.local_path:
                archivos_para_subir.append(result.local_path)
                logger.info(f"Adjunto OK: {result.filename}")
            else:
                logger.warning(f"No se pudo descargar el adjunto {result.filename}: {result.error}")

    # Merge final: recurso principal + adjuntos descargados + archivos ya presentes en payload.
    merged: list[Path] = []
    seen_keys: set[str] = set()

    def _key(p: Path) -> str:
        return os.path.normcase(os.path.normpath(str(p)))

    for p in archivos_para_subir:
        if not p:
            continue
        k = _key(p)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        merged.append(p)

    for p in payload_files_raw:
        if not p:
            continue
        k = _key(p)
        if k in seen_keys:
            continue
        if not p.exists():
            logger.warning("Archivo del payload no encontrado, se omite: %s", p)
            continue
        seen_keys.add(k)
        merged.append(p)

    payload["archivos"] = [str(p) for p in merged if p]
    archivos_para_subir = merged
    logger.info("Archivos combinados para subida (descarga + payload): %s", len(archivos_para_subir))
    return archivos_para_subir

async def process_task(
    task_id: Optional[int],
    site_id: str,
    protocol: Optional[str],
    payload: dict,
    auth_session: Optional[aiohttp.ClientSession] = None
) -> ProcessOutcome:
    task_label = str(task_id) if task_id is not None else "TEST"
    logger.info(f"Procesando tarea ID: {task_label} - Site: {site_id} - Protocol: {protocol}")
    prev_keep_browser_open = os.getenv("XALOC_KEEP_BROWSER_OPEN")
    prev_keep_tab_open = os.getenv("XALOC_KEEP_TAB_OPEN")

    try:
        if auth_session is None:
            raise ValueError("auth_session es requerido para descargar documentos (sesión autenticada).")

        archivos_para_subir = await _download_document_and_attachments(
            payload=payload,
            auth_session=auth_session,
        )

        # 3.1 AÑADIR DOCUMENTACIÓN OBLIGATORIA DEL CLIENTE (para todas las webs)
        require_client_docs = (os.getenv("REQUIRE_CLIENT_DOCS") or "1").strip().lower() not in {"0", "false", "no", "off"}
        disable_gesdoc = bool(payload.get("disable_gesdoc"))
        merge_client_docs = (os.getenv("CLIENT_DOCS_MERGE") or "0").strip().lower() not in {"0", "false", "no", "off"}
        if require_client_docs and not disable_gesdoc:
            try:
                # MODIFICADO: Ahora es async y acepta credenciales GESDOC
                extra_docs = await build_required_client_documents_for_payload(
                    payload,
                    gesdoc_user=GESDOC_USER,
                    gesdoc_pwd=GESDOC_PWD,
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

                logger.info(
                    f"Documentación cliente añadida: {len(extra_docs)} archivo(s). Total a subir: {len(archivos_para_subir)}"
                )
            except RequiredClientDocumentsError as e:
                raise ValueError(f"Documentación obligatoria no disponible: {e}") from e
            except ValueError as e:
                # Distinguir entre errores de GESDOC y otros errores
                error_msg = str(e)
                if "No se pudo obtener autorización" in error_msg:
                    logger.error(f"❌ Error de GESDOC: {e}")
                    raise ValueError(f"Error obteniendo autorización vía GESDOC: {e}") from e
                elif "Credenciales GESDOC no configuradas" in error_msg:
                    logger.error(f"❌ GESDOC no configurado en .env")
                    raise ValueError(f"GESDOC no configurado: {e}") from e
                else:
                    raise
        elif disable_gesdoc:
            logger.info("GESDOC deshabilitado por payload (disable_gesdoc=1). Se omite la documentación obligatoria de cliente en worker.")

        # Palma solo admite un archivo: fusionar recurso + adjuntos + docs cliente en un único PDF.
        if site_id == "ayunta_palma":
            pdf_unico = bundle_documents_to_single_pdf_for_palma(
                archivos_para_subir,
                id_recurso=payload.get("idRecurso"),
            )
            archivos_para_subir = [pdf_unico]
            payload["archivos"] = [str(pdf_unico)]
            logger.info("ayunta_palma: PDF único generado para subida: %s", pdf_unico)

        # 4. PREPARAR AUTOMATIZACIÓN
        try:
            controller = get_site_controller(site_id)
            AutomationCls = get_site(site_id)
        except Exception as e:
            raise ValueError(f"No se encontró controlador/automator para {site_id}: {e}")

        headless = 1 if os.getenv("XALOC_HEADLESS") == "1" else 0
        config = _call_with_supported_kwargs(
            controller.create_config,
            headless=headless,
            protocol=protocol
        )

        worker_profile_path = Path("profiles/worker")
        config.navegador.perfil_path = worker_profile_path.absolute()

        # 5. MAPEO DE DATOS Y ASIGNACIÓN DE ARCHIVOS SEGÚN SITE
        mapped_data = controller.map_data(payload)
        mapped_data.update({
            "protocol": protocol,
            "headless": headless
        })

        # Inyectar la lista de archivos según el controlador del sitio
        if site_id == "madrid":
            mapped_data["archivos"] = archivos_para_subir
        elif site_id == "xaloc_girona":
            mapped_data["archivos_adjuntos"] = archivos_para_subir
        elif site_id == "base_online":
            if not protocol:
                raise ValueError("Falta 'protocol' para tareas del site 'base_online'.")
            protocol_norm = protocol.upper().strip()
            key = f"{protocol_norm.lower()}_archivos"
            mapped_data[key] = archivos_para_subir
        elif site_id == "ayunta_palma":
            mapped_data["archivos"] = archivos_para_subir

        datos = _call_with_supported_kwargs(controller.create_target, **mapped_data)

        # 6. EJECUTAR LA AUTOMATIZACIÓN
        logger.info(f"Iniciando automatización para {site_id}...")
        if site_id in ["madrid", "base_online", "ayunta_palma"]:
            os.environ["XALOC_KEEP_BROWSER_OPEN"] = "1"
            os.environ["XALOC_KEEP_TAB_OPEN"] = "1"

        async with AutomationCls(config) as bot:
            # Iniciar screencast en vivo para el dashboard (CDP).
            try:
                await bot.start_screencast()
            except Exception as sc_exc:
                logger.warning("No se pudo iniciar screencast en vivo: %s", sc_exc)

            try:
                screenshot_path = await bot.ejecutar_flujo_completo(datos)
            except RestartRequiredError as e:
                # Madrid (y otras sedes) pueden detectar "trámite en curso" y fallar al inicio.
                # En ese caso: cerrar el navegador del todo, reabrir, y saltar a la siguiente tarea.
                logger.warning(f"[RESTART] Reinicio requerido (tarea {task_label}): {e}")
                screenshot_path = None
                try:
                    screenshot_path = await bot.capture_error_screenshot("restart_required.png")
                except Exception:
                    pass

                try:
                    if isinstance(e, RestartWithProfileResetError):
                        await bot.restart_browser_with_clean_profile()
                        logger.info("Reinicio con perfil limpio completado; reencolando sin consumir intento.")
                    else:
                        await bot.restart_browser()
                        logger.info("Navegador reiniciado correctamente; reencolando sin consumir intento.")
                except Exception as restart_exc:
                    logger.error(f"Error reiniciando navegador tras RestartRequiredError: {restart_exc}")

                return ProcessOutcome(
                    success=False,
                    error=f"RestartRequiredError: {e}",
                    screenshot=str(screenshot_path) if screenshot_path else None,
                    release_without_attempt=True,
                )
            except RetryWithoutAttemptError as e:
                screenshot_path = None
                try:
                    screenshot_path = await bot.capture_error_screenshot("retry_without_attempt.png")
                except Exception:
                    pass

                try:
                    await bot.restart_browser()
                except Exception as restart_exc:
                    logger.error("Error reiniciando navegador tras RetryWithoutAttemptError: %s", restart_exc)

                return ProcessOutcome(
                    success=False,
                    error=str(e),
                    screenshot=str(screenshot_path) if screenshot_path else None,
                    release_without_attempt=True,
                )
            except asyncio.CancelledError:
                raise
            else:
                logger.info(f"Tarea {task_id} completada. Screenshot: {screenshot_path}")

                # --- MARCAR COMO COMPLETADO EN XVIA ---
                if not getattr(bot, "_exit_has_nonfatal_issues", False):
                    is_base_p1 = site_id == "base_online" and (protocol or "").upper() == "P1"
                    is_ayunta_palma = site_id == "ayunta_palma"
                    if is_base_p1:
                        logger.info("Saltando marcado autom. en XVIA para base_online P1.")
                    elif is_ayunta_palma:
                        logger.info("Saltando marcado autom. en XVIA para ayunta_palma.")
                    elif payload.get("idRecurso") and not payload.get("skip_auto_complete"):
                        logger.info(f"Intentando marcar recurso {payload['idRecurso']} como completado en la web...")
                        success_mark = await mark_resource_complete(auth_session, payload)
                        if not success_mark:
                            logger.warning("No se pudo marcar como completado en la web, pero el trámite fue enviado.")
                    elif payload.get("skip_auto_complete"):
                        logger.info("Salto 'Marcar como Completado' solicitado por payload.")
                else:
                    logger.warning("Tarea finalizada con incidencias no fatales. NO se marcara como completado en la web.")

                return ProcessOutcome(
                    success=True,
                    screenshot=str(screenshot_path) if screenshot_path else None,
                )
            finally:
                # Detener screencast en vivo al terminar la tarea (exito o fallo).
                try:
                    await bot.stop_screencast()
                except Exception:
                    pass

    except PlaywrightTimeoutError as e:
        error_msg = f"Timeout de Playwright: Elemento no encontrado o página no cargó a tiempo"
        logger.error(f"⏱️  Error en tarea {task_label}: {error_msg}")
        logger.error(f"Detalles: {str(e)}")
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=error_msg)

    except PlaywrightError as e:
        error_msg = f"Error de Playwright: {str(e)}"
        logger.error(f"🎭 Error en tarea {task_label}: {error_msg}")
        logger.error("Posibles causas: elemento no encontrado, selector incorrecto, o cambio en la estructura de la página")
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=error_msg)

    except asyncio.TimeoutError as e:
        error_msg = f"Timeout al procesar tarea {task_label}"
        logger.error(f"⏱️  {error_msg}")
        logger.error(f"Detalles: La operación excedió el tiempo límite de espera")
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=error_msg)

    except RequiredClientDocumentsError as e:
        error_msg = f"Documentación del cliente faltante: {e}"
        logger.error(f"📄 Error en tarea {task_label}: {error_msg}")
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=error_msg)

    except ValueError as e:
        error_msg = str(e)
        logger.error(f"❌ Error de validación en tarea {task_label}: {error_msg}")
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=error_msg)

    except RuntimeError as e:
        error_msg = str(e)
        logger.error(f"⚠️  Error de ejecución en tarea {task_label}: {error_msg}")
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=error_msg)

    except FileNotFoundError as e:
        error_msg = f"Archivo no encontrado: {e}"
        logger.error(f"📁 Error en tarea {task_label}: {error_msg}")
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=error_msg)

    except asyncio.CancelledError:
        logger.info("Tarea cancelada durante el procesamiento.")
        raise

    except Exception as e:
        # Captura cualquier otro error no previsto
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(f"💥 Error inesperado ({error_type}) en tarea {task_label}: {error_msg}")
        logger.error(traceback.format_exc())
        return ProcessOutcome(success=False, error=f"{error_type}: {error_msg}")

    finally:
        if prev_keep_browser_open is None:
            os.environ.pop("XALOC_KEEP_BROWSER_OPEN", None)
        else:
            os.environ["XALOC_KEEP_BROWSER_OPEN"] = prev_keep_browser_open
        if prev_keep_tab_open is None:
            os.environ.pop("XALOC_KEEP_TAB_OPEN", None)
        else:
            os.environ["XALOC_KEEP_TAB_OPEN"] = prev_keep_tab_open
        # Asegurar que siempre se registre el fin del procesamiento
        logger.info(f"Finalizando procesamiento de tarea {task_label}")
