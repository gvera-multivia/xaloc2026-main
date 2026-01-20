from __future__ import annotations

from core.base_automation import BaseAutomation
from sites.selva.config import SelvaConfig
from sites.selva.data_models import DatosSolicitud
from sites.selva.flows.navigation import navegar_a_formulario
from sites.selva.flows.form import rellenar_formulario
from sites.selva.flows.upload import subir_adjuntos


class SelvaAutomation(BaseAutomation):
    def __init__(self, config: SelvaConfig):
        super().__init__(config)
        self.config: SelvaConfig = config

    async def ejecutar_flujo_completo(self, datos: DatosSolicitud) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 1: NAVEGACION")
            self.logger.info("=" * 50)
            await navegar_a_formulario(self.page, self.config.url_base)

            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 2: RELLENADO DE FORMULARIO")
            self.logger.info("=" * 50)
            await rellenar_formulario(self.page, datos)

            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 3: SUBIDA DE ADJUNTOS Y CONTINUACION")
            self.logger.info("=" * 50)
            await subir_adjuntos(self.page, datos.attachments)

            self.logger.info("Flujo completado exitosamente.")
            return "OK"

        except Exception:
            await self.capture_error_screenshot("error_selva.png")
            raise
