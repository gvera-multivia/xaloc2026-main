from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Frame, Page
    from ..config import ServeiCatTransConfig
    from ..data_models import ServeiCatTransTarget

from .form_scope import wait_form_scope


logger = logging.getLogger("xaloc_automation.servei_cat_trans")


async def _visible_file_input_ids(scope: "Page | Frame") -> list[str]:
    result = await scope.evaluate(
        """() => {
            return Array.from(document.querySelectorAll("input[type='file']"))
                .map((el) => el.id)
                .filter((id) => !!id);
        }"""
    )
    if not isinstance(result, list):
        return []
    return [str(item).strip() for item in result if str(item).strip()]


async def _wait_visible_file_input_ids(scope: "Page | Frame", timeout_ms: int) -> list[str]:
    waited = 0
    step_ms = 1000
    last_ids: list[str] = []
    while waited <= timeout_ms:
        last_ids = await _visible_file_input_ids(scope)
        if len(last_ids) >= 2:
            return last_ids
        await scope.wait_for_timeout(step_ms)
        waited += step_ms
    return last_ids


async def _upload_to_input(scope: "Page | Frame", input_id: str, file_path: Path) -> None:
    selector = f'[id="{input_id}"]'
    await scope.locator(selector).set_input_files(str(file_path))
    await scope.wait_for_timeout(700)


async def run_documentos(page: "Page", config: "ServeiCatTransConfig", datos: "ServeiCatTransTarget") -> "Page":
    _ = config
    files = [Path(p) for p in (datos.archivos_para_subir or []) if Path(p).exists()]
    if not files:
        return page

    form_scope = await wait_form_scope(page, timeout_ms=config.upload_inputs_timeout_ms)
    input_ids = await _wait_visible_file_input_ids(form_scope, timeout_ms=config.upload_inputs_timeout_ms)
    if len(input_ids) < 2:
        logger.warning(
            "servei_cat_trans.documentos: no se detectaron inputs file visibles suficientes tras espera (%sms).",
            config.upload_inputs_timeout_ms,
        )
        return page

    # Orden observado en este formulario:
    # [0]=uploader interno, [1..4]=docs opcionales, [5]=acreditacion.
    doc_slots = input_ids[1:5]
    acreditacion_slot = input_ids[5] if len(input_ids) > 5 else ""

    for file_path, slot_id in zip(files[:4], doc_slots):
        await _upload_to_input(form_scope, slot_id, file_path)

    if datos.tipo_persona == "juridica" and acreditacion_slot:
        acreditacion_from_payload = Path(str(datos.payload.get("acreditacion_path") or "")).expanduser()
        if acreditacion_from_payload.exists():
            acreditacion_file = acreditacion_from_payload
        elif len(files) >= 5:
            acreditacion_file = files[4]
        else:
            acreditacion_file = files[-1]
        await _upload_to_input(form_scope, acreditacion_slot, acreditacion_file)

    return page
