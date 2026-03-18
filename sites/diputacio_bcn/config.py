from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class DiputacioBcnConfig(BaseConfig):
    site_id: str = "diputacio_bcn"
    url_base: str = "https://orgt.diba.cat/es/TramitsPagaments/Presentmul/presentmul?NouTramit=True"
    default_timeout: int = 30000
    navigation_timeout: int = 60000
