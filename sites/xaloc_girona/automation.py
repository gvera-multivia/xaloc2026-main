from __future__ import annotations

from core.base_automation import BaseAutomation
from sites.xaloc_girona.config import XalocConfig
from sites.xaloc_girona.data_models import DatosMulta
from sites.xaloc_girona.flows import (
    confirmar_tramite,
    ejecutar_login,
    rellenar_formulario,
    subir_documento,
)


class XalocGironaAutomation(BaseAutomation):
    def __init__(self, config: XalocConfig):
        super().__init__(config)
        self.config: XalocConfig = config

    async def ejecutar_flujo_completo(self, datos: DatosMulta) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 1: AUTENTICACION")
            self.logger.info("=" * 50)
            self.page = await ejecutar_login(self.page, self.config)

            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 2: RELLENADO DE FORMULARIO")
            self.logger.info("=" * 50)
            await rellenar_formulario(self.page, datos)

            archivos = datos.archivos_para_subir
            if archivos:
                self.logger.info("\n" + "=" * 50)
                self.logger.info(f"FASE 3: SUBIDA DE {len(archivos)} DOCUMENTO(S)")
                self.logger.info("=" * 50)
                await subir_documento(self.page, archivos)
            else:
                self.logger.info("FASE 3: Saltada (no hay archivos adjuntos)")

            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 4: CONFIRMACION")
            self.logger.info("=" * 50)
            return await confirmar_tramite(self.page, self.config.dir_screenshots)

        except Exception:
            await self.capture_error_screenshot("error.png")
            raise

