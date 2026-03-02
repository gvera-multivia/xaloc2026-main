from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from sites.redsara.config import RedSaraConfig
from sites.redsara.data_models import RedSaraTarget
from sites.redsara.flows import (
    confirmar_y_firmar_redsara,
    descargar_justificante_redsara,
    ejecutar_login_redsara,
    rellenar_formulario_redsara,
    subir_documentacion_redsara,
)


class RedSaraAutomation(BaseAutomation):
    def __init__(self, config: RedSaraConfig):
        super().__init__(config)
        self.config: RedSaraConfig = config

    async def ejecutar_flujo_completo(self, datos: RedSaraTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.logger.info("=" * 60)
            self.logger.info("REDSARA FASE 1: LOGIN")
            self.logger.info("=" * 60)
            self.page = await ejecutar_login_redsara(self.page, self.config)
            await self.sync_screencast_with_page()

            self.logger.info("=" * 60)
            self.logger.info("REDSARA FASE 2: FORMULARIO")
            self.logger.info("=" * 60)
            self.page = await rellenar_formulario_redsara(self.page, self.config, datos)
            await self.sync_screencast_with_page()

            self.logger.info("=" * 60)
            self.logger.info("REDSARA FASE 3: DOCUMENTACION")
            self.logger.info("=" * 60)
            self.page = await subir_documentacion_redsara(self.page, self.config, datos)
            await self.sync_screencast_with_page()

            self.logger.info("=" * 60)
            self.logger.info("REDSARA FASE 4: FIRMA")
            self.logger.info("=" * 60)
            self.page = await confirmar_y_firmar_redsara(self.page, self.config)
            await self.sync_screencast_with_page()

            self.logger.info("=" * 60)
            self.logger.info("REDSARA FASE 5: JUSTIFICANTE")
            self.logger.info("=" * 60)
            final_pdf = await descargar_justificante_redsara(self.page, self.config, datos)

            final_screenshot = self.config.dir_screenshots / "redsara_final.png"
            await self.page.screenshot(path=final_screenshot, full_page=True)
            self.logger.info("redsara: justificante guardado en %s", final_pdf)
            return str(Path(final_screenshot))
        except Exception:
            await self.capture_error_screenshot("redsara_error.png")
            raise
