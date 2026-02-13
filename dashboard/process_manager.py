from __future__ import annotations

import asyncio
import sys
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ManagedProcess:
    name: str
    script: str
    process: asyncio.subprocess.Process
    stdout_path: Path
    stderr_path: Path
    stdout_handle: object
    stderr_handle: object


class ProcessManager:
    PROCESS_SCRIPTS = {
        "worker": "worker.py",
        "brain": "brain.py",
    }

    def __init__(self, *, base_dir: str = ".", logs_dir: str = "logs"):
        self.base_dir = Path(base_dir).resolve()
        self.logs_dir = Path(logs_dir).resolve()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._processes: dict[str, ManagedProcess] = {}

    @classmethod
    def is_valid_process_name(cls, name: str) -> bool:
        return str(name).strip().lower() in cls.PROCESS_SCRIPTS

    async def start_process(self, name: str) -> dict:
        process_name = str(name).strip().lower()
        if not self.is_valid_process_name(process_name):
            raise ValueError("process_name invalido. Usa 'worker' o 'brain'.")

        async with self._lock:
            current = self._processes.get(process_name)
            if current and current.process.returncode is None:
                return {"name": process_name, "status": "running", "started": False}

            script = self.PROCESS_SCRIPTS[process_name]
            script_path = self.base_dir / script
            if not script_path.exists():
                raise FileNotFoundError(f"No existe el script: {script_path}")

            stdout_path = self.logs_dir / f"{process_name}_out.log"
            stdout_handle = open(stdout_path, "a", encoding="utf-8")

            # Preparar argumentos de creacion de proceso para asegurar nuevo grupo
            kwargs = {}
            if sys.platform == "win32":
                # En Windows usamos CREATE_NEW_PROCESS_GROUP para poder enviar CTRL_BREAK_EVENT
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                # En Unix usamos start_new_session=True para crear un nuevo grupo de procesos
                kwargs["start_new_session"] = True

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                str(script_path),
                cwd=str(self.base_dir),
                stdout=stdout_handle,
                stderr=asyncio.subprocess.STDOUT,
                **kwargs
            )

            self._processes[process_name] = ManagedProcess(
                name=process_name,
                script=script,
                process=proc,
                stdout_path=stdout_path,
                stderr_path=stdout_path, # Ambas apuntan al mismo archivo ahora
                stdout_handle=stdout_handle,
                stderr_handle=None, # Solo usamos un handle
            )
            return {"name": process_name, "status": "running", "started": True, "pid": proc.pid}

    async def stop_process(self, name: str, timeout_seconds: float = 8.0) -> dict:
        process_name = str(name).strip().lower()
        if not self.is_valid_process_name(process_name):
            raise ValueError("process_name invalido. Usa 'worker' o 'brain'.")

        async with self._lock:
            current = self._processes.get(process_name)
            if not current:
                return {"name": process_name, "status": "stopped", "stopped": False}

            proc = current.process
            if proc.returncode is not None:
                self._close_handles(current)
                return {"name": process_name, "status": "stopped", "stopped": False}

            # Intentar parada graciosa (graceful shutdown)
            if sys.platform == "win32":
                # En Windows enviamos CTRL_BREAK_EVENT al grupo
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                except Exception:
                    # Si falla, intentamos terminate normal
                    proc.terminate()
            else:
                # En Unix enviamos SIGTERM al grupo de procesos
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass # Ya murio
                except Exception:
                    proc.terminate()

            killed = False
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                # Si no para, forzamos kill al grupo
                killed = True
                if sys.platform == "win32":
                    # En Windows usamos taskkill para asegurar arbol completo
                    try:
                        subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
                    except Exception:
                        proc.kill()
                else:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        proc.kill()

                # Esperar confirmacion final
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass # Ya deberia estar muerto

            self._close_handles(current)
            return {
                "name": process_name,
                "status": "stopped",
                "stopped": True,
                "killed": killed,
                "returncode": proc.returncode,
            }

    async def restart_process(self, name: str) -> dict:
        process_name = str(name).strip().lower()
        await self.stop_process(process_name)
        started = await self.start_process(process_name)
        return {"name": process_name, "status": "running", "restarted": True, "pid": started.get("pid")}

    async def stop_all(self) -> None:
        for name in list(self.PROCESS_SCRIPTS.keys()):
            try:
                await self.stop_process(name)
            except Exception:
                continue

    def get_status(self, name: str) -> str:
        process_name = str(name).strip().lower()
        if not self.is_valid_process_name(process_name):
            raise ValueError("process_name invalido. Usa 'worker' o 'brain'.")
        current = self._processes.get(process_name)
        if not current:
            return "stopped"
        rc = current.process.returncode
        if rc is None:
            return "running"
        if rc == 0:
            return "stopped"
        return "error"

    def get_all_status(self) -> dict[str, str]:
        return {name: self.get_status(name) for name in self.PROCESS_SCRIPTS}

    def get_logs(self, name: str, lines: int = 100) -> dict:
        process_name = str(name).strip().lower()
        if not self.is_valid_process_name(process_name):
            raise ValueError("process_name invalido. Usa 'worker' o 'brain'.")
        safe_lines = min(max(int(lines), 1), 2000)
        stdout_path = self.logs_dir / f"{process_name}_out.log"
        return {
            "name": process_name,
            "status": self.get_status(process_name),
            "lines": safe_lines,
            "stdout": self._tail_file(stdout_path, safe_lines),
            "stderr": [], # Ya no hay archivo de error separado
        }

    @staticmethod
    def _tail_file(path: Path, lines: int) -> list[str]:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            return [line.rstrip("\n") for line in all_lines[-lines:]]
        except Exception:
            return []

    def _close_handles(self, current: ManagedProcess) -> None:
        try:
            current.stdout_handle.flush()
        except Exception:
            pass
        try:
            current.stdout_handle.close()
        except Exception:
            pass
