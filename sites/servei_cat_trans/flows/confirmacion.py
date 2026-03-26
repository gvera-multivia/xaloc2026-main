from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Frame, Page
    from ..config import ServeiCatTransConfig
    from ..data_models import ServeiCatTransTarget

from .form_scope import wait_form_scope


async def run_confirmacion(page: "Page", config: "ServeiCatTransConfig", datos: "ServeiCatTransTarget") -> "Page":
    _ = (config, datos)
    await page.wait_for_timeout(500)
    scope: "Page | Frame" = await wait_form_scope(page, timeout_ms=20000)

    # Parada segura: el envio final requiere firma con certificado.
    candidates = [
        scope.get_by_role("button", name=re.compile(r"Firmar|Signar", re.IGNORECASE)).first,
        scope.locator("button:has-text('Firmar y enviar')").first,
        scope.locator("input[value*='Firmar']").first,
    ]
    for locator in candidates:
        if await locator.count() > 0:
            try:
                await locator.wait_for(state="visible", timeout=5000)
                break
            except Exception:
                continue
    return page
