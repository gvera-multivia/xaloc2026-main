"""
Configuracion base reutilizable para cualquier sitio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from urllib.parse import urlsplit
import os


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _split_csv(raw: str) -> List[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _origin_from_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except Exception:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _resolve_headless_default() -> bool:
    mode = (os.getenv("XALOC_BROWSER_MODE") or "").strip().lower()
    if mode in {"headless", "ci"}:
        return True
    if mode in {"headful", "headful_xvfb", "headed"}:
        return False
    return _env_flag("XALOC_HEADLESS", False)


_SITE_DEFAULT_CERT_ORIGINS = {
    "base_online": ["https://valid.aoc.cat", "https://cert.valid.aoc.cat"],
    "xaloc_girona": ["https://valid.aoc.cat", "https://cert.valid.aoc.cat"],
    "madrid": ["https://cas.madrid.es", "https://servcla.madrid.es", "https://servpub.madrid.es"],
}

_GLOBAL_DEFAULT_CERT_ORIGINS = [
    "https://sede.madrid.es",
    "https://servcla.madrid.es",
    "https://servpub.madrid.es",
    "https://www.xalocgirona.cat",
    "https://seu.xalocgirona.cat",
    "https://www.base.cat",
    "https://www.baseonline.cat",
    "https://valid.aoc.cat",
    "https://cert.valid.aoc.cat",
    "https://cas.madrid.es",
    "https://pasarela.clave.gob.es",
    "https://palma.sedipualba.es",
    "https://identificacionssl.sedipualba.es",
]


@dataclass
class BrowserConfig:
    """Configuracion del navegador Playwright."""

    headless: bool = field(default_factory=_resolve_headless_default)
    perfil_path: Path = Path("profiles/edge")
    canal: str = field(default_factory=lambda: (os.getenv("XALOC_BROWSER_CHANNEL") or "chromium").strip())
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


@dataclass
class BaseConfig:
    """
    Configuracion comun.

    Cada sitio deberia extender esta clase para anadir URLs, selectores y particularidades del flujo.
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

    # Preferible para Linux/Docker: bypass del selector nativo de certificado
    # usando API de Playwright en vez de depender de NSS/policies del SO.
    client_cert_enabled: bool = field(
        default_factory=lambda: _env_flag(
            "PLAYWRIGHT_CLIENT_CERT_ENABLED",
            _env_flag("PLAYWRIGHT_CERT_REQUIRED", False),
        )
    )
    client_cert_required: bool = field(default_factory=lambda: _env_flag("PLAYWRIGHT_CERT_REQUIRED", False))
    client_cert_path: str = field(
        default_factory=lambda: (
            os.getenv("PLAYWRIGHT_CLIENT_CERT_PATH")
            or os.getenv("SIGNING_CERT_PATH")
            or ""
        ).strip()
    )
    client_cert_password: str = field(default_factory=lambda: os.getenv("PLAYWRIGHT_CERT_PASSWORD", ""))
    client_cert_origins: List[str] = field(
        default_factory=lambda: _split_csv(os.getenv("PLAYWRIGHT_CLIENT_CERT_ORIGINS", ""))
    )

    # NetLog opcional para depurar mTLS en CI.
    netlog_path: str = field(default_factory=lambda: (os.getenv("XALOC_NETLOG_PATH") or "").strip())
    netlog_capture_mode: str = field(
        default_factory=lambda: (os.getenv("XALOC_NETLOG_CAPTURE_MODE") or "IncludeSensitive").strip()
    )

    autofirma_auto_open: bool = field(default_factory=lambda: os.getenv("XALOC_AUTOFIRMA_AUTO_OPEN", "1") == "1")
    autofirma_protocol: str = field(default_factory=lambda: os.getenv("XALOC_AUTOFIRMA_PROTOCOL", "afirma"))
    autofirma_origin: str = field(default_factory=lambda: os.getenv("XALOC_AUTOFIRMA_ORIGIN", "https://palma.sedipualba.es"))
    stealth_disable_webdriver: bool = False

    # Delays (milisegundos)
    delay_ms: int = 500
    cert_popup_delay_ms: int = 2000
    cert_popup_midload_delay_ms: int = 1600

    def ensure_client_cert_origins(self) -> None:
        values: List[str] = []
        values.extend(self.client_cert_origins or [])
        values.extend(_GLOBAL_DEFAULT_CERT_ORIGINS)
        values.extend(_SITE_DEFAULT_CERT_ORIGINS.get(self.site_id, []))
        values.extend(_split_csv(os.getenv("PLAYWRIGHT_CLIENT_CERT_DEFAULT_ORIGINS", "")))
        origin = _origin_from_url(self.url_base)
        if origin:
            values.append(origin)

        normalized: List[str] = []
        for value in values:
            candidate = (value or "").strip()
            if not candidate or candidate in normalized:
                continue
            normalized.append(candidate)
        self.client_cert_origins = normalized

    def ensure_directories(self) -> None:
        self.dir_screenshots.mkdir(exist_ok=True)
        self.dir_logs.mkdir(exist_ok=True)
        self.navegador.perfil_path.mkdir(parents=True, exist_ok=True)
