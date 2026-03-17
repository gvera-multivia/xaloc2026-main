from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from pathlib import Path

from core.base_automation import BaseAutomation

from .config import ValenciaConfig
from .data_models import ValenciaTarget
from .flows import run_confirmacion, run_documentos, run_formulario, run_login


class ValenciaAutomation(BaseAutomation):
    def __init__(self, config: ValenciaConfig):
        super().__init__(config)
        self.config = config

    async def ejecutar_flujo_completo(self, datos: ValenciaTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.logger.info(
                "valencia.automation START idRecurso=%s expediente=%s tramite=%s code=%s",
                datos.idRecurso,
                datos.expediente,
                datos.tramite_tipo,
                datos.tramite_code,
            )
            self.page = await run_login(self.page, self.config, datos)
            self.page = await run_formulario(self.page, self.config, datos)
            self.page = await run_documentos(self.page, self.config, datos)
            self.page = await run_confirmacion(self.page, self.config, datos)

            shot = self.config.dir_screenshots / "valencia_standalone.png"
            await self.page.screenshot(path=shot, full_page=True)
            sleep_seconds = int((os.getenv("VALENCIA_POST_RUN_SLEEP_SECONDS") or "0").strip() or "0")
            if sleep_seconds > 0:
                self.logger.info("valencia.automation DEBUG sleep=%ss antes de cerrar navegador", sleep_seconds)
                await asyncio.sleep(sleep_seconds)
            self.logger.info("valencia.automation END screenshot=%s", shot)
            return str(Path(shot))
        except Exception:
            try:
                snapshot = asdict(datos)
            except Exception:
                snapshot = {"idRecurso": getattr(datos, "idRecurso", None), "expediente": getattr(datos, "expediente", "")}
            self.logger.exception("valencia.automation ERROR datos=%s", snapshot)
            await self.capture_error_screenshot("valencia_error.png")
            raise
