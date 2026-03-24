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

MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB
MAX_DOC_SLOTS = 5  # Maximo de documentos permitidos por el formulario


async def _file_input_ids(scope: "Page | Frame") -> list[str]:
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


async def _wait_file_input_ids(scope: "Page | Frame", timeout_ms: int) -> list[str]:
    waited = 0
    step_ms = 1000
    last_ids: list[str] = []
    while waited <= timeout_ms:
        last_ids = await _file_input_ids(scope)
        if len(last_ids) >= 2:
            return last_ids
        await scope.wait_for_timeout(step_ms)
        waited += step_ms
    return last_ids


async def _upload_to_input(scope: "Page | Frame", input_id: str, file_path: Path) -> None:
    selector = f'[id="{input_id}"]'
    await scope.locator(selector).set_input_files(str(file_path))
    await scope.wait_for_timeout(700)


def _is_within_size_limit(file_path: Path) -> bool:
    try:
        return file_path.stat().st_size <= MAX_FILE_SIZE_BYTES
    except Exception:
        return False


def _classify_files(files: list[Path]) -> tuple[Path | None, Path | None, list[Path]]:
    """Clasifica archivos en recurso, autorizacion y resto. Filtra > 1MB."""
    recurso: Path | None = None
    autorizacion: Path | None = None
    rest: list[Path] = []

    # 1. Prioridad absoluta al archivo descargado de XVIA (nombre especifico)
    for f in files:
        if "RECURSO EXP -" in f.name.upper():
            recurso = f
            break

    for f in files:
        if not f.exists():
            continue
        if not _is_within_size_limit(f):
            logger.warning(
                "servei_cat_trans.documentos: archivo %s excede 1MB (%.2f MB), se omite.",
                f.name,
                f.stat().st_size / (1024 * 1024),
            )
            continue

        if f == recurso:
            continue

        name_upper = f.name.upper()
        # Si no hay recurso de XVIA, buscar uno por palabra clave
        if recurso is None and ("RECUR" in name_upper or "ALEGACI" in name_upper):
            recurso = f
        # Buscar autorizacion
        elif autorizacion is None and ("AUT" in name_upper or "ACREDITA" in name_upper):
            autorizacion = f
        else:
            rest.append(f)

    return recurso, autorizacion, rest


async def run_documentos(page: "Page", config: "ServeiCatTransConfig", datos: "ServeiCatTransTarget") -> "Page":
    files = [Path(p) for p in (datos.archivos_para_subir or []) if Path(p).exists()]
    if not files:
        logger.warning("servei_cat_trans.documentos: no hay archivos para subir.")
        return page

    recurso, autorizacion, rest = _classify_files(files)

    form_scope = await wait_form_scope(page, timeout_ms=config.upload_inputs_timeout_ms)
    input_ids = await _wait_file_input_ids(form_scope, timeout_ms=config.upload_inputs_timeout_ms)
    if len(input_ids) < 2:
        logger.warning(
            "servei_cat_trans.documentos: no se detectaron inputs file suficientes tras espera (%sms).",
            config.upload_inputs_timeout_ms,
        )
        return page

    # Orden observado en este formulario:
    # [0]=uploader interno (no usar), [1..5]=docs opcionales, [6]=acreditacion.
    doc_slots = input_ids[1:6]  # 5 slots maximo
    acreditacion_slot = input_ids[6] if len(input_ids) > 6 else ""

    # Montar la lista ordenada: Recurso PRIMERO, Autorizacion ULTIMO, resto en medio
    ordered: list[Path] = []
    if recurso:
        ordered.append(recurso)
    # Rellenar con el resto hasta dejar sitio para autorizacion al final
    max_middle = MAX_DOC_SLOTS - (1 if recurso else 0) - (1 if autorizacion else 0)
    ordered.extend(rest[:max_middle])
    if autorizacion:
        ordered.append(autorizacion)

    logger.info(
        "servei_cat_trans.documentos: subiendo %d archivos (max %d, max 1MB). Recurso=%s, Autorizacion=%s",
        len(ordered),
        MAX_DOC_SLOTS,
        recurso.name if recurso else "N/A",
        autorizacion.name if autorizacion else "N/A",
    )

    for file_path, slot_id in zip(ordered, doc_slots):
        logger.info("  -> subiendo %s (%.2f KB)", file_path.name, file_path.stat().st_size / 1024)
        await _upload_to_input(form_scope, slot_id, file_path)

    # Acreditacion para persona juridica (slot especifico separado)
    if datos.tipo_persona == "juridica" and acreditacion_slot and autorizacion:
        logger.info("  -> subiendo acreditacion (slot especial): %s", autorizacion.name)
        await _upload_to_input(form_scope, acreditacion_slot, autorizacion)

    return page

