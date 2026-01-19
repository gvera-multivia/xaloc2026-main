"""
Registro simple de sitios.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Type

from core.base_automation import BaseAutomation


@dataclass(frozen=True)
class SiteDefinition:
    site_id: str
    automation_path: str  # "module:ClassName"
    controller_path: str  # "module:function" or "module:ClassName"


SITES: dict[str, SiteDefinition] = {
    "xaloc_girona": SiteDefinition(
        site_id="xaloc_girona",
        automation_path="sites.xaloc_girona.automation:XalocGironaAutomation",
        controller_path="sites.xaloc_girona.controller:get_controller",
    ),
    "base_online": SiteDefinition(
        site_id="base_online",
        automation_path="sites.base_online.automation:BaseOnlineAutomation",
        controller_path="sites.base_online.controller:get_controller",
    ),
    "madrid": SiteDefinition(
        site_id="madrid",
        automation_path="sites.madrid.automation:MadridAutomation",
        controller_path="sites.madrid.controller:get_controller",
    ),
    "redsara": SiteDefinition(
        site_id="redsara",
        automation_path="sites.redsara.automation:RedSaraAutomation",
        controller_path="sites.redsara.controller:get_controller",
    ),
}


def list_sites() -> list[str]:
    return sorted(SITES.keys())


def get_site(site_id: str) -> Type[BaseAutomation]:
    if site_id not in SITES:
        raise KeyError(f"Sitio desconocido: {site_id}. Disponibles: {', '.join(list_sites())}")

    module_path, class_name = SITES[site_id].automation_path.split(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls


def get_site_controller(site_id: str):
    if site_id not in SITES:
        raise KeyError(f"Sitio desconocido: {site_id}. Disponibles: {', '.join(list_sites())}")

    module_path, symbol_name = SITES[site_id].controller_path.split(":", 1)
    module = importlib.import_module(module_path)
    symbol = getattr(module, symbol_name)
    return symbol()
