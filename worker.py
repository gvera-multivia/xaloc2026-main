import asyncio
import logging
import sys
import inspect
import traceback
import os
from pathlib import Path
from typing import Optional
import subprocess

from core.sqlite_db import SQLiteDatabase
from core.site_registry import get_site, get_site_controller
from core.validation import ValidationEngine, DiscrepancyReporter, DocumentDownloader
from core.attachments import AttachmentDownloader, AttachmentInfo

# Configuración de URLs y Directorios
DOCUMENT_URL_TEMPLATE = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/{idRecurso}"
DOWNLOAD_DIR = Path("tmp/downloads")

# Configuración de logging para el Worker
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [WORKER] - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/worker.log", encoding="utf-8")
    ]
)

logger = logging.getLogger("worker")

def _call_with_supported_kwargs(fn, **kwargs):
    """Llama a fn solo con los argumentos que acepta."""
    sig = inspect.signature(fn)
    supported = {k: v for k, v in kwargs.items() if k in sig.parameters and v is not None}
    return fn(**supported)

def apply_url_cert_config():
    """
    Ejecuta el script de configuración de certificados leyendo el archivo:
    url-cert-config.txt (que contiene comandos CMD tal cual).
    Solo aplica en Windows.
    """
    if sys.platform != "win32":
        logger.info("apply_url_cert_config: no es Windows; se omite.")
        return

    script_path = Path("url-cert-config.txt")
    if not script_path.exists():
        raise FileNotFoundError(f"No existe {script_path.resolve()}")

    logger.info(f"Aplicando configuración de AutoSelectCertificateForUrls desde: {script_path.resolve()}")

    # Ejecuta el archivo con cmd.exe para que soporte 'set', 'rem', expansión %CN%, etc.
    # /d -> no auto-run, /s -> manejo de comillas, /c -> ejecutar y salir
    completed = subprocess.run(
        ["cmd.exe", "/d", "/s", "/c", str(script_path.resolve())],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if completed.stdout:
        logger.info(f"[url-cert-config stdout]\n{completed.stdout.strip()}")
    if completed.stderr:
        logger.warning(f"[url-cert-config stderr]\n{completed.stderr.strip()}")

    if completed.returncode != 0:
        raise RuntimeError(f"url-cert-config.txt falló con código {completed.returncode}")

    logger.info("Configuración de certificados aplicada correctamente.")

async def process_task(db: SQLiteDatabase, task_id: int, site_id: str, protocol: Optional[str], payload: dict):
    logger.info(f"Procesando tarea ID: {task_id} - Site: {site_id} - Protocol: {protocol}")

    try:
        meta = payload.get("_meta") or {}
        skip_validation = True
        no_defaults = True

        if not skip_validation:
            logger.info(f"Validando datos para ID: {payload.get('idRecurso', 'N/A')}...")
            validator = ValidationEngine(site_id=site_id)
            val_result = validator.validate(payload)

            if not val_result.is_valid:
                logger.warning(f"Validación fallida para Tarea {task_id}")
                reporter = DiscrepancyReporter()
                report_path = reporter.generate_html(
                    payload, 
                    val_result.errors, 
                    val_result.warnings,
                    str(payload.get('idRecurso', 'N/A'))
                )
                reporter.open_in_browser(report_path)
                
                print(f"\n[!] VALIDACIÓN FALLIDA para ID: {payload.get('idRecurso', 'N/A')}")
                print(f"Reporte generado en: {report_path.absolute()}")
                print("Por favor, corrija los datos en la base de datos.")
                
                input("Pulse Enter para continuar con la siguiente tarea una vez revisado... (o Ctrl+C para salir)")
                
                db.update_task_status(task_id, "failed", error="Validation failed. Discrepancy report opened.")
                return

        # 2. DESCARGA DE DOCUMENTO
        id_recurso = payload.get("idRecurso")
        if not id_recurso:
            raise ValueError("Falta 'idRecurso' en el payload para descargar el documento.")

        downloader = DocumentDownloader(url_template=DOCUMENT_URL_TEMPLATE, download_dir=DOWNLOAD_DIR)
        download_res = await downloader.download(str(id_recurso))

        if not download_res.success:
            logger.error(f"Error descargando documento: {download_res.error}")
            db.update_task_status(task_id, "failed", error=f"Download failed: {download_res.error}")
            return

        local_pdf_path = download_res.local_path
        archivos_para_subir = [local_pdf_path]
        
        # 3. DESCARGA DE ADJUNTOS (NUEVO)
        adjuntos_metadata = payload.get("adjuntos", [])
        if adjuntos_metadata:
            logger.info(f"Descargando {len(adjuntos_metadata)} adjunto(s)...")

            attachment_downloader = AttachmentDownloader()
            attachments_info = [
                AttachmentInfo(
                    id=adj["id"],
                    filename=adj["filename"],
                    url=adj["url"]
                )
                for adj in adjuntos_metadata
            ]

            download_results = await attachment_downloader.download_batch(
                attachments_info,
                str(id_recurso)
            )

            # Validar resultados
            failed_downloads = [r for r in download_results if not r.success]
            if failed_downloads:
                error_msg = f"Fallo descargando {len(failed_downloads)} adjunto(s): " + \
                           ", ".join([f"{r.filename} ({r.error})" for r in failed_downloads])
                logger.error(error_msg)
                db.update_task_status(task_id, "failed", error=error_msg)
                return

            # Añadir adjuntos descargados a la lista de archivos
            for result in download_results:
                if result.local_path:
                    archivos_para_subir.append(result.local_path)
                    logger.info(f"Adjunto descargado: {result.filename} ({result.file_size_bytes} bytes)")

        # 4. Preparar automatización
        try:
            controller = get_site_controller(site_id)
            AutomationCls = get_site(site_id)
        except Exception as e:
            raise ValueError(f"No se encontró controlador/automator para {site_id}: {e}")

        
        headless = 0 # Navegador visible para depuración headless=1 -> oculto

        config = _call_with_supported_kwargs(
            controller.create_config,
            headless=headless,
            protocol=protocol
        )

        worker_profile_path = Path("profiles/worker")
        config.navegador.perfil_path = worker_profile_path.absolute()

        # 5. Mapear datos y añadir TODOS los archivos descargados
        mapped_data = controller.map_data(payload)
        
        mapped_data.update({
            "protocol": protocol,
            "headless": headless
        })

        if site_id == "madrid":
            mapped_data["archivos"] = archivos_para_subir
        elif site_id == "xaloc_girona":
            mapped_data["archivos_adjuntos"] = archivos_para_subir
        elif site_id == "base_online":
            protocol_norm = (protocol or "P1").upper().strip()
            if protocol_norm == "P2":
                mapped_data["p2_archivos"] = archivos_para_subir
            elif protocol_norm == "P3":
                mapped_data["p3_archivos"] = archivos_para_subir
            else:
                mapped_data["p1_archivos"] = archivos_para_subir

        target_fn = controller.create_target
        if no_defaults and hasattr(controller, "create_target_strict"):
            target_fn = controller.create_target_strict

        datos = _call_with_supported_kwargs(target_fn, **mapped_data)

        # 6. Ejecutar la automatización
        logger.info(f"Iniciando automatización para {site_id}...")
        async with AutomationCls(config) as bot:
            screenshot_path = await bot.ejecutar_flujo_completo(datos)

            logger.info(f"Tarea {task_id} completada. Screenshot: {screenshot_path}")
            db.update_task_status(task_id, "completed", screenshot=str(screenshot_path))

    except Exception as e:
        logger.error(f"Error procesando tarea {task_id}: {e}")
        logger.error(traceback.format_exc())
        db.update_task_status(task_id, "failed", error=str(e))

async def worker_loop():
    db = SQLiteDatabase()
    logger.info("Iniciando Worker Loop. Esperando tareas...")

    while True:
        try:
            task = db.get_pending_task()
            if task:
                task_id, site_id, protocol, payload = task
                await process_task(db, task_id, site_id, protocol, payload)
            else:
                # No hay tareas, dormir
                await asyncio.sleep(10)
        except KeyboardInterrupt:
            logger.info("Deteniendo worker por interrupción de teclado...")
            break
        except Exception as e:
            logger.error(f"Error en el bucle principal: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        # ANTES DE NADA: aplicar el script de registro desde url-cert-config.txt
        apply_url_cert_config()

        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        pass
