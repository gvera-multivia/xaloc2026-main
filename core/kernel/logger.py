import sys
import logging
from pathlib import Path
from typing import Optional

def setup_logging(
    name: str,
    log_dir: str = "logs",
    level: int = logging.INFO,
    console: bool = True
) -> logging.Logger:
    """
    Configures a logger with standard formatting and file/console handlers.

    Args:
        name: Name of the logger (e.g. 'worker', 'brain').
        log_dir: Directory to store log files.
        level: Logging level.
        console: Whether to log to stdout.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding duplicate handlers if logger is reused
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(f"{log_dir}/{name}.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if console:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger
