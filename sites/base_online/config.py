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

    # Formulario P3 (Recurs de reposició)
    p3_radio_ibi: str = "#radio1"
    p3_radio_ivtm: str = "#radio2"
    p3_radio_executiu: str = "#radio3"
    p3_radio_altres: str = "#radio4"
    p3_textarea_dades: str = "#form0\\:dades"
    p3_select_tipus: str = "select[name='form0:j_id124']"
    p3_textarea_exposo: str = "#form0\\:exposo"
    p3_textarea_solicito: str = "#form0\\:solicito"
    p3_button_continuar: str = "input[type='submit'][value='Continuar']"

