from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dashboard.process_manager import ProcessManager
from dashboard.services import DashboardService


class UpdateManager:
    def __init__(
        self,
        *,
        base_dir: str | Path,
        service: DashboardService,
        process_manager: ProcessManager,
    ):
        self.base_dir = Path(base_dir).resolve()
        self.service = service
        self.process_manager = process_manager
        self.logger = logging.getLogger("dashboard.update")
        self._lock = asyncio.Lock()
        self._running = False
        self._last_result: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "last_result": self._last_result,
        }

    async def check_for_updates(self) -> dict[str, Any]:
        fetch = await self._git_cmd("fetch", "--prune")
        if int(fetch.get("returncode", 1)) != 0:
            raise RuntimeError(
                "git fetch --prune fallo. Revisa conexion y credenciales remotas."
            )

        branch_cmd = await self._git_cmd("rev-parse", "--abbrev-ref", "HEAD")
        if int(branch_cmd.get("returncode", 1)) != 0:
            raise RuntimeError("No se pudo resolver la rama actual (git rev-parse --abbrev-ref HEAD).")
        branch = (branch_cmd.get("stdout") or "").strip()
        if not branch:
            raise RuntimeError("No se pudo resolver la rama actual.")

        ahead, behind = await self._git_ahead_behind()
        return {
            "branch": branch,
            "ahead": ahead,
            "behind": behind,
            "up_to_date": behind == 0,
            "update_available": behind > 0,
            "diverged": ahead > 0 and behind > 0,
        }

    async def run_update(
        self,
        *,
        wait_timeout_seconds: int = 1800,
        poll_seconds: float = 2.0,
    ) -> dict[str, Any]:
        if self._lock.locked():
            raise RuntimeError("Ya hay una actualizacion en curso.")

        async with self._lock:
            self._running = True
            started_at = datetime.now(timezone.utc).isoformat()
            result: dict[str, Any] = {
                "started_at": started_at,
                "updated": False,
                "up_to_date": False,
                "queues_paused": [],
                "stopped_processes": {},
            }
            try:
                check = await self.check_for_updates()
                result["check"] = check
                if check.get("up_to_date"):
                    result["up_to_date"] = True
                    result["updated"] = False
                    return result
                if check.get("diverged"):
                    raise RuntimeError(
                        "La rama local y remota han divergido (ahead/behind). "
                        "No se puede aplicar update automatico con --ff-only."
                    )

                paused = self._pause_all_sites(reason="Actualizacion en curso")
                result["queues_paused"] = sorted(paused)

                wait_data = await self._wait_until_no_processing(
                    timeout_seconds=max(1, int(wait_timeout_seconds)),
                    poll_seconds=max(0.2, float(poll_seconds)),
                )
                result["wait_processing"] = wait_data

                stop_worker = await self.process_manager.stop_process("worker")
                stop_brain = await self.process_manager.stop_process("brain")
                result["stopped_processes"] = {
                    "worker": stop_worker,
                    "brain": stop_brain,
                }

                pull = await self._git_cmd("pull", "--ff-only")
                result["git_pull"] = pull
                if int(pull.get("returncode", 1)) != 0:
                    raise RuntimeError(
                        "git pull --ff-only fallo. Revisa git_pull.stdout/git_pull.stderr."
                    )

                # BUILD FRONTEND
                frontend_dir = self.base_dir / "dashboard-frontend"
                if frontend_dir.exists():
                    self.logger.info("Construyendo frontend...")
                    npm_install = await self._run_cmd("cmd", "/c", "npm", "install", cwd=frontend_dir)
                    result["npm_install"] = npm_install
                    
                    npm_build = await self._run_cmd("cmd", "/c", "npm", "run", "build", cwd=frontend_dir)
                    result["npm_build"] = npm_build
                    
                    if int(npm_build.get("returncode", 1)) != 0:
                        raise RuntimeError(
                            "Fallo la compilacion del frontend (npm run build). "
                            "Revisa npm_build.stderr."
                        )

                result["updated"] = True
                result["up_to_date"] = False
                result["requires_dashboard_restart"] = True
                return result
            finally:
                result["finished_at"] = datetime.now(timezone.utc).isoformat()
                self._last_result = result
                self._running = False

    def _pause_all_sites(self, *, reason: str) -> set[str]:
        site_ids: set[str] = set()

        try:
            configs = self.service.list_organismo_configs()
            for item in configs:
                site = str((item or {}).get("site_id") or "").strip()
                if site:
                    site_ids.add(site)
        except Exception as exc:
            self.logger.warning("No se pudieron listar sites de organismo_config: %s", exc)

        try:
            current = self.service.list_queue_current(day=None, page=1, page_size=10000)
            for item in list(current.get("items") or []):
                site = str((item or {}).get("site_id") or "").strip()
                if site:
                    site_ids.add(site)
        except Exception as exc:
            self.logger.warning("No se pudieron listar sites en cola activa: %s", exc)

        for site in sorted(site_ids):
            try:
                self.service.pause_site_processing(site_id=site, reason=reason, minutes=None)
            except Exception as exc:
                self.logger.warning("No se pudo pausar site %s durante update: %s", site, exc)
        return site_ids

    async def _wait_until_no_processing(
        self,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> dict[str, Any]:
        started = asyncio.get_running_loop().time()
        iterations = 0

        while True:
            iterations += 1
            processing = self._count_processing_items()
            if processing <= 0:
                elapsed = asyncio.get_running_loop().time() - started
                return {
                    "waited": True,
                    "timed_out": False,
                    "processing_count": 0,
                    "elapsed_seconds": round(elapsed, 3),
                    "iterations": iterations,
                }

            elapsed = asyncio.get_running_loop().time() - started
            if elapsed >= timeout_seconds:
                raise TimeoutError(
                    f"Timeout esperando fin de processing ({processing} items aun en curso)."
                )
            await asyncio.sleep(poll_seconds)

    def _count_processing_items(self) -> int:
        current = self.service.list_queue_current(day=None, page=1, page_size=10000)
        items = list(current.get("items") or [])
        return int(sum(1 for item in items if str((item or {}).get("state") or "").strip().lower() == "processing"))

    async def _git_ahead_behind(self) -> tuple[int, int]:
        out = await self._git_cmd("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        if int(out.get("returncode", 1)) != 0:
            raise RuntimeError(
                "No se pudo calcular ahead/behind contra upstream. "
                "Asegura que la rama actual tenga upstream configurado."
            )
        raw = (out.get("stdout") or "").strip()
        parts = [p for p in raw.replace("\t", " ").split(" ") if p]
        if len(parts) < 2:
            raise RuntimeError(f"Salida inesperada en rev-list ahead/behind: '{raw}'")
        ahead = int(parts[0])
        behind = int(parts[1])
        return ahead, behind

    async def _git_cmd(self, *args: str) -> dict[str, Any]:
        return await self._run_cmd("git", *args)

    async def _run_cmd(self, executable: str, *args: str, cwd: Path | str | None = None) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            executable,
            *args,
            cwd=str(cwd or self.base_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        return {
            "command": executable + " " + " ".join(args),
            "returncode": int(proc.returncode or 0),
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
        }
