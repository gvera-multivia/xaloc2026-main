import logging
import sys
from pathlib import Path


def setup_worker_logging(run_id: str) -> logging.Logger:
    """Configura logging dual: INFO en terminal y DEBUG en archivo por ejecucion."""
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"worker_run_{run_id}.log"
    stable_log_path = logs_dir / "worker_out.log"

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    root.setLevel(logging.DEBUG)

    # Evita UnicodeEncodeError en consolas Windows cp1252 cuando se loguean
    # caracteres no representables (p. ej. flechas, emojis, etc.).
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s - [WORKER] - %(levelname)s - %(message)s")
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s"
        )
    )

    # Archivo estable para UI (/api/logs/worker)
    stable_file_handler = logging.FileHandler(stable_log_path, encoding="utf-8")
    stable_file_handler.setLevel(logging.DEBUG)
    stable_file_handler.setFormatter(
        logging.Formatter("%(asctime)s - [WORKER] - %(levelname)s - %(message)s")
    )

    root.addHandler(stream_handler)
    root.addHandler(file_handler)
    root.addHandler(stable_file_handler)

    logger = logging.getLogger("worker")
    logger.setLevel(logging.DEBUG)
    return logger
