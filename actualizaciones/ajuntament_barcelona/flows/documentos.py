from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AjuntamentBarcelonaConfig
    from ..data_models import AjuntamentBarcelonaTarget


logger = logging.getLogger("xaloc_automation.ajuntament_barcelona")


async def _find_first_visible_input(page: "Page", selectors: list[str], attempts: int = 60):
    for _ in range(attempts):
        for selector in selectors:
            loc = page.locator(selector)
            count = await loc.count()
            for idx in range(count):
                cand = loc.nth(idx)
                try:
                    if await cand.is_visible():
                        return cand
                except Exception:
                    continue
        await page.wait_for_timeout(250)
    return None


async def run_documentos(page: "Page", config: "AjuntamentBarcelonaConfig", datos: "AjuntamentBarcelonaTarget") -> "Page":
    _ = datos
    logger.info("ajuntament_barcelona.documentos START")

    cert_btn = page.get_by_test_id("certificate-btn")
    if await cert_btn.count():
        logger.info("ajuntament_barcelona.documentos certificate-btn present, clicking")
        await cert_btn.first.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_load_state("networkidle")
    else:
        logger.info("ajuntament_barcelona.documentos certificate-btn not present, assuming already authenticated")

    # Espera fuerte: el formulario real esta listo cuando aparece el select de tipo doc.
    tipo_id = page.locator("#T19b_REP_docTipus")
    await tipo_id.first.wait_for(state="visible", timeout=30000)

    # Telefono principal (prioriza label; fallback por ids/names reales del formulario T19b).
    telefono = page.get_by_label(
        re.compile(r"Tel[eèé]fon.*principal|Tel[eé]fono.*principal", re.IGNORECASE)
    ).first
    telefono_ok = False
    try:
        if await telefono.count():
            await telefono.wait_for(state="visible", timeout=5000)
            await telefono.click()
            await telefono.fill(config.telefono_principal)
            telefono_ok = True
    except Exception:
        telefono_ok = False

    if not telefono_ok:
        telefono = await _find_first_visible_input(
            page,
            [
                "input#T19b_REP_telPrincipal",
                "input[name='T19b_REP_telPrincipal']",
                "input[id*='T19b_REP_tel' i]",
                "input[name*='T19b_REP_tel' i]",
                "input[id*='telefon' i]",
                "input[name*='telefon' i]",
                "input[id*='telefono' i]",
                "input[name*='telefono' i]",
            ],
            attempts=60,
        )
        if telefono:
            await telefono.click()
            await telefono.fill(config.telefono_principal)
            telefono_ok = True

    if telefono_ok:
        logger.info("ajuntament_barcelona.documentos telefono OK")
    else:
        logger.warning("ajuntament_barcelona.documentos telefono NOT FOUND (continuando flujo)")

    await tipo_id.first.select_option("PR.R.DNI")

    cert_negativo = page.locator("#T19b_tipcert__XX\\.K\\.NEGDEUDA")
    if await cert_negativo.count():
        await cert_negativo.first.check()
    else:
        await page.get_by_role(
            "radio",
            name=re.compile(r"Certificat negatiu de deute|Certificado negativo de deuda", re.IGNORECASE),
        ).first.check()

    idioma_radio = page.locator("#T19b_idioma__DV\\.R\\.ID_CA")
    if await idioma_radio.count():
        await idioma_radio.first.check()
    else:
        await page.get_by_role(
            "radio",
            name=re.compile(r"Catal", re.IGNORECASE),
        ).first.check()

    continuar = page.locator("#continuar")
    await continuar.first.wait_for(state="visible", timeout=15000)
    await continuar.first.click()

    await page.get_by_role("button", name=re.compile(r"Enviar", re.IGNORECASE)).first.click(timeout=90000)
    try:
        await page.wait_for_load_state("networkidle", timeout=90000)
    except Exception:
        await page.wait_for_load_state("domcontentloaded", timeout=90000)

    logger.info("ajuntament_barcelona.documentos done")
    return page
