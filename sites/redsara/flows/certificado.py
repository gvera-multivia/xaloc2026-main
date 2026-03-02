from __future__ import annotations

import asyncio
from playwright.async_api import Page

from sites.redsara.config import RedSaraConfig


async def aceptar_certificado_clave_si_aparece(page: Page, config: RedSaraConfig, timeout: int | None = None) -> bool:
    timeout_ms = timeout or config.flow_timeouts.cert_wait
    try:
        await page.wait_for_url("**pasarela.clave.gob.es/**", timeout=timeout_ms)
    except Exception:
        return False

    boton = page.locator(config.selectors.cert_clave_xpath)
    try:
        await boton.wait_for(state="visible", timeout=config.flow_timeouts.short_wait)
    except Exception:
        return False

    for _ in range(6):
        disabled = await boton.get_attribute("disabled")
        if not disabled:
            break
        await asyncio.sleep(1.0)

    try:
        await boton.click(force=True)
        await asyncio.sleep(2.0)
        return True
    except Exception:
        return False
