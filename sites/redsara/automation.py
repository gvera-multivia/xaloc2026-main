from __future__ import annotations

from pathlib import Path

from core.autofirma_shared import (
    prepare_autofirma_context,
    prewarm_autofirma_process,
    stop_autofirma_prewarm,
    wait_autofirma_prewarm_ready,
)
from core.base_automation import BaseAutomation
from sites.redsara.config import RedsaraConfig
from sites.redsara.data_models import RedsaraTarget
from sites.redsara.flows import ejecutar_login_redsara, rellenar_formulario_redsara


class RedsaraAutomation(BaseAutomation):
    def __init__(self, config: RedsaraConfig):
        super().__init__(config)
        self.config: RedsaraConfig = config
        self.last_flow_metadata: dict = {}

    async def ejecutar_flujo_completo(self, datos: RedsaraTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")
        prewarm_proc = None

        try:
            if self.context is not None:
                await prepare_autofirma_context(self.context, logger=self.logger)
                prewarm_proc = prewarm_autofirma_process(self.logger)
                if prewarm_proc:
                    await wait_autofirma_prewarm_ready(prewarm_proc, timeout_ms=5000, logger=self.logger)

            self.logger.info("\n" + "=" * 60)
            self.logger.info("FASE 1: LOGIN CERTIFICADO + NUEVO REGISTRO")
            self.logger.info("=" * 60)
            self.page = await ejecutar_login_redsara(self.page, self.config)
            await self.sync_screencast_with_page()

            self.logger.info("\n" + "=" * 60)
            self.logger.info("FASE 2: RELLENADO PASO 1 (PRUEBA)")
            self.logger.info("=" * 60)
            self.last_flow_metadata = await rellenar_formulario_redsara(
                self.page,
                self.config,
                datos,
                prewarm_proc=prewarm_proc,
            ) or {}
            await self.sync_screencast_with_page()

            path = self.config.dir_screenshots / "redsara_step1_completo.png"
            await self.page.screenshot(path=path, full_page=True)
            self.logger.info("Screenshot guardado: %s", path)
            return str(Path(path))
        except Exception:
            await self.capture_error_screenshot("redsara_error.png")
            raise
        finally:
            stop_autofirma_prewarm(prewarm_proc, logger=self.logger)
