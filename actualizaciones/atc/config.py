from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.base_config import BaseConfig


@dataclass
class AtcConfig(BaseConfig):
    site_id: str = "atc"
    url_base: str = "https://atc.gencat.cat/es/gestions/certificats/certificats-tributaris/"
    url_certificats: str = "https://atc.gencat.cat/es/gestions/certificats/certificats-tributaris/"
    # El archivo resultante sera: actualizaciones/atc/atc.log
    dir_logs: Path = Path("actualizaciones/atc")
    start_cta_selector: str = (
        "a:has-text('Inicia el tramit'),"
        "a:has-text('Iniciar tramite'),"
        "a:has-text('Tramitar')"
    )
    default_timeout: int = 30000
    navigation_timeout: int = 60000

    def __post_init__(self) -> None:
        self.navegador.canal = "chrome"
