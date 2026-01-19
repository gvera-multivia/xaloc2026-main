from __future__ import annotations
from dataclasses import dataclass, field
from core.base_config import BaseConfig

@dataclass
class RedSaraConfig(BaseConfig):
    url_base: str = "https://reg.redsara.es/es/"
    site_id: str = "redsara"
    
    # Datos Tramite específicos de RedSARA
    asunto: str = ""
    expone: str = ""
    solicita: str = ""
    organismo: str = "L01220067" # DIR3 por defecto

    # Autoselección de certificado: restringida a dominios de RedSARA
    auto_select_certificate_patterns: list[str] = field(default_factory=lambda: [
        "https://reg.redsara.es/*",
        "https://*.redsara.es/*",
    ])
