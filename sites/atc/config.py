from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class AtcConfig(BaseConfig):
    site_id: str = "atc"
    url_base: str = "https://atc.gencat.cat/ca/gestions/impugnacions/"
    url_impugnacions: str = "https://atc.gencat.cat/ca/gestions/impugnacions/"
    url_registro_entry: str = "https://atc.gencat.cat/es/gestions/registre-electronic/"
    url_registro_form: str = "https://seu.atc.gencat.cat/es/OficinaVirtual/Paginas/TramitsGenerics.aspx"
    auto_select_certificate_pattern: str = "https://valid.aoc.cat/*"
    prefer_ephemeral_profile_on_windows: bool = True
    delay_ms: int = 1000
    default_timeout: int = 45000
    navigation_timeout: int = 120000
