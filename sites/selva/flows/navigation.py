from __future__ import annotations

import asyncio
import logging
import re

from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def _already_in_form(page: Page, timeout_ms: int) -> bool:
    try:
        await page.wait_for_url("**/TramitaForm**", timeout=timeout_ms)
        return True
    except Exception:
        return False


async def _try_click_in_frames(page: Page, selector: str, timeout_ms: int) -> bool:
    for frame in page.frames:
        try:
            loc = frame.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            await loc.click(timeout=timeout_ms, no_wait_after=True)
            return True
        except Exception:
            continue
    return False


async def _try_click_link_by_text(page: Page, pattern: re.Pattern[str], timeout_ms: int) -> bool:
    for frame in page.frames:
        try:
            loc = frame.get_by_role("link", name=pattern).first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            await loc.click(timeout=timeout_ms, no_wait_after=True)
            return True
        except Exception:
            continue
    return False


async def _try_click_tramita_href(page: Page, timeout_ms: int) -> bool:
    for frame in page.frames:
        try:
            loc = frame.locator('a[href*="TramitaForm"]').first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            await loc.click(timeout=timeout_ms, no_wait_after=True)
            return True
        except Exception:
            continue
    return False


async def navegar_a_formulario(page: Page, url_base: str):
    """
    Navega a la pagina de inicio y entra en el formulario TramitaForm.
    """
    logger.info("Navegando a url_base: %s", url_base)
    await page.goto(url_base, wait_until="domcontentloaded")
    logger.info("URL actual tras goto: %s", page.url)
    logger.info("Frames detectados: %s", [f.url for f in page.frames])

    # Algunos portales redirigen automaticamente (frames/login/certificado).
    # Si ya hemos llegado al formulario, no hace falta clicar.
    if await _already_in_form(page, timeout_ms=15_000):
        logger.info("Ya en TramitaForm tras goto (sin click).")
        return

    # El selector original del recording (puede vivir dentro de frame.jsp).
    recording_selector = "div#aazone.CATSERV > div > ul > li > div:nth-of-type(2) > ul > li > a"

    click_timeout = 8_000

    clicked = False
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(1.0)
            logger.info("Reintentando click (attempt=%s). URL: %s", attempt + 1, page.url)
            if await _already_in_form(page, timeout_ms=5_000):
                logger.info("Se alcanzo TramitaForm durante el reintento (sin click).")
                return

        # 1) Link directo al TramitaForm por href (mas estable).
        if await _try_click_tramita_href(page, timeout_ms=click_timeout):
            logger.info("Click via a[href*='TramitaForm']")
            clicked = True
            break
        # 2) Selector exacto del recording.
        if await _try_click_in_frames(page, recording_selector, timeout_ms=click_timeout):
            logger.info("Click via selector del recording")
            clicked = True
            break
        # 3) Por texto del link (variantes catalan/castellano).
        text_pat = re.compile(r"(certificat|certificado|amb\s+certificat|con\s+certificado)", re.IGNORECASE)
        if await _try_click_link_by_text(page, text_pat, timeout_ms=click_timeout):
            logger.info("Click via texto (certificat/certificado)")
            clicked = True
            break

    if not clicked:
        raise TimeoutError("No se encontro el link hacia TramitaForm (href/selector/texto).")

    await page.wait_for_url("**/TramitaForm**", timeout=60_000)
