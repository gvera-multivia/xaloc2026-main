from __future__ import annotations

from playwright.async_api import Page

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineReposicionData
from sites.base_online.flows.reposicion import rellenar_formulario_p3


async def ejecutar_p3(page: Page, config: BaseOnlineConfig, data: BaseOnlineReposicionData) -> None:
    await rellenar_formulario_p3(page, config, data)

