"""
Lanzador Windows (sin terminal) para ejecutar worker.py con el Python del venv.

Motivo:
- Empaquetar Playwright en un .exe "standalone" puede fallar o ser pesado.
- Este launcher es ligero: solo arranca `worker.py` en el repo y no abre consola.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _message_box(title: str, message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for _ in range(6):
        if (current / "worker.py").exists() and (current / "core").is_dir() and (current / "sites").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def main() -> int:
    base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    repo_root = _find_repo_root(base_dir)
    if repo_root is None:
        _message_box("Xaloc Worker", f"No se encuentra el repo (worker.py) desde: {base_dir}")
        return 2

    venv_python = repo_root / "venv" / "Scripts" / "python.exe"
    python_exe = str(venv_python) if venv_python.exists() else "python"

    worker_py = repo_root / "worker.py"
    if not worker_py.exists():
        _message_box("Xaloc Worker", f"No existe: {worker_py}")
        return 2

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    try:
        subprocess.Popen(
            [python_exe, str(worker_py)],
            cwd=str(repo_root),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        _message_box("Xaloc Worker", f"No se pudo lanzar el worker.\n\n{type(e).__name__}: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

