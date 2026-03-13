from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AjuntamentBarcelonaConfig
    from ..data_models import AjuntamentBarcelonaTarget


logger = logging.getLogger("xaloc_automation.ajuntament_barcelona")


async def run_formulario(page: "Page", config: "AjuntamentBarcelonaConfig", datos: "AjuntamentBarcelonaTarget") -> "Page":
    _ = (config, datos)
    logger.info("ajuntament_barcelona.formulario START")

    if page.is_closed():
        alive_pages = [p for p in page.context.pages if not p.is_closed()]
        if not alive_pages:
            raise RuntimeError("formulario: no hay paginas activas")
        page = alive_pages[-1]

    await page.wait_for_load_state("domcontentloaded")

    # Si ya estamos en init (tramite iniciado), no reintentar click.
    if "/formulari/" in page.url.lower() and "/init/" in page.url.lower():
        logger.info("ajuntament_barcelona.formulario already_in_init url=%s", page.url)
        return page

    starter_button = page.locator("#starter-buttons").get_by_role(
        "button",
        name=re.compile(r"Inicia el tr.*mit|Iniciar el tr.*mite", re.IGNORECASE),
    ).first
    starter_fallback = page.get_by_role(
        "button",
        name=re.compile(r"Inicia el tr.*mit|Iniciar el tr.*mite", re.IGNORECASE),
    ).first

    clicked = False
    last_error = None
    for attempt in range(1, 4):
        try:
            if await starter_button.count():
                await starter_button.wait_for(state="visible", timeout=8000)
                await starter_button.scroll_into_view_if_needed()
                await starter_button.click(timeout=8000)
            else:
                await starter_fallback.wait_for(state="visible", timeout=8000)
                await starter_fallback.scroll_into_view_if_needed()
                await starter_fallback.click(timeout=8000)
            clicked = True
            logger.info("ajuntament_barcelona.formulario starter clicked attempt=%s", attempt)
            break
        except Exception as exc:
            last_error = exc
            logger.warning("ajuntament_barcelona.formulario starter click failed attempt=%s err=%s", attempt, exc)
            await page.wait_for_timeout(800)

    if not clicked:
        # Si tras fallar ya hemos entrado al init, continuar igualmente.
        if "/formulari/" in page.url.lower() and "/init/" in page.url.lower():
            logger.info("ajuntament_barcelona.formulario starter_not_clicked_but_already_init url=%s", page.url)
            return page
        raise RuntimeError(f"formulario: no se pudo iniciar el tramite: {last_error}")

    try:
        await page.wait_for_load_state("networkidle", timeout=config.navigation_timeout)
    except Exception:
        await page.wait_for_load_state("domcontentloaded", timeout=config.navigation_timeout)

    # En algunas ejecuciones aparece una pantalla intermedia para escoger certificado.
    cert_clicked = False
    cert_selector = "#btnContinuaCert, [data-testid='certificate-btn']"
    for attempt in range(1, 9):
        if page.is_closed():
            alive_pages = [p for p in page.context.pages if not p.is_closed()]
            if not alive_pages:
                logger.warning("ajuntament_barcelona.formulario cert_btn: no hay pagina viva (attempt=%s)", attempt)
                break
            page = alive_pages[-1]

        cert_btn = page.locator(cert_selector).first
        cert_btn_count = await cert_btn.count()
        logger.info(
            "ajuntament_barcelona.formulario cert_btn probe attempt=%s count=%s url=%s",
            attempt,
            cert_btn_count,
            page.url,
        )
        if cert_btn_count:
            try:
                await cert_btn.wait_for(state="visible", timeout=2500)
                await cert_btn.scroll_into_view_if_needed()
                await cert_btn.click(timeout=5000)
                cert_clicked = True
                logger.info("ajuntament_barcelona.formulario cert_btn clicked attempt=%s", attempt)
                break
            except Exception as exc:
                logger.warning(
                    "ajuntament_barcelona.formulario cert_btn click failed attempt=%s err=%s",
                    attempt,
                    exc,
                )
        await page.wait_for_timeout(700)

    if cert_clicked:
        try:
            await page.wait_for_load_state("networkidle", timeout=config.navigation_timeout)
        except Exception:
            await page.wait_for_load_state("domcontentloaded", timeout=config.navigation_timeout)
    else:
        logger.info("ajuntament_barcelona.formulario cert_btn not present after starter (continuing)")

    logger.info("ajuntament_barcelona.formulario done url=%s", page.url)
    return page
