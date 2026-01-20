"""
Configuración del sitio Selva.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class SelvaConfig(BaseConfig):
    url_base: str = "https://seu.selva.cat/sta/CarpetaPublic/doEvent?APP_CODE=STA&PAGE_CODE=CATALOGO&DETALLE=6269005284505775806120"
    site_id: str = "selva"

    # Specific selectors or patterns
    # Although we can put them in the code, having them here is good for maintenance.
