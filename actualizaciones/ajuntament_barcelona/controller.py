from __future__ import annotations

from pathlib import Path

from .config import AjuntamentBarcelonaConfig
from .data_models import AjuntamentBarcelonaTarget


class AjuntamentBarcelonaController:
    site_id = "ajuntament_barcelona"
    display_name = "Ajuntament Barcelona"

    def create_config(self, *, headless: bool):
        cfg = AjuntamentBarcelonaConfig()
        cfg.navegador.headless = bool(headless)
        return cfg

    def map_data(self, data: dict) -> dict:
        return dict(data or {})

    def create_target(self, **kwargs) -> AjuntamentBarcelonaTarget:
        archivos = kwargs.get("archivos") or []
        return AjuntamentBarcelonaTarget(
            idRecurso=kwargs.get("idRecurso"),
            expediente=str(kwargs.get("expediente") or ""),
            archivos_adjuntos=[Path(str(p)) for p in archivos],
            payload=dict(kwargs),
            headless=bool(kwargs.get("headless", True)),
        )


def get_controller() -> AjuntamentBarcelonaController:
    return AjuntamentBarcelonaController()
