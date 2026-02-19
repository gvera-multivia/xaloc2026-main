import asyncio
import logging
import os
import uuid
import signal
import contextlib
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from core.pg_runtime_store import PgRuntimeStore
from core.queue_gateway import build_queue_gateway
from core.realtime_store import build_realtime_store
from core.runtime_flags import get_queue_mode
from core.worker_logging import setup_worker_logging
from core.xvia_auth import create_authenticated_session_in_place
from core.xvia_deselect import deselect_resource

from core.worker.processor import process_task, _extraer_n_expediente
from core.worker.utils import int_env, purge_invalid_incidents_if_supported

logger = logging.getLogger("worker")

async def run_worker_loop():
    global logger
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    logger = setup_worker_logging(run_id)

    db = PgRuntimeStore.from_env(logger=logger)
    realtime_store = build_realtime_store(logger=logger)
    queue_backend = get_queue_mode()
    queue_gateway = build_queue_gateway(backend=queue_backend, db=db)
    logger.info("Iniciando Worker Loop. Esperando tareas...")
    logger.info("Run ID: %s", run_id)
    logger.info(f"Backend de cola activo: {queue_backend}")
    worker_instance_id = f"worker-{uuid.uuid4().hex}"
    worker_pid = os.getpid()
    logger.info("Worker UUID runtime: %s (pid=%s)", worker_instance_id, worker_pid)

    heartbeat_seconds = int_env("WORKER_HEARTBEAT_SECONDS", 5, minimum=1)
    heartbeat_timeout_seconds = int_env("WORKER_HEARTBEAT_TIMEOUT_SECONDS", 90, minimum=5)
    reconcile_interval_seconds = int_env("WORKER_RECONCILE_INTERVAL_SECONDS", 20, minimum=5)
    reconcile_batch_size = int_env("WORKER_RECONCILE_BATCH_SIZE", 200, minimum=1)

    runtime_state: dict[str, Optional[str]] = {"current_job_id": None}

    # -- GESTION DE PARADA ORDENADA --
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Señal de parada recibida (SIGINT/SIGTERM). Iniciando shutdown ordenado...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    if os.name != "nt": # sys.platform != "win32"
        try:
            loop.add_signal_handler(signal.SIGTERM, _signal_handler)
            loop.add_signal_handler(signal.SIGINT, _signal_handler)
        except NotImplementedError:
            pass

    heartbeat_task: Optional[asyncio.Task] = None
    reconcile_task: Optional[asyncio.Task] = None

    async def _runtime_heartbeat_loop() -> None:
        while not shutdown_event.is_set():
            try:
                db.upsert_worker_runtime(
                    worker_id=worker_instance_id,
                    run_id=run_id,
                    pid=worker_pid,
                    status="online",
                    current_job_id=runtime_state.get("current_job_id"),
                )
                await asyncio.wait_for(shutdown_event.wait(), timeout=heartbeat_seconds)
            except asyncio.TimeoutError:
                continue # Tick normal
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error en heartbeat: {e}")
                await asyncio.sleep(5)

    async def _runtime_reconcile_loop() -> None:
        if queue_backend != "sqlite":
            return
        while not shutdown_event.is_set():
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
                await asyncio.wait_for(shutdown_event.wait(), timeout=reconcile_interval_seconds)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Fallo en UUID reconcile de processing: %s", exc)
                await asyncio.sleep(5)

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
        shutdown_event.set()

    # CONFIGURACIÓN DE CABECERAS Y COOKIES
    cookie_jar = aiohttp.CookieJar(unsafe=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/login",
        "Origin": "http://www.xvia-grupoeuropa.net",
        "DNT": "1",
        "Connection": "keep-alive",
    }

    # Iniciamos la sesión persistente con el tarro de cookies especial
    processed_jobs = 0
    success_jobs = 0
    failed_jobs = 0
    auth_session = None

    try:
        auth_session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar)
        try:
            # Intentar el login único inicial
            await create_authenticated_session_in_place(auth_session, auth_email, auth_password)
            logger.info("XVIA Session lista y persistente (Cookies almacenadas).")
        except Exception as e:
            logger.error(f"Error crítico de autenticación inicial: {e}")
            shutdown_event.set()

        # Bucle principal de procesamiento
        while not shutdown_event.is_set():
            current_job = None
            try:
                # Reservamos con algo de espera, pero checkeando shutdown
                try:
                    job = await asyncio.wait_for(
                        queue_gateway.reserve(timeout_seconds=10, worker_id=worker_instance_id),
                        timeout=11
                    )
                except asyncio.TimeoutError:
                    job = None
                except asyncio.CancelledError:
                    break

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

                    try:
                        outcome = await process_task(
                            job.queue_ref,
                            job.site_id,
                            job.protocol,
                            job.payload,
                            auth_session,
                        )
                    except asyncio.CancelledError:
                        logger.warning("Job interrumpido por shutdown.")
                        await queue_gateway.release(job, reason="Shutdown del worker")
                        break

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
                            purge_invalid_incidents_if_supported(realtime_store, logger)
                            current_job = None
                            runtime_state["current_job_id"] = None
                            try:
                                await asyncio.wait_for(shutdown_event.wait(), timeout=10)
                            except asyncio.TimeoutError:
                                pass
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
                    purge_invalid_incidents_if_supported(realtime_store, logger)
                    current_job = None
                    runtime_state["current_job_id"] = None
                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        pass
                else:
                    runtime_state["current_job_id"] = None
                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        pass

            except KeyboardInterrupt:
                logger.info("Interrupción de teclado capturada en bucle principal.")
                shutdown_event.set()
                if current_job is not None:
                     try:
                        await queue_gateway.release(
                            current_job,
                            reason="Interrumpido por operador (Ctrl+C). Devuelto a pendiente.",
                        )
                        logger.info("Job %s liberado.", current_job.job_id)
                     except Exception:
                         pass
            except asyncio.CancelledError:
                 logger.info("Worker loop cancelado.")
                 shutdown_event.set()
                 break
            except Exception as e:
                error_type = type(e).__name__
                logger.error(f"💥 Error inesperado en el bucle principal ({error_type}): {e}")
                logger.error(traceback.format_exc())
                logger.info("⚡ El worker continuará procesando tareas después de este error...")
                runtime_state["current_job_id"] = None
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

    finally:
        shutdown_event.set()

        for task in (heartbeat_task, reconcile_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        if auth_session and not auth_session.closed:
            await auth_session.close()

        db.mark_worker_runtime_offline(worker_id=worker_instance_id)
        logger.info(
            "Resumen ejecución run=%s processed=%s success=%s failed=%s",
            run_id,
            processed_jobs,
            success_jobs,
            failed_jobs,
        )
        logger.info("Worker finalizado correctamente.")
