"""
Flujo para el formulario de Recurso de Reposición (P3).
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Page

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineReposicionData
from sites.base_online.flows.firma_y_justificante import firmar_presentar_y_descargar_justificante
from sites.base_online.flows.upload import subir_archivos_por_modal


def _normalizar_tipus_objecte(raw: str) -> str:
    valor = (raw or "").strip().upper()
    if valor in {"IBI"}:
        return "IBI"
    if valor in {"IVTM"}:
        return "IVTM"
    if valor in {"EXPEDIENTE EJECUTIVO", "EXPEDIENTE_EJECUTIVO", "EXPEDIENT EXECUTIU", "EXPEDIENT_EXECUTIU"}:
        return "EXPEDIENTE EJECUTIVO"
    if valor in {"OTROS", "ALTRES"}:
        return "OTROS"
    raise ValueError(f"tipus_objecte inválido: {raw}. Usa IBI, IVTM, Expediente Ejecutivo u Otros.")


async def _avanzar_a_presentacion_p3(page: Page) -> None:
    logging.info("[P3] Continuando al paso de presentacion...")
    await page.locator("input[type='submit'][name='form0:j_id66'][value='Continuar']").first.click()
    await page.wait_for_timeout(1000)
    await page.wait_for_load_state("domcontentloaded")

    boton_firma = page.locator("input[type='button'][value='Signar i Presentar']").first
    await boton_firma.wait_for(state="visible", timeout=20000)
    logging.info("[P3] Pantalla 'Signar i Presentar' detectada.")


async def _set_textarea_stable(
    page: Page,
    selector: str,
    value: str | None,
    *,
    label: str,
    wait_ms: int,
    retries: int = 3,
) -> None:
    expected = str(value or "").strip()
    locator = page.locator(selector).first
    await locator.wait_for(state="visible", timeout=20000)
    await locator.scroll_into_view_if_needed()

    for intento in range(1, retries + 1):
        await locator.click()
        await locator.fill("")
        if expected:
            await locator.type(expected, delay=20)

        ok = await page.evaluate(
            """([sel, val]) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                const expected = String(val || '').trim();
                const current = String(el.value || '').trim();
                if (current !== expected) {
                    el.value = expected;
                }
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                return String(el.value || '').trim() === expected;
            }""",
            [selector, expected],
        )
        current = (await locator.input_value()).strip()
        if ok and current == expected:
            return

        logging.warning(
            "[P3] Reintento %s/%s al persistir %s (actual=%r esperado=%r)",
            intento,
            retries,
            label,
            current,
            expected,
        )
        await page.wait_for_timeout(wait_ms)

    raise ValueError(f"[P3] No se pudo persistir el campo {label}.")


async def rellenar_formulario_p3(
    page: Page,
    config: BaseOnlineConfig,
    data: BaseOnlineReposicionData,
    *,
    payload: dict,
) -> None:
    logging.info("[P3] Rellenando formulario de Recurso de Reposicion...")
    delay_ms = getattr(config, "delay_ms", 1000)

    # 1. Inputs radio: tipo de objeto
    tipus_objecte = _normalizar_tipus_objecte(data.tipus_objecte)
    radio_selector = {
        "IBI": config.p3_radio_ibi,
        "IVTM": config.p3_radio_ivtm,
        "EXPEDIENTE EJECUTIVO": config.p3_radio_executiu,
        "OTROS": config.p3_radio_altres,
    }[tipus_objecte]
    logging.info(f"[P3] Seleccionando tipo de objeto: {tipus_objecte}")
    await page.locator(radio_selector).first.click()
    await page.wait_for_timeout(delay_ms)

    # 2. Dades específiques
    logging.info("[P3] Introduciendo datos especificos...")
    await _set_textarea_stable(
        page,
        config.p3_textarea_dades,
        data.dades_especifiques,
        label="dades_especifiques",
        wait_ms=delay_ms,
    )
    await page.wait_for_timeout(delay_ms)

    # 3. Tipo de solicitud
    logging.info(f"[P3] Seleccionando tipo de solicitud: value={data.tipus_solicitud_value}")
    await page.locator(config.p3_select_tipus).first.select_option(value=str(data.tipus_solicitud_value))
    await page.wait_for_timeout(delay_ms)

    # 4. Exposición
    logging.info("[P3] Introduciendo exposicion...")
    await _set_textarea_stable(
        page,
        config.p3_textarea_exposo,
        data.exposo,
        label="exposo",
        wait_ms=delay_ms,
    )
    await page.wait_for_timeout(delay_ms)

    # 5. Solicitud
    logging.info("[P3] Introduciendo solicitud...")
    await _set_textarea_stable(
        page,
        config.p3_textarea_solicito,
        data.solicito,
        label="solicito",
        wait_ms=delay_ms,
    )
    await page.wait_for_timeout(delay_ms)

    # 6. Botón Continuar (Página 1 -> Página Documentos)
    logging.info("[P3] Pulsando el boton de continuar...")
    await page.locator(config.p3_button_continuar).first.click()
    await page.wait_for_timeout(delay_ms)
    await page.wait_for_load_state("domcontentloaded")

    # 7. Subida de documentos (modal + iframe)
    archivos = data.archivos_adjuntos or []
    archivos_paths: list[Path] = list(archivos)
    await subir_archivos_por_modal(page, archivos_paths)

    # 8. Confirmación (llegar hasta la pantalla de firma)
    await _avanzar_a_presentacion_p3(page)

    # 9. Firma + presentación + descarga del justificante
    await firmar_presentar_y_descargar_justificante(page, payload=payload)
