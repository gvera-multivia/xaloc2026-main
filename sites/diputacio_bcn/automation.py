from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from .config import DiputacioBcnConfig
from .data_models import DiputacioBcnTarget
from .flows import run_login, run_formulario, run_documentos, run_confirmacion, run_presentmul_pas2


class DiputacioBcnAutomation(BaseAutomation):
    def __init__(self, config: DiputacioBcnConfig):
        super().__init__(config)
        self.config = config

    async def ejecutar_flujo_completo(self, datos: DiputacioBcnTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        self.page = await run_login(self.page, self.config, datos)
        self.page = await run_formulario(self.page, self.config, datos)
        self.page = await run_documentos(self.page, self.config, datos)
        self.page = await run_confirmacion(self.page, self.config, datos)
        self.page = await run_presentmul_pas2(self.page, self.config, datos)

        shot = self.config.dir_screenshots / f"diputacio_bcn_standalone.png"
        await self.page.screenshot(path=shot, full_page=True)
        return str(Path(shot))
