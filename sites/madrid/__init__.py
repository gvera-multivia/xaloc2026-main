"""
Sitio Madrid Ayuntamiento - Sede Electrónica
"""

from sites.madrid.automation import MadridAutomation
from sites.madrid.config import MadridConfig
from sites.madrid.controller import MadridController, get_controller

__all__ = [
    "MadridAutomation",
    "MadridConfig",
    "MadridController",
    "get_controller",
]
