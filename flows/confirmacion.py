"""
Flujo de confirmación final (sin envío real)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError


async def _wait_mask_hidden(page: Page) -> None:
    mask = page.locator("#mask")
    try:
        if await mask.count() > 0:
            await mask.wait_for(state="hidden", timeout=30000)
    except Exception:
        pass


async def _check_lopd(page: Page) -> None:
    await page.wait_for_selector("#lopdok", state="attached", timeout=60000)
    checkbox = page.locator("#lopdok").first
    await checkbox.wait_for(state="visible", timeout=30000)
    await checkbox.scroll_into_view_if_needed()

    for _ in range(3):
        await _wait_mask_hidden(page)
        try:
            await checkbox.check(timeout=10000)
        except Exception:
            try:
                await checkbox.check(timeout=5000, force=True)
            except Exception:
                pass

        if await checkbox.is_checked():
            return

        await page.wait_for_timeout(500)

    # Último recurso: forzar estado por JS + disparar eventos (onclick/onchange) para que aparezca "Continuar".
    ok = await page.evaluate(
        """() => {
            const cb = document.getElementById('lopdok');
            if (!cb) return false;
            cb.checked = true;
            cb.dispatchEvent(new Event('click', { bubbles: true }));
            cb.dispatchEvent(new Event('change', { bubbles: true }));
            if (typeof window.checkContinuar === 'function') window.checkContinuar(cb);
            return cb.checked === true;
        }"""
    )
    if not ok:
        raise TimeoutError("No se pudo marcar el checkbox LOPD (#lopdok)")


async def _wait_boton_continuar(page: Page) -> None:
    await page.wait_for_function(
        """() => {
            const el = document.querySelector('#botoncontinuar');
            if (!el) return false;
            const style = window.getComputedStyle(el);
            return style && style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
        }""",
        timeout=30000,
    )


async def confirmar_tramite(page: Page, screenshots_dir: Path) -> str:
    """
    Confirma el trámite y toma screenshot (NO ENVÍA).

    Returns:
        Ruta del screenshot guardado
    """

    logging.info("Marcando aceptación LOPD")
    await _wait_mask_hidden(page)
    await _check_lopd(page)

    await _wait_boton_continuar(page)

    logging.info("Avanzando a pantalla final")
    continuar = page.locator("div#botoncontinuar a").first
    await continuar.scroll_into_view_if_needed()
    await continuar.wait_for(state="visible", timeout=30000)

    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
            await continuar.click()
    except TimeoutError:
        await continuar.click()

    if "TramitaSign" not in page.url:
        await page.wait_for_url("**/TramitaSign**", timeout=60000)
    await page.wait_for_load_state("networkidle")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = screenshots_dir / f"xaloc_final_{timestamp}.png"
    await page.screenshot(path=screenshot_path, full_page=True)

    logging.warning("PROCESO DETENIDO - Screenshot guardado")
    logging.warning("Botón 'Enviar' NO pulsado (modo testing)")

    return str(screenshot_path)
