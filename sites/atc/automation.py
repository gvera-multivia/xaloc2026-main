from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from .config import AtcConfig
from .data_models import AtcTarget
from .flows import run_login, run_formulario, run_documentos, run_confirmacion


class AtcAutomation(BaseAutomation):
    def __init__(self, config: AtcConfig):
        super().__init__(config)
        self.config = config

    async def ejecutar_flujo_completo(self, datos: AtcTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.page = await run_login(self.page, self.config, datos)
            self.page = await run_formulario(self.page, self.config, datos)
            self.page = await run_documentos(self.page, self.config, datos)
            self.page = await run_confirmacion(self.page, self.config, datos)

            shot = self.config.dir_screenshots / "atc_standalone.png"
            await self.page.screenshot(path=shot, full_page=True)
            return str(Path(shot))
        except Exception:
            await self.capture_error_screenshot("atc_error.png")
            raise
