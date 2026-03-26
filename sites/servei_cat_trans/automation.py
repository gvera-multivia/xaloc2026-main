from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from .config import ServeiCatTransConfig
from .data_models import ServeiCatTransTarget
from .flows import run_login, run_formulario, run_documentos, run_confirmacion


class ServeiCatTransAutomation(BaseAutomation):
    def __init__(self, config: ServeiCatTransConfig):
        super().__init__(config)
        self.config = config

    async def ejecutar_flujo_completo(self, datos: ServeiCatTransTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.page = await run_login(self.page, self.config, datos)
            self.page = await run_formulario(self.page, self.config, datos)
            self.page = await run_documentos(self.page, self.config, datos)
            self.page = await run_confirmacion(self.page, self.config, datos)

            shot = self.config.dir_screenshots / "servei_cat_trans_standalone.png"
            await self.page.screenshot(path=shot, full_page=True)
            return str(Path(shot))
        except Exception:
            await self.capture_error_screenshot("servei_cat_trans_error.png")
            raise
        finally:
            import os
            is_smoke = datos.payload.get("smoke") or os.getenv("XALOC_SMOKE") == "1"
            if is_smoke or self.config.navegador.headless is False:
                import asyncio
                import logging
                logger = logging.getLogger("xaloc_automation.servei_cat_trans")
                logger.info("Modo smoke/debug detectado (finally): manteniendo el navegador abierto indefinidamente...")
                while True:
                    await asyncio.sleep(3600)
