from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineTarget
from sites.base_online.flows import ejecutar_login_base, navegar_a_rama


class BaseOnlineAutomation(BaseAutomation):
    def __init__(self, config: BaseOnlineConfig):
        super().__init__(config)
        self.config: BaseOnlineConfig = config

    async def ejecutar_flujo_completo(self, datos: BaseOnlineTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 1: LOGIN + COMMON DESKTOP")
            self.logger.info("=" * 50)
            self.page = await ejecutar_login_base(self.page, self.config)

            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 2: RAMIFICACION (P1/P2/P3)")
            self.logger.info("=" * 50)
            await navegar_a_rama(self.page, datos)

            filename = f"base_online_{datos.protocol.lower()}.png"
            path = self.config.dir_screenshots / filename
            await self.page.screenshot(path=path, full_page=True)
            return str(Path(path))
        except Exception:
            await self.capture_error_screenshot("base_online_error.png")
            raise

