import asyncio
import argparse
import logging
import sys
import inspect
import traceback
import os
from pathlib import Path
from typing import Optional
import subprocess

import aiohttp
from dotenv import load_dotenv

from core.sqlite_db import SQLiteDatabase
from core.site_registry import get_site, get_site_controller
from core.validation import ValidationEngine, DiscrepancyReporter, DocumentDownloader
from core.attachments import AttachmentDownloader, AttachmentInfo
from core.xvia_auth import create_authenticated_session_in_place

# Configuracion de URLs y Directorios
DOCUMENT_URL_TEMPLATE = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/{idRecurso}"
DOWNLOAD_DIR = Path("tmp/downloads")

# Configuracion de logging para el Worker
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
    Ejecuta el script de configuracion de certificados leyendo el archivo:
    url-cert-config.txt (que contiene comandos CMD tal cual).
    Solo aplica en Windows.
    """
    if sys.platform != "win32":
        logger.info("apply_url_cert_config: no es Windows; se omite.")
        return

    script_path = Path("url-cert-config.txt")
    if not script_path.exists():
        raise FileNotFoundError(f"No existe {script_path.resolve()}")

    logger.info(f"Aplicando configuracion de AutoSelectCertificateForUrls desde: {script_path.resolve()}")

    # Ejecuta el archivo con cmd.exe para que soporte 'set', 'rem', expansion %CN%, etc.
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
        raise RuntimeError(f"url-cert-config.txt fallo con codigo {completed.returncode}")

    logger.info("Configuracion de certificados aplicada correctamente.")

async def _download_document_and_attachments(
    *,
    payload: dict,
    auth_session: aiohttp.ClientSession,
) -> list[Path]:
    id_recurso = payload.get("idRecurso")
    if not id_recurso:
        raise ValueError("Falta 'idRecurso' en el payload para descargar el documento.")

    target_url = DOCUMENT_URL_TEMPLATE.format(idRecurso=id_recurso)
    logger.info(f"Iniciando descarga autenticada desde: {target_url}")

    local_pdf_path = DOWNLOAD_DIR / f"{id_recurso}.pdf"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

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

    payload["archivos"] = [str(p) for p in archivos_para_subir if p]
    return archivos_para_subir

async def process_task(
    db: Optional[SQLiteDatabase],
    task_id: Optional[int],
    site_id: str,
    protocol: Optional[str],
    payload: dict,
    auth_session: Optional[aiohttp.ClientSession] = None
):
    task_label = str(task_id) if task_id is not None else "TEST"
    logger.info(f"Procesando tarea ID: {task_label} - Site: {site_id} - Protocol: {protocol}")

    try:
        if auth_session is None:
            raise ValueError("auth_session es requerido para descargar documentos (sesión autenticada).")

        archivos_para_subir = await _download_document_and_attachments(
            payload=payload,
            auth_session=auth_session,
        )

        # 4. PREPARAR AUTOMATIZACIÓN
        try:
            controller = get_site_controller(site_id)
            AutomationCls = get_site(site_id)
        except Exception as e:
            raise ValueError(f"No se encontró controlador/automator para {site_id}: {e}")

        headless = 0 # Cambiar a 1 para ocultar el navegador
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
        async with AutomationCls(config) as bot:
            screenshot_path = await bot.ejecutar_flujo_completo(datos)

            logger.info(f"Tarea {task_id} completada. Screenshot: {screenshot_path}")
            if db is not None and task_id is not None:
                db.update_task_status(task_id, "completed", screenshot=str(screenshot_path))

    except Exception as e:
        logger.error(f"Error procesando tarea {task_id}: {e}")
        logger.error(traceback.format_exc())
        if db is not None and task_id is not None:
            db.update_task_status(task_id, "failed", error=str(e))

async def worker_loop():
    db = SQLiteDatabase()
    logger.info("Iniciando Worker Loop. Esperando tareas...")

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
    async with aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar) as auth_session:
        try:
            # Intentar el login único inicial
            await create_authenticated_session_in_place(auth_session, auth_email, auth_password)
            logger.info("XVIA Session lista y persistente (Cookies almacenadas).")
        except Exception as e:
            logger.error(f"Error crítico de autenticación inicial: {e}")
            return # Si no podemos loguear al inicio, el worker no puede trabajar

        # Bucle principal de procesamiento
        while True:
            try:
                task = db.get_pending_task()
                if task:
                    task_id, site_id, protocol, payload = task
                    # Procesamos la tarea pasando la sesión autenticada
                    await process_task(db, task_id, site_id, protocol, payload, auth_session)
                else:
                    # Sin tareas: esperar 10 segundos antes de volver a consultar la DB
                    await asyncio.sleep(10)
                    
            except KeyboardInterrupt:
                logger.info("Deteniendo worker por interrupción de teclado (Ctrl+C)...")
                break
            except Exception as e:
                logger.error(f"Error inesperado en el bucle principal: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)

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
