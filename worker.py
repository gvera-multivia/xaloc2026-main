import asyncio
import argparse
import contextlib
import logging
import sys
import inspect
import traceback
import os
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


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return max(minimum, int(default))
    try:
        return max(minimum, int(raw))
    except Exception:
        return max(minimum, int(default))

def apply_url_cert_config():
    if sys.platform != "win32":
        return

    script_path = Path("url-cert-config.bat")
    if not script_path.exists():
        logger.error("No se encontro url-cert-config.bat")
        return

    try:
        # Ejecutamos con encoding utf-8 para coincidir con el chcp 65001 del bat
        completed = subprocess.run(
            [str(script_path.resolve())],
            capture_output=True,
            text=True,
            shell=True,
            encoding="utf-8", 
            errors="replace"
        )

        # Solo logueamos exito si el bat imprimio nuestra palabra clave
        if completed.returncode == 0 and "EXITOSOS" in completed.stdout:
            logger.info("Configuracion de certificados aplicada correctamente.")
        else:
            logger.error(f"Fallo en la configuracion. Error: {completed.stderr.strip()}")

    except Exception as e:
        logger.error(f"Error inesperado al aplicar certificados: {e}")
        
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

        datos = _call_with_supported_kwargs(controller.create_target, **mapped_data)

        # 6. EJECUTAR LA AUTOMATIZACIÓN
        logger.info(f"Iniciando automatización para {site_id}...")
        if site_id in ["madrid", "base_online"]:
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
            else:
                # Éxito: flujo completo sin excepciones de reinicio.
                logger.info(f"Tarea {task_id} completada. Screenshot: {screenshot_path}")

                # --- MARCAR COMO COMPLETADO EN XVIA ---
                if not getattr(bot, "_exit_has_nonfatal_issues", False):
                    is_base_p1 = site_id == "base_online" and (protocol or "").upper() == "P1"
                    if is_base_p1:
                        logger.info("Saltando marcado autom. en XVIA para base_online P1.")
                    elif payload.get("idRecurso") and not payload.get("skip_auto_complete"):
                        logger.info(f"Intentando marcar recurso {payload['idRecurso']} como completado en la web...")
                        success_mark = await mark_resource_complete(auth_session, payload)
                        if not success_mark:
                            logger.warning("No se pudo marcar como completado en la web, pero el trámite fue enviado.")
                    elif payload.get("skip_auto_complete"):
                        logger.info(f"⏭️  Salto 'Marcar como Completado' solicitado por payload.")
                else:
                    logger.warning("Tarea finalizada con incidencias no fatales. NO se marcará como completado en la web.")

                return ProcessOutcome(
                    success=True,
                    screenshot=str(screenshot_path) if screenshot_path else None,
                )
            finally:
                # Detener screencast en vivo al terminar la tarea (éxito o fallo).
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

