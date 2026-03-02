from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from sites.redsara.config import RedsaraConfig
from sites.redsara.data_models import RedsaraTarget
from sites.redsara.flows import ejecutar_login_redsara, rellenar_formulario_redsara


class RedsaraAutomation(BaseAutomation):
    def __init__(self, config: RedsaraConfig):
        super().__init__(config)
        self.config: RedsaraConfig = config

    async def ejecutar_flujo_completo(self, datos: RedsaraTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("FASE 1: LOGIN CERTIFICADO + NUEVO REGISTRO")
            self.logger.info("=" * 60)
            self.page = await ejecutar_login_redsara(self.page, self.config)
            await self.sync_screencast_with_page()

            self.logger.info("\n" + "=" * 60)
            self.logger.info("FASE 2: RELLENADO PASO 1 (PRUEBA)")
            self.logger.info("=" * 60)
            await rellenar_formulario_redsara(self.page, self.config, datos)
            await self.sync_screencast_with_page()

            path = self.config.dir_screenshots / "redsara_step1_completo.png"
            await self.page.screenshot(path=path, full_page=True)
            self.logger.info("Screenshot guardado: %s", path)
            return str(Path(path))
        except Exception:
            await self.capture_error_screenshot("redsara_error.png")
            raise
