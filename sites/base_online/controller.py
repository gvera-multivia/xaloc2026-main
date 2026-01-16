from __future__ import annotations

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
        p3_archivo: str | None = None,
    ) -> BaseOnlineTarget:
        protocol_norm = (protocol or "P1").upper().strip()
        reposicion = None
        if protocol_norm == "P3":
            reposicion = BaseOnlineReposicionData(
                tipus_objecte=p3_tipus_objecte or "IVTM",
                dades_especifiques=p3_dades_especifiques or "1234-ABC (Matrícula de prueba)",
                tipus_solicitud_value=str(p3_tipus_solicitud_value or "1"),
                exposo=p3_exposo or "Exposición de motivos de prueba para el recurso.",
                solicito=p3_solicito or "Solicitud de prueba para el recurso.",
                archivo_adjunto=Path(p3_archivo) if p3_archivo else Path("pdfs-prueba/test3.pdf"),
            )
        return BaseOnlineTarget(protocol=protocol_norm, reposicion=reposicion)


def get_controller() -> BaseOnlineController:
    return BaseOnlineController()


__all__ = ["BaseOnlineController", "get_controller"]
