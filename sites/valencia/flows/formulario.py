from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .common import (
    fill_client_identification,
    fill_default_address,
    fill_identificacion_conductor,
    fill_mu_numbers,
    fill_text_if_present,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from ..config import ValenciaConfig
    from ..data_models import ValenciaTarget

logger = logging.getLogger("xaloc_automation.valencia")


def _selectors_expone(tramite_tipo: str) -> list[str]:
    if tramite_tipo in {"alegaciones_denuncia_transito", "recurso_reposicion"}:
        return [
            '[id="o0seccion_hechos-section\u2261grid-1-grid\u2261hechos-control\u2261\u2261c"]',
            '[id="o0seccion_hechos-section\u2261grid-1-grid\u2261expone-control\u2261xforms-textarea-1"]',
            '[id="o0seccion_expone-section\u2261grid-8-grid\u2261expone-control\u2261xforms-textarea-1"]',
        ]
    return [
        '[id="o0seccion_hechos-section\u2261grid-1-grid\u2261expone-control\u2261xforms-textarea-1"]',
        '[id="o0seccion_expone-section\u2261grid-8-grid\u2261expone-control\u2261xforms-textarea-1"]',
    ]


def _selectors_solicita(tramite_tipo: str) -> list[str]:
    if tramite_tipo == "alegaciones_denuncia_transito":
        return [
            '[id="o0solicitud_gral_solicita-section\u2261xf-1513\u2261grid-41-grid\u2261solicita-control\u2261\u2261c"]',
            '[id="o0seccion_hechos-section\u2261grid-4-grid\u2261solicita-control\u2261xforms-textarea-1"]',
            '[id="o0seccion_expone-section\u2261grid-9-grid\u2261solicita-control\u2261xforms-textarea-1"]',
        ]
    if tramite_tipo == "recurso_reposicion":
        return [
            '[id="o0solicitud_gral_solicita-section\u2261xf-1517\u2261grid-41-grid\u2261solicita-control\u2261\u2261c"]',
            '[id="o0seccion_hechos-section\u2261grid-4-grid\u2261solicita-control\u2261xforms-textarea-1"]',
            '[id="o0seccion_expone-section\u2261grid-9-grid\u2261solicita-control\u2261xforms-textarea-1"]',
        ]
    return [
        '[id="o0seccion_hechos-section\u2261grid-4-grid\u2261solicita-control\u2261xforms-textarea-1"]',
        '[id="o0seccion_expone-section\u2261grid-9-grid\u2261solicita-control\u2261xforms-textarea-1"]',
    ]


async def run_formulario(page: "Page", config: "ValenciaConfig", datos: "ValenciaTarget") -> "Page":
    logger.info(
        "valencia.run_formulario START idRecurso=%s expediente=%s tramite=%s code=%s",
        datos.idRecurso,
        datos.expediente,
        datos.tramite_tipo,
        datos.tramite_code,
    )
    logger.info(
        "valencia.run_formulario payload cliente tipodecliente=%s nif=%s conduc_dni=%s nifempresa=%s nombre=%s",
        datos.tipodecliente,
        datos.nif,
        datos.conduc_dni,
        datos.nifempresa,
        datos.nombre,
    )

    logger.info("valencia.run_formulario -> fill_client_identification")
    await fill_client_identification(page, datos)
    logger.info("valencia.run_formulario -> fill_default_address")
    await fill_default_address(page)

    if datos.tramite_tipo == "identificacion_conductor":
        logger.info("valencia.run_formulario -> fill_identificacion_conductor")
        await fill_identificacion_conductor(page, datos)

    logger.info("valencia.run_formulario -> fill_mu_numbers")
    await fill_mu_numbers(page, datos)

    expone_text = (datos.expone or "").strip()
    solicita_text = (datos.solicita or "").strip()
    requires_text_fields = datos.tramite_tipo in {"alegaciones_denuncia_transito", "recurso_reposicion"}
    if requires_text_fields:
        if not expone_text:
            raise ValueError("valencia: falta texto 'expone' para tramite con hechos/solicita obligatorio")
        if not solicita_text:
            raise ValueError("valencia: falta texto 'solicita' para tramite con hechos/solicita obligatorio")
    if requires_text_fields:
        expone_filled = await fill_text_if_present(
            page,
            selectors=_selectors_expone(datos.tramite_tipo),
            text=expone_text,
        )
        logger.info(
            "valencia.run_formulario -> expone completado filled=%s len=%s",
            expone_filled,
            len(expone_text),
        )
        if expone_text and not expone_filled:
            raise ValueError(f"valencia: no se pudo rellenar 'expone' para tramite={datos.tramite_tipo}")

        solicita_filled = await fill_text_if_present(
            page,
            selectors=_selectors_solicita(datos.tramite_tipo),
            text=solicita_text,
        )
        logger.info(
            "valencia.run_formulario -> solicita completado filled=%s len=%s",
            solicita_filled,
            len(solicita_text),
        )
        if solicita_text and not solicita_filled:
            raise ValueError(f"valencia: no se pudo rellenar 'solicita' para tramite={datos.tramite_tipo}")
    else:
        logger.info(
            "valencia.run_formulario -> omitir expone/solicita para tramite=%s",
            datos.tramite_tipo,
        )

    logger.info("valencia.run_formulario -> save form selector=%s", config.save_form_selector)
    await page.locator(config.save_form_selector).click()
    await page.wait_for_load_state("networkidle")
    logger.info("valencia.run_formulario END")
    return page
