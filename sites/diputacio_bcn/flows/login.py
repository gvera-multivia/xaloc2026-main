from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import DiputacioBcnConfig
    from ..data_models import DiputacioBcnTarget

logger = logging.getLogger("sites.diputacio_bcn.login")


def _pick_latest_open_page(page: "Page") -> "Page":
    if not page.is_closed():
        return page
    pages = [p for p in page.context.pages if not p.is_closed()]
    if not pages:
        raise RuntimeError("No hay pestañas activas durante el login de Diputacio BCN.")
    return pages[-1]


async def run_login(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = datos
    page = _pick_latest_open_page(page)
    await page.goto(config.url_base, wait_until="domcontentloaded")

    cookie_btn = page.locator(
        "button.cc-dismiss, button[aria-label='dismiss cookie message'], button:has-text('De acuerdo')"
    )
    if await cookie_btn.count() > 0:
        await cookie_btn.first.click()

    if "/Home/Index" in page.url:
        await page.get_by_role(
            "link",
            name="Presentación de alegaciones o recursos por infracciones de tráfico",
        ).click()

    trigger = page.locator(
        "a.btn.btn-info.pull-left[value='Accedir'], "
        "a.btn.btn-info.pull-left:has-text('Acceder'), "
        "a.btn.btn-info.pull-left:has-text('Accedir')"
    ).first
    if await trigger.count() > 0:
        await trigger.wait_for(state="visible", timeout=config.default_timeout)
        await trigger.click()
    else:
        trigger = page.get_by_text(re.compile(r"Acced(er|ir)", re.IGNORECASE), exact=False).first
        await trigger.wait_for(state="visible", timeout=config.default_timeout)
        await trigger.click()
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        logger.warning(
            "diputacio_bcn login: networkidle no alcanzado en 15s; continuamos con domcontentloaded."
        )
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    return _pick_latest_open_page(page)
