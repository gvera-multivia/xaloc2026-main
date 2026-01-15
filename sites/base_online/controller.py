from __future__ import annotations

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineTarget


class BaseOnlineController:
    site_id = "base_online"
    display_name = "BASE On-line"

    def create_config(self, *, headless: bool) -> BaseOnlineConfig:
        config = BaseOnlineConfig()
        config.navegador.headless = bool(headless)
        return config

    def create_demo_data(self, *, protocol: str | None = None) -> BaseOnlineTarget:
        return BaseOnlineTarget(protocol=(protocol or "P1"))


def get_controller() -> BaseOnlineController:
    return BaseOnlineController()


__all__ = ["BaseOnlineController", "get_controller"]