async def worker_loop():
    global logger
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    logger = setup_worker_logging(run_id)

    db = SQLiteDatabase()
    realtime_store = build_realtime_store(logger=logger)
    queue_backend = (os.getenv("QUEUE_BACKEND", "sqlite") or "sqlite").strip().lower()
    queue_gateway = build_queue_gateway(backend=queue_backend, db=db)
    logger.info("Iniciando Worker Loop. Esperando tareas...")
    logger.info("Run ID: %s", run_id)
    logger.info(f"Backend de cola activo: {queue_backend}")
    worker_instance_id = f"worker-{uuid.uuid4().hex}"
    worker_pid = os.getpid()
    logger.info("Worker UUID runtime: %s (pid=%s)", worker_instance_id, worker_pid)

    heartbeat_seconds = _int_env("WORKER_HEARTBEAT_SECONDS", 5, minimum=1)
    heartbeat_timeout_seconds = _int_env("WORKER_HEARTBEAT_TIMEOUT_SECONDS", 90, minimum=5)
    reconcile_interval_seconds = _int_env("WORKER_RECONCILE_INTERVAL_SECONDS", 20, minimum=5)
    reconcile_batch_size = _int_env("WORKER_RECONCILE_BATCH_SIZE", 200, minimum=1)

    runtime_state: dict[str, Optional[str]] = {"current_job_id": None}
    stop_runtime_tasks = asyncio.Event()
    heartbeat_task: Optional[asyncio.Task] = None
    reconcile_task: Optional[asyncio.Task] = None

    async def _runtime_heartbeat_loop() -> None:
        while not stop_runtime_tasks.is_set():
            db.upsert_worker_runtime(
                worker_id=worker_instance_id,
                run_id=run_id,
                pid=worker_pid,
                status="online",
                current_job_id=runtime_state.get("current_job_id"),
            )
            await asyncio.sleep(heartbeat_seconds)

    async def _runtime_reconcile_loop() -> None:
        if queue_backend != "sqlite":
            return
        while not stop_runtime_tasks.is_set():
            try:
                result = db.reconcile_processing_with_worker_runtime(
                    heartbeat_timeout_seconds=heartbeat_timeout_seconds,
                    limit=reconcile_batch_size,
                )
                if result.get("recovered"):
                    logger.warning(
                        "UUID reconcile: %s processing recuperados (workers vivos=%s).",
                        result.get("recovered"),
                        result.get("alive_workers"),
                    )
            except Exception as exc:
                logger.error("Fallo en UUID reconcile de processing: %s", exc)
            await asyncio.sleep(reconcile_interval_seconds)
    db.upsert_worker_runtime(
        worker_id=worker_instance_id,
        run_id=run_id,
        pid=worker_pid,
        status="online",
        current_job_id=None,
    )
    heartbeat_task = asyncio.create_task(_runtime_heartbeat_loop())
    reconcile_task = asyncio.create_task(_runtime_reconcile_loop())

    # Cargar credenciales
    load_dotenv()
    auth_email = os.getenv("XVIA_EMAIL")
    auth_password = os.getenv("XVIA_PASSWORD")
    
    if not auth_email or not auth_password:
        logger.error("Faltan XVIA_EMAIL/XVIA_PASSWORD en el entorno o archivo .env.")
        return

    # CONFIGURACIÓN DE CABECERAS Y COOKIES
    # unsafe=True permite procesar cookies en conexiones HTTP no cifradas
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/login", # Clave para CSRF
        "Origin": "http://www.xvia-grupoeuropa.net",
        "DNT": "1",
        "Connection": "keep-alive",
    }

    # Iniciamos la sesión persistente con el tarro de cookies especial
    processed_jobs = 0
    success_jobs = 0
    failed_jobs = 0

    try:
        async with aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar) as auth_session:
            try:
                # Intentar el login único inicial
                await create_authenticated_session_in_place(auth_session, auth_email, auth_password)
                logger.info("XVIA Session lista y persistente (Cookies almacenadas).")
            except Exception as e:
                logger.error(f"Error crítico de autenticación inicial: {e}")
                return  # Si no podemos loguear al inicio, el worker no puede trabajar

            # Bucle principal de procesamiento
            while True:
                current_job = None
                try:
                    job = await queue_gateway.reserve(timeout_seconds=10, worker_id=worker_instance_id)
                    if job:
                        current_job = job
                        runtime_state["current_job_id"] = job.job_id
                        processed_jobs += 1
                        logger.info(
                            "Procesando job %s (intento %s/%s) site=%s resource=%s",
                            job.job_id,
                            int(job.attempt) + 1,
                            job.max_attempts,
                            job.site_id,
                            job.resource_id,
                        )
                        started = time.perf_counter()
                        started_at = datetime.now(timezone.utc)
                        outcome = await process_task(
                            job.queue_ref,
                            job.site_id,
                            job.protocol,
                            job.payload,
                            auth_session,
                        )
                        elapsed = time.perf_counter() - started
                        ended_at = datetime.now(timezone.utc)
                        if outcome.success:
                            success_jobs += 1
                            await queue_gateway.ack(
                                job,
                                result={"screenshot_path": outcome.screenshot} if outcome.screenshot else None,
                                screenshot=outcome.screenshot,
                            )
                            realtime_store.record_task_success(
                                payload=job.payload,
                                site_id=job.site_id,
                                resource_id=job.resource_id,
                                job_id=job.job_id,
                                protocol=job.protocol,
                                result={"screenshot_path": outcome.screenshot, "elapsed_seconds": elapsed},
                                started_at=started_at,
                                ended_at=ended_at,
                            )
                        else:
                            failed_jobs += 1
                            if outcome.release_without_attempt:
                                await queue_gateway.release(
                                    job,
                                    reason=outcome.error or "release_without_attempt",
                                )
                                realtime_store.record_incident_once(
                                    site_id=job.site_id,
                                    incident_type="RETRY_WITHOUT_ATTEMPT",
                                    reason=outcome.error or "release_without_attempt",
                                    resource_id=job.resource_id,
                                    expediente=_extraer_n_expediente(job.payload),
                                    payload=job.payload,
                                    started_at=started_at,
                                    ended_at=ended_at,
                                )
                                current_job = None
                                runtime_state["current_job_id"] = None
                                await asyncio.sleep(10)
                                continue

                            exhausted = (int(job.attempt) + 1) >= int(job.max_attempts)
                            if exhausted and job.resource_id is not None:
                                deselected = await deselect_resource(auth_session, int(job.resource_id))
                                suffix = (
                                    " Recurso liberado en XVIA."
                                    if deselected
                                    else " No se pudo liberar recurso en XVIA."
                                )
                                base_error = outcome.error or "unknown_error"
                                db.block_resource(
                                    site_id=job.site_id,
                                    resource_id=int(job.resource_id),
                                    reason=f"Final failure tras reintentos agotados. {base_error}",
                                    source="worker_retry_exhausted",
                                )
                                realtime_store.record_task_failed_final(
                                    site_id=job.site_id,
                                    resource_id=job.resource_id,
                                    job_id=job.job_id,
                                    protocol=job.protocol,
                                    payload=job.payload,
                                    error_message=f"{base_error}{suffix}",
                                    started_at=started_at,
                                    ended_at=ended_at,
                                    extra={"xvia_deselected": bool(deselected)},
                                )

                            await queue_gateway.nack(
                                job,
                                error=outcome.error or "unknown_error",
                                retryable=True,
                            )
                        if outcome.success and job.site_id == "madrid" and job.payload.get("madrid_tramite_enviado") and not job.payload.get("madrid_justificante_descargado", True):
                            anotacion = str(job.payload.get("madrid_numero_anotacion") or "").strip()
                            refresh_count = job.payload.get("madrid_post_envio_refresh_count")
                            motivo = (
                                "Trámite enviado correctamente en Madrid, pero justificante no descargado. "
                                f"Número de anotación: {anotacion or 'N/A'}. "
                                f"Refrescos aplicados: {refresh_count if refresh_count is not None else 'N/A'}."
                            )
                            try:
                                db.add_incident(
                                    id_recurso=job.resource_id,
                                    n_exp=_extraer_n_expediente(job.payload),
                                    tipo="MADRID_TRAMITE_ENVIADO_SIN_JUSTIFICANTE",
                                    motivo=motivo,
                                    site_id=job.site_id,
                                )
                            except Exception as inc_db_exc:
                                logger.error("No se pudo guardar incidencia Madrid sin justificante en SQLite: %s", inc_db_exc)
                            realtime_store.record_incident_once(
                                site_id=job.site_id,
                                incident_type="MADRID_TRAMITE_ENVIADO_SIN_JUSTIFICANTE",
                                reason=motivo,
                                resource_id=job.resource_id,
                                expediente=_extraer_n_expediente(job.payload),
                                payload=job.payload,
                                started_at=started_at,
                                ended_at=ended_at,
                            )
                        current_job = None
                        runtime_state["current_job_id"] = None
                        # Pausa fija entre jobs para no encadenar acciones en la sede/web
                        await asyncio.sleep(10)
                    else:
                        runtime_state["current_job_id"] = None
                        # Sin tareas: esperar 10 segundos antes de volver a consultar la cola
                        await asyncio.sleep(10)

                except KeyboardInterrupt:
                    if current_job is not None:
                        try:
                            await queue_gateway.release(
                                current_job,
                                reason="Interrumpido por operador (Ctrl+C). Devuelto a pendiente.",
                            )
                            logger.info(
                                "Job %s devuelto a pendiente tras Ctrl+C.",
                                current_job.job_id,
                            )
                        except Exception as release_exc:
                            logger.error(
                                "No se pudo devolver el job %s a pendiente tras Ctrl+C: %s",
                                current_job.job_id,
                                release_exc,
                            )
                    logger.info("Deteniendo worker por interrupción de teclado (Ctrl+C)...")
                    runtime_state["current_job_id"] = None
                    break
                except Exception as e:
                    error_type = type(e).__name__
                    logger.error(f"💥 Error inesperado en el bucle principal ({error_type}): {e}")
                    logger.error(traceback.format_exc())
                    logger.info("⚡ El worker continuará procesando tareas después de este error...")
                    runtime_state["current_job_id"] = None
                    await asyncio.sleep(5)
    finally:
        stop_runtime_tasks.set()
        for task in (heartbeat_task, reconcile_task):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(Exception):
                await task
        db.mark_worker_runtime_offline(worker_id=worker_instance_id)
        logger.info(
            "Resumen ejecución run=%s processed=%s success=%s failed=%s",
            run_id,
            processed_jobs,
            success_jobs,
            failed_jobs,
        )
        logger.info("Worker finalizado correctamente.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        # ANTES DE NADA: aplicar el script de registro desde url-cert-config.txt
        apply_url_cert_config()
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        pass
