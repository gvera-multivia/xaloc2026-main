"""
Automatización principal para Madrid Ayuntamiento.
"""

from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from core.errors import RestartRequiredError
from sites.madrid.config import MadridConfig
from sites.madrid.data_models import MadridTarget
from sites.madrid.flows import ejecutar_navegacion_madrid, ejecutar_formulario_madrid, ejecutar_upload_madrid, ejecutar_firma_madrid


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
        - FASE 2: Rellenado del formulario (8 secciones)
        - FASE 3: Subida de documentos (adjuntos)
        - FASE 4: Firma y verificación de documento
        
        Args:
            datos: Datos del trámite (MadridTarget)
            
        Returns:
            str: Ruta al screenshot final
        """
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        for intento in range(2):
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
                # FASE 2: RELLENADO DEL FORMULARIO
                # ================================================================
                if datos.form_data:
                    self.logger.info("\n" + "=" * 80)
                    self.logger.info("FASE 2: RELLENADO DEL FORMULARIO")
                    self.logger.info("=" * 80)

                    self.page = await ejecutar_formulario_madrid(
                        self.page,
                        self.config,
                        datos.form_data,
                    )

                    self.logger.info("\n" + "=" * 80)
                    self.logger.info("FORMULARIO COMPLETADO - Pantalla de adjuntos alcanzada")
                    self.logger.info("=" * 80)
                else:
                    self.logger.info("\n⚠ Sin datos de formulario, saltando FASE 2")

                # ================================================================
                # FASE 3: SUBIDA DE DOCUMENTOS (adjuntos)
                # ================================================================
                if datos.archivos_adjuntos:
                    self.logger.info("\n" + "=" * 80)
                    self.logger.info("FASE 3: SUBIDA DE DOCUMENTOS")
                    self.logger.info("=" * 80)
                    self.page = await ejecutar_upload_madrid(self.page, self.config, datos.archivos_adjuntos)
                else:
                    self.logger.info("\nƒsÿ Sin adjuntos, saltando FASE 3")

                # ================================================================
                # FASE 4: FIRMA Y VERIFICACIÓN DE DOCUMENTO
                # ================================================================
                self.logger.info("\n" + "=" * 80)
                self.logger.info("FASE 4: FIRMA Y VERIFICACIÓN DE DOCUMENTO")
                self.logger.info("=" * 80)
                
                # Construir ruta de destino para el documento verificado
                id_recurso = getattr(datos, 'idRecurso', 'unknown')
                destino_verificacion = self.config.dir_screenshots / f"verificacion_{id_recurso}.pdf"
                
                self.page = await ejecutar_firma_madrid(
                    self.page,
                    self.config,
                    destino_verificacion
                )
                
                self.logger.info("\n" + "=" * 80)
                self.logger.info("FIRMA Y VERIFICACIÓN COMPLETADA")
                self.logger.info("=" * 80)

                # ================================================================
                # CAPTURA DE SCREENSHOT FINAL
                # ================================================================
                filename = "madrid_formulario_completo.png"
                path = self.config.dir_screenshots / filename
                await self.page.screenshot(path=path, full_page=True)
                self.logger.info(f"\n✓ Screenshot guardado: {path}")

                return str(Path(path))

            except RestartRequiredError as e:
                self.logger.warning(
                    f"\n↻ Reinicio requerido por 'trámite en curso': {e} (intento {intento + 1}/2)"
                )
                await self.capture_error_screenshot("madrid_restart_required.png")
                if intento >= 1:
                    raise
                await self.restart_browser()
                if not self.page:
                    raise RuntimeError("No se pudo reiniciar el navegador (page es None).") from e
                continue

            except Exception as e:
                self.logger.error(f"\n✗ Error durante la automatización: {e}")
                await self.capture_error_screenshot("madrid_error.png")
                raise

        raise RuntimeError("No se pudo completar la automatización tras reiniciar el navegador.")
