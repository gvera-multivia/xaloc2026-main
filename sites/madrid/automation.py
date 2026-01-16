"""
Automatización principal para Madrid Ayuntamiento.
"""

from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from sites.madrid.config import MadridConfig
from sites.madrid.data_models import MadridTarget
from sites.madrid.flows import ejecutar_navegacion_madrid


class MadridAutomation(BaseAutomation):
    """
    Clase de automatización para el sitio Madrid Ayuntamiento.
    Extiende BaseAutomation siguiendo el patrón del proyecto.
    """
    
    def __init__(self, config: MadridConfig):
        super().__init__(config)
        self.config: MadridConfig = config

    async def ejecutar_flujo_completo(self, datos: MadridTarget) -> str:
        """
        Ejecuta el flujo completo de automatización para Madrid.
        
        Fases implementadas:
        - FASE 1: Navegación hasta el formulario (11 pasos)
        
        Fases futuras:
        - FASE 2: Rellenado del formulario
        - FASE 3: Subida de documentos
        - FASE 4: Confirmación y envío
        
        Args:
            datos: Datos del trámite (MadridTarget)
            
        Returns:
            str: Ruta al screenshot final
        """
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            # ================================================================
            # FASE 1: NAVEGACIÓN HASTA EL FORMULARIO
            # ================================================================
            self.logger.info("\n" + "=" * 80)
            self.logger.info("FASE 1: NAVEGACIÓN HASTA EL FORMULARIO")
            self.logger.info("=" * 80)
            
            self.page = await ejecutar_navegacion_madrid(self.page, self.config)
            
            self.logger.info("\n" + "=" * 80)
            self.logger.info("NAVEGACIÓN COMPLETADA - Formulario alcanzado")
            self.logger.info("=" * 80)
            
            # ================================================================
            # FASE 2: RELLENADO DEL FORMULARIO (FUTURO)
            # ================================================================
            # TODO: Implementar cuando se capture el HTML del formulario real
            # self.logger.info("\n" + "=" * 80)
            # self.logger.info("FASE 2: RELLENADO DEL FORMULARIO")
            # self.logger.info("=" * 80)
            # await ejecutar_formulario_madrid(self.page, self.config, datos.form_data)
            
            # ================================================================
            # FASE 3: SUBIDA DE DOCUMENTOS (FUTURO)
            # ================================================================
            # TODO: Implementar si el formulario requiere adjuntos
            # if datos.archivos_adjuntos:
            #     self.logger.info("\n" + "=" * 80)
            #     self.logger.info("FASE 3: SUBIDA DE DOCUMENTOS")
            #     self.logger.info("=" * 80)
            #     await ejecutar_upload_madrid(self.page, self.config, datos.archivos_adjuntos)
            
            # ================================================================
            # FASE 4: CONFIRMACIÓN Y ENVÍO (FUTURO)
            # ================================================================
            # TODO: Implementar confirmación final
            # self.logger.info("\n" + "=" * 80)
            # self.logger.info("FASE 4: CONFIRMACIÓN Y ENVÍO")
            # self.logger.info("=" * 80)
            # await ejecutar_confirmacion_madrid(self.page, self.config)
            
            # ================================================================
            # CAPTURA DE SCREENSHOT FINAL
            # ================================================================
            filename = "madrid_navegacion_completa.png"
            path = self.config.dir_screenshots / filename
            await self.page.screenshot(path=path, full_page=True)
            self.logger.info(f"\n✓ Screenshot guardado: {path}")
            
            return str(Path(path))
            
        except Exception as e:
            self.logger.error(f"\n✗ Error durante la automatización: {e}")
            await self.capture_error_screenshot("madrid_error.png")
            raise
