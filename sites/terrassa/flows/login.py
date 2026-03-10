from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget


async def run_login(page: "Page", config: "TerrassaConfig", datos: "TerrassaTarget") -> "Page":
    _ = datos
    await page.goto(config.url_tramit)
    await page.wait_for_load_state("domcontentloaded")

    start_link = page.locator(f"a[href='{config.href_omplir_form}']").first
    await start_link.wait_for(state="visible", timeout=config.timeouts.transicion)
    await start_link.click()
    await page.wait_for_load_state("domcontentloaded")

    # Puede entrar directo al formulario (sesion activa) o pedir identificacion.
    if await page.locator(f"a[href='{config.href_identificar}']").count() > 0:
        await page.locator(f"a[href='{config.href_identificar}']").first.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_url("**valid.aoc.cat/**", timeout=config.timeouts.login)

        cert_btn = page.locator(config.cert_button_selector).first
        await cert_btn.wait_for(state="visible", timeout=config.timeouts.login)
        await cert_btn.click()

        # El selector de certificado del SO es manual.
        await page.wait_for_url("**/tramits/ferTramit.jsp**", timeout=config.auth_timeout_ms)
        await page.wait_for_load_state("domcontentloaded")

    await page.locator(f"a[href='{config.href_actuar_representant}']").first.wait_for(
        state="visible",
        timeout=config.timeouts.transicion,
    )
    return page
