from .site_adapter import SiteAdapter
from .base import BaseOnlineAdapter
from .madrid import MadridAdapter
from .xaloc_girona import XalocAdapter
from .ayunta_palma import AyuntaPalmaAdapter
from .redsara import RedsaraAdapter
from .terrassa import TerrassaAdapter
from .valencia import ValenciaAdapter
from .atc import AtcAdapter

__all__ = [
    "SiteAdapter",
    "BaseOnlineAdapter",
    "MadridAdapter",
    "XalocAdapter",
    "AyuntaPalmaAdapter",
    "RedsaraAdapter",
    "TerrassaAdapter",
    "ValenciaAdapter",
    "AtcAdapter",
]
