from __future__ import annotations

import asyncio
from pathlib import Path

from core.base_automation import BaseAutomation
from .config import AtcConfig
from .data_models import AtcTarget
from .flows import run_login, run_formulario, run_documentos, run_confirmacion


class AtcAutomation(BaseAutomation):
    def __init__(self, config: AtcConfig):
        super().__init__(config)
        self.config = config

    async def _pause_before_close(self) -> None:
        self.logger.info("atc.flujo pause END (pulsa Enter en consola para cerrar navegador)")
        await asyncio.to_thread(
            input, "ATC flujo finalizado. Pulsa Enter para cerrar el navegador..."
        )

    async def ejecutar_flujo_completo(self, datos: AtcTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        shot = self.config.dir_screenshots / "atc_standalone.png"
        current_page = self.page
        try:
            self.logger.info(
                "atc.flujo START numclient=%s expediente=%s",
                datos.payload.get("numclient"),
                datos.expediente,
            )
            current_page = await run_login(current_page, self.config, datos)
            self.logger.info("atc.flujo login OK")
            current_page = await run_formulario(current_page, self.config, datos)
            self.logger.info("atc.flujo formulario OK")
            current_page = await run_documentos(current_page, self.config, datos)
            self.logger.info("atc.flujo documentos OK")
            current_page = await run_confirmacion(current_page, self.config, datos)
            self.logger.info("atc.flujo confirmacion OK")

            self.page = current_page
            await current_page.screenshot(path=shot, full_page=True)
            self.logger.info("atc.flujo END screenshot=%s", shot)
            return str(Path(shot))
        except Exception:
            # Guardar estado visual tambien en caso de error antes de cerrar.
            try:
                await current_page.screenshot(path=shot, full_page=True)
                self.logger.info("atc.flujo ERROR screenshot=%s", shot)
            except Exception:
                pass
            raise
        finally:
            await self._pause_before_close()
