import asyncio
import logging
import sys
import inspect
import traceback
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import subprocess

from core.sqlite_db import SQLiteDatabase
from core.site_registry import get_site, get_site_controller
from core.errors import RestartRequiredError

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

def _reset_profile_dir(profile_path: Path) -> None:
    """
    Resetea el perfil persistente moviendo la carpeta a un backup con timestamp.
    Útil cuando el sitio queda "atascado" por sesión/cookies (p.ej. 'trámite en curso').
    """
    try:
        if not profile_path.exists():
            return

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = profile_path.parent / f"{profile_path.name}_bak_{ts}"
        profile_path.rename(backup_path)
        logger.warning(f"Perfil reseteado: {profile_path} -> {backup_path}")
    except Exception as e:
        logger.warning(f"No se pudo resetear el perfil {profile_path}: {e}")

def _call_with_supported_kwargs(fn, **kwargs):
    """Llama a fn solo con los argumentos que acepta."""
    sig = inspect.signature(fn)
    supported = {k: v for k, v in kwargs.items() if k in sig.parameters}
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
        # 1. Obtener controlador y clase de automatización
        try:
            controller = get_site_controller(site_id)
            AutomationCls = get_site(site_id)
        except Exception as e:
            raise ValueError(f"No se encontró controlador/automator para {site_id}: {e}")

        # 2. Crear configuración
        # Por defecto headless=True para el worker (desatendido).
        # Override: WORKER_HEADLESS=0 para ejecutar en visible (debug/calentamiento de perfil).
        headless_env = os.getenv("WORKER_HEADLESS", "0").strip().lower()
        headless = headless_env not in {"0", "false", "no"}

        # Creamos la config base usando el controlador
        config = _call_with_supported_kwargs(
            controller.create_config,
            headless=headless,
            protocol=protocol
        )

        # SOBREESCRIBIMOS la ruta del perfil para usar uno dedicado al worker (por site)
        worker_profile_path = (Path("profiles") / "worker" / site_id).absolute()
        config.navegador.perfil_path = worker_profile_path

        # 3. Preparar los datos (Target)
        # Mapeamos los datos crudos (payload) al formato interno
        mapped_data = controller.map_data(payload)

        # Añadimos info de contexto
        mapped_data.update({
            "protocol": protocol,
            "headless": headless
        })

        # Creamos el objeto Target
        datos = _call_with_supported_kwargs(controller.create_target, **mapped_data)

        # 4. Ejecutar la automatización
        logger.info(f"Iniciando automatización para {site_id}...")
        try:
            async with AutomationCls(config) as bot:
                screenshot_path = await bot.ejecutar_flujo_completo(datos)

                logger.info(f"Tarea {task_id} completada. Screenshot: {screenshot_path}")
                db.update_task_status(task_id, "completed", screenshot=str(screenshot_path))

        except RestartRequiredError as e:
            max_attempts = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))
            attempts = db.get_task_attempts(task_id)
            msg = f"{type(e).__name__}: {e}"

            logger.warning(
                f"Tarea {task_id}: reinicio requerido ({attempts}/{max_attempts}). "
                f"Reseteando perfil y re-encolando. Motivo: {msg}"
            )
            _reset_profile_dir(worker_profile_path)

            if attempts >= max_attempts:
                db.update_task_status(task_id, "failed", error=msg)
            else:
                db.requeue_task(task_id, error=msg)
            return

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
