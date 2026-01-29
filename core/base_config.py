"""
Configuración base reutilizable para cualquier sitio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import os
from core.config_manager import config_manager


@dataclass
class BrowserConfig:
    """Configuración del navegador Playwright."""

    headless: bool = False
    perfil_path: Path = Path("profiles/edge")
    canal: str = "msedge"
    certificado_cn: str = os.getenv("certificado_cn", "")
    args: List[str] = field(
        default_factory=lambda: [
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
        ]
    )


@dataclass
class Timeouts:
    """Tiempos de espera en milisegundos."""

    general: int = 30000
    login: int = 60000
    transicion: int = 30000
    subida_archivo: int = 60000

    def __post_init__(self):
        timeouts = config_manager.timeouts
        if timeouts:
             self.general = timeouts.get("general", self.general)
             self.login = timeouts.get("login", self.login)
             self.transicion = timeouts.get("transicion", self.transicion)
             self.subida_archivo = timeouts.get("subida_archivo", self.subida_archivo)


@dataclass
class BaseConfig:
    """
    Configuración común.

    Cada sitio debería extender esta clase para añadir URLs, selectores y particularidades del flujo.
    """

    site_id: str
    url_base: str

    navegador: BrowserConfig = field(default_factory=BrowserConfig)
    timeouts: Timeouts = field(default_factory=Timeouts)

    dir_screenshots: Path = Path("screenshots")
    dir_logs: Path = Path("logs")

    lang: str = "ca"
    disable_translate_ui: bool = True
    auto_select_certificate: bool = True
    auto_select_certificate_pattern: str = "*"
    stealth_disable_webdriver: bool = False

    # Delays (milisegundos)
    # Útiles para desacelerar la demo y dar tiempo a renders/handlers del sitio.
    delay_ms: int = 500
    cert_popup_delay_ms: int = 2000
    cert_popup_midload_delay_ms: int = 1600

    def __post_init__(self):
        timeouts = config_manager.timeouts
        if timeouts:
            self.delay_ms = timeouts.get("delay_ms", self.delay_ms)
            self.cert_popup_delay_ms = timeouts.get("cert_popup_delay_ms", self.cert_popup_delay_ms)
            self.cert_popup_midload_delay_ms = timeouts.get("cert_popup_midload_delay_ms", self.cert_popup_midload_delay_ms)

    def ensure_directories(self) -> None:
        self.dir_screenshots.mkdir(exist_ok=True)
        self.dir_logs.mkdir(exist_ok=True)
        self.navegador.perfil_path.mkdir(parents=True, exist_ok=True)
