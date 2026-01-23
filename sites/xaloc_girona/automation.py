from __future__ import annotations

from core.base_automation import BaseAutomation
from sites.xaloc_girona.config import XalocConfig
from sites.xaloc_girona.data_models import DatosMulta
from sites.xaloc_girona.flows.confirmacion import confirmar_tramite
from sites.xaloc_girona.flows.documentos import subir_documento
from sites.xaloc_girona.flows.login import ejecutar_login
from sites.xaloc_girona.flows.formulario import rellenar_formulario



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

            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 3: SUBIDA DE DOCUMENTOS")
            self.logger.info("=" * 50)
            self.logger.info(
                "Archivos a adjuntar: "
                + (", ".join(str(p) for p in (datos.archivos_para_subir or [])) or "(ninguno)")
            )
            await subir_documento(self.page, datos.archivos_para_subir)

            self.logger.info("\n" + "=" * 50)
            self.logger.info("FASE 4: CONFIRMACION")
            self.logger.info("=" * 50)
            return await confirmar_tramite(self.page, self.config.dir_screenshots)

        except Exception:
            await self.capture_error_screenshot("error.png")
            raise
