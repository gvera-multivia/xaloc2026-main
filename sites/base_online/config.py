"""
Configuración del sitio BASE On-line.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class BaseOnlineConfig(BaseConfig):
    site_id: str = "base_online"
    url_base: str = "https://www.base.cat/ciutada/ca/tramits/multes-i-sancions/multes-i-sancions.html"

    # Landing
    base_online_link_selector: str = "a.logo_text[href*='/sav/valid'], a.logo_text[href*='base.cat/sav/valid']"

    # Login / VÀLid
    cert_button_selector: str = "#btnContinuaCert, [data-testid='certificate-btn']"
    url_post_login: str = "**/commons-desktop/index.*"

