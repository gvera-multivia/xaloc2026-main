from __future__ import annotations

import asyncio
from pathlib import Path

from core.base_automation import BaseAutomation
from .config import AjuntamentBarcelonaConfig
from .data_models import AjuntamentBarcelonaTarget
from .flows import run_login, run_formulario, run_documentos, run_confirmacion, run_multes


class AjuntamentBarcelonaAutomation(BaseAutomation):
    def __init__(self, config: AjuntamentBarcelonaConfig):
        super().__init__(config)
        self.config = config

    async def _pause_before_close(self) -> None:
        self.logger.info("ajuntament_barcelona.flujo pause END (pulsa Enter en consola para cerrar navegador)")
        await asyncio.to_thread(
            input, "Ajuntament Barcelona flujo finalizado. Pulsa Enter para cerrar el navegador..."
        )

    async def ejecutar_flujo_completo(self, datos: AjuntamentBarcelonaTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        shot = self.config.dir_screenshots / "ajuntament_barcelona_standalone.png"
        try:
            current_page = self.page
            self.logger.info(
                "ajuntament_barcelona.flujo START numclient=%s expediente=%s",
                datos.payload.get("numclient"),
                datos.expediente,
            )
            current_page = await run_login(current_page, self.config, datos)
            self.logger.info("ajuntament_barcelona.flujo login OK")
            current_page = await run_formulario(current_page, self.config, datos)
            self.logger.info("ajuntament_barcelona.flujo formulario OK")
            current_page = await run_documentos(current_page, self.config, datos)
            self.logger.info("ajuntament_barcelona.flujo documentos OK")
            current_page = await run_confirmacion(current_page, self.config, datos)
            self.logger.info("ajuntament_barcelona.flujo confirmacion OK")
            current_page = await run_multes(current_page, self.config, datos)
            self.logger.info("ajuntament_barcelona.flujo multes OK")

            self.page = current_page
            await current_page.screenshot(path=shot, full_page=True)
            self.logger.info("ajuntament_barcelona.flujo END screenshot=%s", shot)
            return str(Path(shot))
        except Exception:
            try:
                await self.page.screenshot(path=shot, full_page=True)
                self.logger.info("ajuntament_barcelona.flujo ERROR screenshot=%s", shot)
            except Exception:
                pass
            raise
        finally:
            await self._pause_before_close()
