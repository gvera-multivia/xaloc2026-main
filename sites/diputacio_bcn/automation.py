from __future__ import annotations

import asyncio
from pathlib import Path

from core.base_automation import BaseAutomation
from .config import DiputacioBcnConfig
from .data_models import DiputacioBcnTarget
from .flows import run_login, run_formulario, run_documentos, run_confirmacion, run_presentmul_pas2


class DiputacioBcnAutomation(BaseAutomation):
    def __init__(self, config: DiputacioBcnConfig):
        super().__init__(config)
        self.config = config
        self.last_flow_metadata: dict = {}

    async def ejecutar_flujo_completo(self, datos: DiputacioBcnTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")
        self.last_flow_metadata = {"diputacio_justificante_descargado": False}

        async def _run_step(name: str, coro, timeout_s: int):
            try:
                return await asyncio.wait_for(coro, timeout=timeout_s)
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    f"Diputacio BCN: timeout en etapa '{name}' tras {timeout_s}s (sin progreso)."
                ) from exc

        self.page = await _run_step("login", run_login(self.page, self.config, datos), 180)
        self.page = await _run_step("formulario", run_formulario(self.page, self.config, datos), 240)
        self.page = await _run_step("documentos", run_documentos(self.page, self.config, datos), 360)
        self.page = await _run_step("confirmacion", run_confirmacion(self.page, self.config, datos), 180)
        self.page = await _run_step("presentmul_pas2", run_presentmul_pas2(self.page, self.config, datos), 180)
        self.last_flow_metadata = {
            "diputacio_justificante_descargado": bool(
                datos.payload.get("diputacio_justificante_descargado", False)
            ),
            "diputacio_justificante_path": str(datos.payload.get("diputacio_justificante_path") or ""),
            "diputacio_justificante_artifact_path": str(
                datos.payload.get("diputacio_justificante_artifact_path") or ""
            ),
        }

        shot = self.config.dir_screenshots / f"diputacio_bcn_standalone.png"
        await self.page.screenshot(path=shot, full_page=True)
        return str(Path(shot))
