from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ._page_eval import evaluate_with_nav_retry

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget

logger = logging.getLogger("xaloc_automation.terrassa")


async def _fallback_cert_button_by_role(page: "Page") -> "Locator":
    button = page.get_by_role("button", name=re.compile(r"certificat|certificado", re.IGNORECASE)).first
    if await button.count() <= 0:
        raise RuntimeError("terrassa.login: no se encontro boton de acceso con certificado.")
    return button


async def _resolve_cert_button(page: "Page", selector: str, timeout_ms: int) -> "Locator":
    locator = page.locator(selector)
    deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0
    last_count = 0

    while time.monotonic() < deadline:
        try:
            await locator.first.wait_for(state="attached", timeout=800)
        except Exception:
            await page.wait_for_timeout(150)
            continue

        try:
            last_count = await locator.count()
        except Exception:
            last_count = 0
        if last_count <= 0:
            await page.wait_for_timeout(150)
            continue

        for idx in range(last_count):
            candidate = locator.nth(idx)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue
        await page.wait_for_timeout(150)

    if last_count > 0:
        return locator.first
    return await _fallback_cert_button_by_role(page)


async def _click_cert_button_robusto(page: "Page", selector: str, timeout_ms: int) -> None:
    cert_btn = await _resolve_cert_button(page, selector, timeout_ms)
    try:
        await cert_btn.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass

    for kwargs in ({"no_wait_after": True}, {"no_wait_after": True, "force": True}):
        try:
            await cert_btn.click(timeout=5000, **kwargs)
            logger.info("terrassa.login: click en boton certificado lanzado kwargs=%s", kwargs)
            return
        except Exception as exc:
            logger.warning("terrassa.login: click boton certificado fallo kwargs=%s error=%s", kwargs, exc)
            continue

    try:
        await cert_btn.dispatch_event("click")
        logger.info("terrassa.login: dispatch_event('click') lanzado sobre boton certificado")
        return
    except Exception as exc:
        logger.warning("terrassa.login: dispatch_event('click') fallo: %s", exc)

    clicked = await evaluate_with_nav_retry(
        page,
        """(selector) => {
            const isVisible = (el) => {
                if (!el) return false;
                const st = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return !!st && st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
            };
            const nodes = Array.from(document.querySelectorAll(selector));
            if (!nodes.length) return false;
            const target = nodes.find((el) => isVisible(el)) || nodes[0];
            for (const [name, Ctor] of [
                ["pointerdown", PointerEvent],
                ["mousedown", MouseEvent],
                ["pointerup", PointerEvent],
                ["mouseup", MouseEvent],
                ["click", MouseEvent],
            ]) {
                try {
                    target.dispatchEvent(new Ctor(name, { bubbles: true, cancelable: true }));
                } catch (_err) {}
            }
            try { target.click(); } catch (_err) {}
            return true;
        }""",
        selector,
    )
    if not clicked:
        raise RuntimeError(f"terrassa.login: no se pudo clicar el boton de certificado selector={selector!r}")
    logger.info("terrassa.login: fallback JS click lanzado sobre boton certificado")


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

        try:
            await _click_cert_button_robusto(page, config.cert_button_selector, config.timeouts.login)
        except (PlaywrightTimeoutError, RuntimeError) as exc:
            logger.warning("terrassa.login: click CSS fallo (%s); reintentando por rol/nombre", exc)
            cert_btn = await _fallback_cert_button_by_role(page)
            try:
                await cert_btn.scroll_into_view_if_needed()
            except Exception:
                pass
            await cert_btn.click(timeout=5000, no_wait_after=True, force=True)

        # El selector de certificado del SO es manual.
        await page.wait_for_url("**/tramits/ferTramit.jsp**", timeout=config.auth_timeout_ms)
        await page.wait_for_load_state("domcontentloaded")

    await page.locator(f"a[href='{config.href_actuar_representant}']").first.wait_for(
        state="visible",
        timeout=config.timeouts.transicion,
    )
    return page
