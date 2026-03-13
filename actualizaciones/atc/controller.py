from __future__ import annotations

from pathlib import Path

from .config import AtcConfig
from .data_models import AtcTarget


class AtcController:
    site_id = "atc"
    display_name = "ATC Gencat"

    def create_config(self, *, headless: bool):
        cfg = AtcConfig()
        cfg.navegador.headless = bool(headless)
        return cfg

    def map_data(self, data: dict) -> dict:
        return dict(data or {})

    def create_target(self, **kwargs) -> AtcTarget:
        archivos = kwargs.get("archivos") or []
        return AtcTarget(
            idRecurso=kwargs.get("idRecurso"),
            expediente=str(kwargs.get("expediente") or ""),
            archivos_adjuntos=[Path(str(p)) for p in archivos],
            payload=dict(kwargs),
            headless=bool(kwargs.get("headless", True)),
        )


def get_controller() -> AtcController:
    return AtcController()
