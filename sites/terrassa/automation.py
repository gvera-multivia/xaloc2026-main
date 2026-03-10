from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from .config import TerrassaConfig
from .data_models import TerrassaTarget
from .flows import run_login, run_formulario, run_documentos, run_confirmacion, run_firma_y_justificante


class TerrassaAutomation(BaseAutomation):
    def __init__(self, config: TerrassaConfig):
        super().__init__(config)
        self.config = config

    async def ejecutar_flujo_completo(self, datos: TerrassaTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.page = await run_login(self.page, self.config, datos)
            self.page = await run_formulario(self.page, self.config, datos)
            self.page = await run_documentos(self.page, self.config, datos)
            self.page = await run_confirmacion(self.page, self.config, datos)

            # Signing + receipt download
            self.page, justificante_path = await run_firma_y_justificante(self.page, self.config, datos)

            # Store metadata for upstream consumption
            self.last_flow_metadata = {}
            if justificante_path:
                self.last_flow_metadata["justificante_path"] = justificante_path

            shot = self.config.dir_screenshots / "terrassa_standalone.png"
            await self.page.screenshot(path=shot, full_page=True)
            return str(Path(shot))
        except Exception:
            await self.capture_error_screenshot("terrassa_error.png")
            raise
