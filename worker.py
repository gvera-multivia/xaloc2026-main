import asyncio
import logging
import sys
import inspect
import traceback
import os
from pathlib import Path
from typing import Optional

from core.sqlite_db import SQLiteDatabase
from core.site_registry import get_site, get_site_controller

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
    supported = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return fn(**supported)

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

        # SOBREESCRIBIMOS la ruta del perfil para usar uno dedicado al worker
        worker_profile_path = Path("profiles/worker")
        config.navegador.perfil_path = worker_profile_path.absolute()

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
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        pass
