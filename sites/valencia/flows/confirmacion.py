from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

    from ..config import ValenciaConfig
    from ..data_models import ValenciaTarget

logger = logging.getLogger("xaloc_automation.valencia")


async def _click_first_available(
    page: "Page",
    selectors: list[str],
    *,
    step: str,
    required: bool = True,
) -> bool:
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        for idx in range(count):
            candidate = loc.nth(idx)
            try:
                if not await candidate.is_visible():
                    continue
                if await candidate.is_disabled():
                    continue
                await candidate.click()
                await page.wait_for_load_state("networkidle")
                logger.info("valencia.run_confirmacion -> %s ok selector=%s index=%s", step, selector, idx)
                return True
            except Exception:
                try:
                    await candidate.click(force=True)
                    await page.wait_for_load_state("networkidle")
                    logger.info(
                        "valencia.run_confirmacion -> %s ok selector=%s index=%s forced=1",
                        step,
                        selector,
                        idx,
                    )
                    return True
                except Exception:
                    continue
    if required:
        raise RuntimeError(f"valencia.confirmacion: no se encontro elemento para {step}")
    logger.warning("valencia.run_confirmacion -> %s no encontrado (continuando)", step)
    return False


async def _click_acceder_second_preferred(page: "Page") -> None:
    selectors = [
        'a[title*="Firma con certificado local"]',
        'a.button:has-text("Acceder")',
        'a:has-text("Acceder")',
    ]
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        if count <= 0:
            continue
        # Si hay dos o mas, usar el segundo. Si no, usar el primero.
        index = 1 if count >= 2 else 0
        candidate = loc.nth(index)
        try:
            await candidate.click()
            await page.wait_for_load_state("networkidle")
            logger.info(
                "valencia.run_confirmacion -> click_acceder_autofirma ok selector=%s index=%s",
                selector,
                index,
            )
            return
        except Exception:
            try:
                await candidate.click(force=True)
                await page.wait_for_load_state("networkidle")
                logger.info(
                    "valencia.run_confirmacion -> click_acceder_autofirma ok selector=%s index=%s forced=1",
                    selector,
                    index,
                )
                return
            except Exception:
                continue
    raise RuntimeError("valencia.confirmacion: no se encontro elemento para click_acceder_autofirma")


async def run_confirmacion(page: "Page", config: "ValenciaConfig", datos: "ValenciaTarget") -> "Page":
    _ = (config, datos)
    logger.info(
        "valencia.run_confirmacion START idRecurso=%s expediente=%s tramite=%s",
        datos.idRecurso,
        datos.expediente,
        datos.tramite_tipo,
    )
    await page.wait_for_load_state("networkidle")

    # 1) Presentar
    await _click_first_available(
        page,
        selectors=[
            '[id="j_id1929771016_1_7c0efcb1:j_id1929771016_1_7c0eff57"]',
            'input[type="submit"][value="Presentar"]',
        ],
        step="click_presentar",
    )

    # 2) Checkbox privacidad
    privacy = page.locator('[id="checkBoxPrivacidad"]')
    if await privacy.count():
        if not await privacy.first.is_checked():
            await privacy.first.check()
        logger.info("valencia.run_confirmacion -> checkbox_privacidad ok")
    else:
        logger.warning("valencia.run_confirmacion -> checkbox_privacidad no encontrado")

    # 3) Firmar y presentar
    await _click_first_available(
        page,
        selectors=[
            '[id="formFirma:j_id914586918_1_72a7e174"]',
            'input[type="submit"][value*="Firmar"]',
            'input[type="submit"][value*="Signar"]',
        ],
        step="click_firmar_presentar",
    )

    # 4) Acceptar del panel/modal
    await _click_first_available(
        page,
        selectors=[
            "div.ui-dialog-buttonset button:has-text('Acceptar')",
            'button:has-text("Acceptar")',
            'button:has-text("Aceptar")',
            'button.ui-button:has-text("Acceptar")',
        ],
        step="click_acceptar_modal",
    )

    # 5) Acceder con AutoFirma
    await _click_acceder_second_preferred(page)

    # 6) Boton grande de Firmar (puede aparecer en la pagina actual o en un frame/dialog).
    sign_selectors = [
        '[id="buttonSign"]',
        'input[type="button"][value="Firmar"]',
        'input.button_firmar',
    ]
    clicked_sign = await _click_first_available(
        page,
        selectors=sign_selectors,
        step="click_button_sign",
        required=False,
    )
    if not clicked_sign:
        for idx, frame in enumerate(page.frames):
            for selector in sign_selectors:
                loc = frame.locator(selector)
                if await loc.count():
                    try:
                        await loc.first.click()
                        logger.info(
                            "valencia.run_confirmacion -> click_button_sign ok in_frame=%s selector=%s",
                            idx,
                            selector,
                        )
                        clicked_sign = True
                        break
                    except Exception:
                        continue
            if clicked_sign:
                break
    if not clicked_sign:
        logger.warning("valencia.run_confirmacion -> click_button_sign no disponible tras Acceder (continuando)")

    logger.info("valencia.run_confirmacion END")
    return page
