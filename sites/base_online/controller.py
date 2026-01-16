from __future__ import annotations
import logging
from pathlib import Path

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineReposicionData, BaseOnlineTarget

class BaseOnlineController:
    site_id = "base_online"
    display_name = "BASE On-line"

    def create_config(self, *, headless: bool) -> BaseOnlineConfig:
        config = BaseOnlineConfig()
        config.navegador.headless = bool(headless)
        return config

    def create_demo_data(
        self,
        *,
        protocol: str | None = None,
        p3_tipus_objecte: str | None = None,
        p3_dades_especifiques: str | None = None,
        p3_tipus_solicitud_value: str | None = None,
        p3_exposo: str | None = None,
        p3_solicito: str | None = None,
        p3_archivos: str | list[str] | None = None, # Cambiado a plural para claridad
    ) -> BaseOnlineTarget:
        protocol_norm = (protocol or "P1").upper().strip()
        reposicion = None
        
        if protocol_norm == "P3":
            # Procesamos los archivos: si viene uno solo en string, lo metemos en lista.
            # Si no viene nada, usamos el de prueba por defecto.
            lista_raw = []
            if p3_archivos:
                lista_raw = [p3_archivos] if isinstance(p3_archivos, str) else p3_archivos
            else:
                lista_raw = ["pdfs-prueba/test3.pdf"]

            archivos_paths = [Path(a) for a in lista_raw]

            reposicion = BaseOnlineReposicionData(
                tipus_objecte=p3_tipus_objecte or "IVTM",
                dades_especifiques=p3_dades_especifiques or "1234-ABC (Matrícula de prueba)",
                tipus_solicitud_value=str(p3_tipus_solicitud_value or "1"),
                exposo=p3_exposo or "Exposición de motivos de prueba para el recurso.",
                solicito=p3_solicito or "Solicitud de prueba para el recurso.",
                archivos_adjuntos=archivos_paths, # Ahora es una lista
            )
        return BaseOnlineTarget(protocol=protocol_norm, reposicion=reposicion)

def get_controller() -> BaseOnlineController:
    return BaseOnlineController()

__all__ = ["BaseOnlineController", "get_controller"]