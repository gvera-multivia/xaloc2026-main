"""
Configuracion del sitio Xaloc Girona.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.base_config import BaseConfig


@dataclass
class XalocSelectors:
    cert_button: str = "#btnContinuaCert, [data-testid='certificate-btn']"
    cookie_buttons: List[str] = field(
        default_factory=lambda: [
            r"Acceptar",
            r"Aceptar",
            r"Aceptar todo",
            r"Aceptar todas",
            r"Accept all",
            r"Entesos",
        ]
    )
    tramite_link_regex: str = r"Tramitaci[oó] en l[ií]nia|Tramitaci[oó]n en l[ií]nea"


@dataclass
class XalocFlowTimeouts:
    cookie_click: int = 1500
    link_appear: int = 10000
    cert_button_appear: int = 15000
    short_delay: int = 500


@dataclass
class XalocConfig(BaseConfig):
    url_base: str = "https://www.xalocgirona.cat/seu-electronica?view=tramits&id=11"
    site_id: str = "xaloc_girona"
    selectors: XalocSelectors = field(default_factory=XalocSelectors)
    flow_timeouts: XalocFlowTimeouts = field(default_factory=XalocFlowTimeouts)

    # Legacy aliases kept for backward compatibility with existing flow code.
    tramite_link_pattern: str = r"Tramitaci[oó] en l[ií]nia|Tramitaci[oó]n en l[ií]nea"
    cert_button_selector: str = "#btnContinuaCert, [data-testid='certificate-btn']"
    url_post_login: str = "**/seu.xalocgirona.cat/sta/**"

    # Configuracion de tiempos de espera
    tiempo_espera_post_envio: int = 10  # Segundos a esperar tras enviar antes de descargar justificante
