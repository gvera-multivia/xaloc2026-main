import os
import sys
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("worker.utils")

def int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return max(minimum, int(default))
    try:
        return max(minimum, int(raw))
    except Exception:
        return max(minimum, int(default))

def purge_invalid_incidents_if_supported(realtime_store, logger: logging.Logger) -> None:
    cleanup = getattr(realtime_store, "purge_invalid_incidents", None)
    if not callable(cleanup):
        return
    try:
        removed = int(cleanup() or 0)
        if removed > 0:
            logger.info("Panel incidencias: %s incidencia(s) invalida(s) eliminada(s).", removed)
    except Exception as exc:
        logger.warning("No se pudo depurar incidencias invalidas: %s", exc)

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
