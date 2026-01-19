"""
Configuración del sitio Xaloc Girona.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.base_config import BaseConfig


@dataclass
class XalocConfig(BaseConfig):
    url_base: str = "https://www.xalocgirona.cat/seu-electronica?view=tramits&id=11"
    site_id: str = "xaloc_girona"

    # Autoselección de certificado: restringida a dominios del flujo (Girona)
    auto_select_certificate_patterns: list[str] = field(default_factory=lambda: [
        "https://www.xalocgirona.cat/*",
        "https://seu.xalocgirona.cat/*",
    ])

    # Login / VÀLid
    tramite_link_pattern: str = r"Tramitaci[oÇü] en l[iÇð]nia|Tramitaci[oÇü]n en l[iÇð]nea"
    cert_button_selector: str = "#btnContinuaCert, [data-testid='certificate-btn']"
    url_post_login: str = "**/seu.xalocgirona.cat/sta/**"
