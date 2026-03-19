from __future__ import annotations

from pathlib import Path

from .config import DiputacioBcnConfig
from .data_models import DiputacioBcnTarget


class DiputacioBcnController:
    site_id = "diputacio_bcn"
    display_name = "Diputacio Barcelona"

    def create_config(self, *, headless: bool):
        cfg = DiputacioBcnConfig()
        cfg.navegador.headless = bool(headless)
        return cfg

    def map_data(self, data: dict) -> dict:
        return dict(data or {})

    def create_target(self, **kwargs) -> DiputacioBcnTarget:
        archivos = kwargs.get("archivos") or []
        return DiputacioBcnTarget(
            idRecurso=kwargs.get("idRecurso"),
            expediente=str(kwargs.get("expediente") or ""),
            archivos_adjuntos=[Path(str(p)) for p in archivos],
            payload=dict(kwargs),
            tipo_representado=str(kwargs.get("tipo_representado") or "fisica"),
            nif_interessat=str(kwargs.get("nif_interessat") or ""),
            nom_cr4=str(kwargs.get("nom_cr4") or ""),
            cognom1=str(kwargs.get("cognom1") or ""),
            cognom2=str(kwargs.get("cognom2") or ""),
            nom_juridica=str(kwargs.get("nom_juridica") or ""),
            fase_procedimiento=str(kwargs.get("fase_procedimiento") or ""),
            municipio=str(kwargs.get("municipio") or ""),
            matricula=str(kwargs.get("matricula") or ""),
            doc_acreditativa=str(kwargs.get("doc_acreditativa") or ""),
            doc_tramite=str(kwargs.get("doc_tramite") or ""),
            comentari=str(kwargs.get("comentari") or ""),
            telefon=str(kwargs.get("telefon") or ""),
            email=str(kwargs.get("email") or ""),
            headless=bool(kwargs.get("headless", True)),
        )


def get_controller() -> DiputacioBcnController:
    return DiputacioBcnController()
