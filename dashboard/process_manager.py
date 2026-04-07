from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from core.process_launcher import start_async_process, terminate_process_tree


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
    DOCKER_CONTAINERS = {
        "worker": "xaloc-worker-orchestrator",
        "brain": "xaloc-brain-claim",
    }

    def __init__(self, *, base_dir: str = ".", logs_dir: str = "logs"):
        self.base_dir = Path(base_dir).resolve()
        self.logs_dir = Path(logs_dir).resolve()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._processes: dict[str, ManagedProcess] = {}
        self._docker_socket = Path("/var/run/docker.sock")

    def _docker_available(self) -> bool:
        return self._docker_socket.exists()

    def _docker_request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        expected_statuses: tuple[int, ...] = (200, 204, 304),
    ) -> tuple[int, object | None]:
        if not self._docker_available():
            raise RuntimeError("docker socket not available")

        payload = body or b""
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            "Host: docker\r\n"
            "Connection: close\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "\r\n"
        ).encode("utf-8") + payload

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(self._docker_socket))
            sock.sendall(request)
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            sock.close()

        raw = b"".join(chunks)
        header, _, body_bytes = raw.partition(b"\r\n\r\n")
        header_text = header.decode("utf-8", errors="replace")
        header_lines = header_text.splitlines()
        if not header_lines:
            raise RuntimeError("empty docker response")
        parts = header_lines[0].split()
        status_code = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 500
        if status_code not in expected_statuses:
            return status_code, body_bytes.decode("utf-8", errors="replace")
        if "transfer-encoding: chunked" in header_text.lower():
            body_bytes = self._decode_chunked_body(body_bytes)
        if not body_bytes:
            return status_code, None
        try:
            return status_code, json.loads(body_bytes.decode("utf-8", errors="replace"))
        except Exception:
            return status_code, body_bytes.decode("utf-8", errors="replace")

    @staticmethod
    def _decode_chunked_body(body: bytes) -> bytes:
        out = bytearray()
        rest = body
        while rest:
            line, sep, remainder = rest.partition(b"\r\n")
            if not sep:
                break
            size_token = line.split(b";", 1)[0].strip()
            try:
                size = int(size_token.decode("ascii", errors="replace") or "0", 16)
            except Exception:
                break
            if size <= 0:
                break
            chunk = remainder[:size]
            out.extend(chunk)
            rest = remainder[size + 2 :]
        return bytes(out)

    def _inspect_docker_container(self, process_name: str) -> dict | None:
        container_name = self.DOCKER_CONTAINERS.get(process_name)
        if not container_name or not self._docker_available():
            return None
        status, data = self._docker_request(
            "GET",
            f"/containers/{quote(container_name, safe='')}/json",
            expected_statuses=(200, 404),
        )
        if status == 404 or not isinstance(data, dict):
            return None
        return data

    def _docker_status(self, process_name: str) -> Optional[str]:
        info = self._inspect_docker_container(process_name)
        if not info:
            return None
        state = info.get("State") or {}
        if bool(state.get("Running")):
            return "running"
        raw_status = str(state.get("Status") or "").strip().lower()
        if raw_status in {"created", "exited", "dead"}:
            exit_code = state.get("ExitCode")
            return "stopped" if exit_code in (0, None) else "error"
        return "stopped"

    def _docker_pid(self, process_name: str) -> Optional[int]:
        info = self._inspect_docker_container(process_name)
        if not info:
            return None
        state = info.get("State") or {}
        try:
            pid = int(state.get("Pid") or 0)
        except Exception:
            return None
        return pid or None

    async def _docker_start(self, process_name: str) -> dict:
        container_name = self.DOCKER_CONTAINERS[process_name]
        status, payload = self._docker_request(
            "POST",
            f"/containers/{quote(container_name, safe='')}/start",
            expected_statuses=(204, 304, 404),
        )
        if status == 404:
            raise FileNotFoundError(f"Contenedor no encontrado: {container_name}")
        return {
            "name": process_name,
            "status": self._docker_status(process_name) or "running",
            "started": status == 204,
            "external": True,
            "container": container_name,
            "pid": self._docker_pid(process_name),
            "message": payload,
        }

    async def _docker_stop(self, process_name: str, timeout_seconds: float) -> dict:
        container_name = self.DOCKER_CONTAINERS[process_name]
        timeout = max(1, int(timeout_seconds))
        status, payload = self._docker_request(
            "POST",
            f"/containers/{quote(container_name, safe='')}/stop?t={timeout}",
            expected_statuses=(204, 304, 404),
        )
        if status == 404:
            raise FileNotFoundError(f"Contenedor no encontrado: {container_name}")
        return {
            "name": process_name,
            "status": self._docker_status(process_name) or "stopped",
            "stopped": status == 204,
            "external": True,
            "container": container_name,
            "message": payload,
        }

    async def _docker_restart(self, process_name: str, timeout_seconds: float) -> dict:
        container_name = self.DOCKER_CONTAINERS[process_name]
        timeout = max(1, int(timeout_seconds))
        status, payload = self._docker_request(
            "POST",
            f"/containers/{quote(container_name, safe='')}/restart?t={timeout}",
            expected_statuses=(204, 404),
        )
        if status == 404:
            raise FileNotFoundError(f"Contenedor no encontrado: {container_name}")
        return {
            "name": process_name,
            "status": self._docker_status(process_name) or "running",
            "restarted": status == 204,
            "external": True,
            "container": container_name,
            "pid": self._docker_pid(process_name),
            "message": payload,
        }

    def _find_external_pids(self, process_name: str) -> list[int]:
        script = self.PROCESS_SCRIPTS[process_name]
        script_path = str((self.base_dir / script).resolve())
        me = os.getpid()
        found: list[int] = []
        try:
            out = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True, stderr=subprocess.DEVNULL)
        except Exception:
            return found

        for raw in out.splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            try:
                pid = int(parts[0])
            except Exception:
                continue
            if pid == me:
                continue
            args = parts[1]
            if "python" not in args:
                continue
            if script_path in args or f"/{script}" in args or f" {script}" in args:
                found.append(pid)
        return found

    @classmethod
    def is_valid_process_name(cls, name: str) -> bool:
        return str(name).strip().lower() in cls.PROCESS_SCRIPTS

    async def start_process(self, name: str) -> dict:
        process_name = str(name).strip().lower()
        if not self.is_valid_process_name(process_name):
            raise ValueError("process_name invalido. Usa 'worker' o 'brain'.")

        async with self._lock:
            docker_status = self._docker_status(process_name)
            if docker_status == "running":
                return {
                    "name": process_name,
                    "status": "running",
                    "started": False,
                    "external": True,
                    "container": self.DOCKER_CONTAINERS.get(process_name),
                    "pid": self._docker_pid(process_name),
                }
            if docker_status in {"stopped", "error"}:
                return await self._docker_start(process_name)

            current = self._processes.get(process_name)
            if current and current.process.returncode is None:
                return {"name": process_name, "status": "running", "started": False}
            external = self._find_external_pids(process_name)
            if external:
                return {
                    "name": process_name,
                    "status": "running",
                    "started": False,
                    "external": True,
                    "pids": external,
                }

            script = self.PROCESS_SCRIPTS[process_name]
            script_path = self.base_dir / script
            if not script_path.exists():
                raise FileNotFoundError(f"No existe el script: {script_path}")

            stdout_path = self.logs_dir / f"{process_name}_out.log"
            stdout_handle = open(stdout_path, "a", encoding="utf-8")

            cmd = [sys.executable, "-u", str(script_path)]

            proc = await start_async_process(
                cmd,
                cwd=str(self.base_dir),
                stdout=stdout_handle,
                stderr=asyncio.subprocess.STDOUT,
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
            docker_status = self._docker_status(process_name)
            if docker_status is not None:
                return await self._docker_stop(process_name, timeout_seconds)

            current = self._processes.get(process_name)
            if not current:
                external = self._find_external_pids(process_name)
                if not external:
                    return {"name": process_name, "status": "stopped", "stopped": False}

                stopped_any = False
                killed_any = False
                for pid in external:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        stopped_any = True
                    except Exception:
                        continue

                deadline = time.time() + timeout_seconds
                while time.time() < deadline:
                    alive = self._find_external_pids(process_name)
                    if not alive:
                        break
                    await asyncio.sleep(0.2)

                alive = self._find_external_pids(process_name)
                for pid in alive:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        killed_any = True
                    except Exception:
                        continue

                return {
                    "name": process_name,
                    "status": "stopped",
                    "stopped": stopped_any,
                    "killed": killed_any,
                    "external": True,
                }

            result = await terminate_process_tree(current.process, timeout=timeout_seconds)
            self._close_handles(current)

            return {
                "name": process_name,
                "status": "stopped",
                "stopped": result.get("stopped", False),
                "killed": result.get("killed", False),
                "returncode": result.get("returncode"),
            }

    async def restart_process(self, name: str) -> dict:
        process_name = str(name).strip().lower()
        docker_status = self._docker_status(process_name)
        if docker_status is not None:
            return await self._docker_restart(process_name, timeout_seconds=8.0)
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
        docker_status = self._docker_status(process_name)
        if docker_status is not None:
            return docker_status
        current = self._processes.get(process_name)
        if not current:
            external = self._find_external_pids(process_name)
            return "running" if external else "stopped"
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
            if lines <= 0:
                return []

            block_size = 64 * 1024
            remaining = int(lines)
            chunks: list[bytes] = []

            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                position = file_size

                while position > 0 and remaining >= 0:
                    read_size = min(block_size, position)
                    position -= read_size
                    f.seek(position)
                    chunk = f.read(read_size)
                    chunks.append(chunk)
                    remaining -= chunk.count(b"\n")

            data = b"".join(reversed(chunks))
            text = data.decode("utf-8", errors="replace")
            return [line.rstrip("\r") for line in text.splitlines()[-lines:]]
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
