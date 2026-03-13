from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.base_config import BaseConfig


@dataclass
class AjuntamentBarcelonaConfig(BaseConfig):
    site_id: str = "ajuntament_barcelona"
    url_base: str = "https://seuelectronica.ajuntament.barcelona.cat/oficinavirtual/ca/tramit/20200001444"
    url_confirm_ca: str = (
        "https://seuelectronica.ajuntament.barcelona.cat/APPS/portaltramits/formulari/"
        "ptbcertnegatiui/T19b/confirma/ca/PTCIU.html?stepName=viewConfirmFormulariStep"
    )
    url_confirm_es: str = (
        "https://seuelectronica.ajuntament.barcelona.cat/APPS/portaltramits/formulari/"
        "ptbcertnegatiui/T19b/confirma/es/PTCIU.html?stepName=viewConfirmFormulariStep"
    )
    dir_logs: Path = Path("actualizaciones/ajuntament_barcelona")
    telefono_principal: str = "722761154"
    default_timeout: int = 30000
    navigation_timeout: int = 60000

    def __post_init__(self) -> None:
        self.navegador.canal = "chrome"
