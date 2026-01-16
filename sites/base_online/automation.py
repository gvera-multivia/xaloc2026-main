from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineTarget
from sites.base_online.flows import ejecutar_login_base, navegar_a_rama, ejecutar_p1, ejecutar_p2, ejecutar_p3


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

            if datos.protocol.upper() == "P1":
                self.logger.info("\n" + "=" * 50)
                self.logger.info("FASE 3: FORMULARIO P1 (IDENTIFICACION)")
                self.logger.info("=" * 50)
                if not datos.p1:
                    raise ValueError("Faltan datos de P1.")
                await ejecutar_p1(self.page, datos.p1)

            if datos.protocol.upper() == "P2":
                self.logger.info("\n" + "=" * 50)
                self.logger.info("FASE 3: FORMULARIO P2 (ALEGACIONES)")
                self.logger.info("=" * 50)
                if not datos.p2:
                    raise ValueError("Faltan datos de P2.")
                await ejecutar_p2(self.page, datos.p2)

            if datos.protocol.upper() == "P3":
                self.logger.info("\n" + "=" * 50)
                self.logger.info("FASE 3: FORMULARIO P3 (REPOSICION)")
                self.logger.info("=" * 50)
                p3_data = datos.p3 or datos.reposicion
                if not p3_data:
                    raise ValueError("Faltan datos de P3.")
                await ejecutar_p3(self.page, self.config, p3_data)

            filename = f"base_online_{datos.protocol.lower()}.png"
            path = self.config.dir_screenshots / filename
            await self.page.screenshot(path=path, full_page=True)
            return str(Path(path))
        except Exception:
            await self.capture_error_screenshot("base_online_error.png")
            raise
