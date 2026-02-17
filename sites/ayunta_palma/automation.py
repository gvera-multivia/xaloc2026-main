"""
Automatización principal para Ayunta Palma.
"""

from __future__ import annotations

from core.base_automation import BaseAutomation
from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.data_models import AyuntaPalmaTarget
from sites.ayunta_palma.flows import (
    completar_alegaciones,
    ejecutar_login,
    indicar_representante,
    registrar_interesado,
    subir_documentos,
)


class AyuntaPalmaAutomation(BaseAutomation):
    def __init__(self, config: AyuntaPalmaConfig):
        super().__init__(config)
        self.config: AyuntaPalmaConfig = config

    async def ejecutar_flujo_completo(self, datos: AyuntaPalmaTarget) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        try:
            self.logger.info("FASE 1: LOGIN EN AYUNTA PALMA")
            self.page = await ejecutar_login(self.page, self.config)
            await self.sync_screencast_with_page()

            self.logger.info("FASE 2: REGISTRAR INTERESADO")
            self.page = await registrar_interesado(self.page, self.config, datos)
            await self.sync_screencast_with_page()

            self.logger.info("FASE 3: INDICAR REPRESENTANTE")
            self.page = await indicar_representante(self.page, self.config)
            await self.sync_screencast_with_page()

            self.logger.info("FASE 4: COMPLETAR ALEGACIONES")
            if datos.alegaciones:
                self.page = await completar_alegaciones(self.page, self.config, datos.alegaciones)
                await self.sync_screencast_with_page()

            self.logger.info("FASE 5: SUBIR DOCUMENTOS")
            self.page = await subir_documentos(self.page, self.config, datos.archivos, payload=datos.payload)
            await self.sync_screencast_with_page()

            screenshot_path = self.config.dir_screenshots / "ayunta_palma_final.png"
            await self.page.screenshot(path=screenshot_path, full_page=True)
            self.logger.info(f"Flujo completado. Screenshot en {screenshot_path}")
            return str(screenshot_path)

        except Exception:
            await self.capture_error_screenshot("ayunta_palma_error.png")
            raise
        finally:
            # Palma queda inestable si se reutiliza la misma pestaña tras un tramite.
            # Cerramos siempre la pestaña de trabajo (exito o error).
            if self.page:
                try:
                    if not self.page.is_closed():
                        await self.page.close()
                        self.logger.info("Pestaña de trabajo cerrada al finalizar trámite de ayunta_palma.")
                except Exception as e:
                    self.logger.warning("No se pudo cerrar la pestaña de ayunta_palma al finalizar: %s", e)
                finally:
                    self.page = None
