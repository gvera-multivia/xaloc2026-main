from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DashboardRestarter:
    def __init__(self, *, base_dir: str | Path):
        self.base_dir = Path(base_dir).resolve()
        self._lock = asyncio.Lock()
        self._restarting = False
        self._last_scheduled_at: str | None = None

    def status(self) -> dict[str, Any]:
        return {
            "restarting": self._restarting,
            "last_scheduled_at": self._last_scheduled_at,
        }

    async def schedule_restart(self, *, delay_seconds: float = 1.0) -> dict[str, Any]:
        safe_delay = max(0.2, min(10.0, float(delay_seconds)))
        async with self._lock:
            if self._restarting:
                raise RuntimeError("Ya hay un reinicio del dashboard en curso.")
            self._restarting = True
            self._last_scheduled_at = datetime.now(timezone.utc).isoformat()
            asyncio.create_task(self._restart_after_delay(safe_delay))
            return {
                "scheduled": True,
                "delay_seconds": safe_delay,
                "scheduled_at": self._last_scheduled_at,
            }

    async def _restart_after_delay(self, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)
        os.chdir(str(self.base_dir))
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, [sys.executable, *sys.argv])
