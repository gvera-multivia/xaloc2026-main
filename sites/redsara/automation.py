from __future__ import annotations
import logging
from typing import Optional
from playwright.async_api import Page

from core.base_automation import BaseAutomation
from .config import RedSaraConfig
from .data_models import DatosRepresentante, DatosPresentador, DatosInteresado, ArchivoAdjunto

class RedSaraAutomation(BaseAutomation):
    def __init__(self, config: RedSaraConfig):
        super().__init__(config)
        self.config: RedSaraConfig = config

    async def ejecutar_flujo_completo(
        self, 
        datos: tuple | DatosRepresentante, 
        datos_presentador: Optional[DatosPresentador] = None, 
        datos_interesado: Optional[DatosInteresado] = None, 
        archivos: Optional[list[ArchivoAdjunto]] = None,
        config_override: Optional[RedSaraConfig] = None
    ):
        """Ejecuta toda la secuencia de automatización de RedSARA"""
        if isinstance(datos, tuple):
            # Desempaquetar si viene de main.py como tupla
            datos_representante, datos_presentador, datos_interesado, archivos = datos
        else:
            datos_representante = datos

        if not self.page:
            raise RuntimeError("Navegador no iniciado")

        current_config = config_override or self.config
        
        # Imports locales para evitar ciclos
        from .flows.login import ejecutar_login
        from .flows.formulario import rellenar_formulario
        from .flows.documentos import subir_documentacion
        from .flows.confirmacion import enviar_solicitud
        
        try:
            self.logger.info(f"[{self.config.site_id}] Iniciando flujo completo")
            
            # 1. Login
            await ejecutar_login(self.page, current_config)
            
            # 2. Rellenar Formulario
            await rellenar_formulario(
                self.page, 
                datos_representante, 
                datos_presentador, 
                datos_interesado, 
                current_config
            )

            # 3. Subir Documentación
            if archivos:
                await subir_documentacion(self.page, archivos)

            # 4. Envio (Mock - No firma en demo)
            await enviar_solicitud(self.page)
            
            self.logger.info(f"[{self.config.site_id}] Flujo completado con éxito")
            
        except Exception:
            await self.capture_error_screenshot(f"error_{self.config.site_id}.png")
            raise
