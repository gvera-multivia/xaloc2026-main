from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .common import upload_documents

if TYPE_CHECKING:
    from playwright.async_api import Page

    from ..config import ValenciaConfig
    from ..data_models import ValenciaTarget

logger = logging.getLogger("xaloc_automation.valencia")


def _is_authorization_doc(path: Path) -> bool:
    name = path.name.upper()
    return any(token in name for token in ("AUTORIZ", "AUTORITZ"))


def _is_xvia_resource_doc(path: Path) -> bool:
    name = path.name.upper()
    return any(token in name for token in ("RECURSO", "RECURS", "JUSTIFICAT", "JUSTIFICANTE"))


def _stable_key(path: Path) -> str:
    return re.sub(r"[\\/]+", "/", str(path).strip()).lower()


def _pick_first(files: list[Path], predicate, used: set[str]) -> Path | None:
    for file_path in files:
        key = _stable_key(file_path)
        if key in used:
            continue
        if predicate(file_path):
            used.add(key)
            return file_path
    return None


def order_documents_for_upload(files: list[Path], tramite_tipo: str) -> list[Path]:
    used: set[str] = set()
    ordered: list[Path] = []
    is_identificacion = tramite_tipo == "identificacion_conductor"

    auth_doc = _pick_first(files, _is_authorization_doc, used)
    recurso_doc = _pick_first(files, _is_xvia_resource_doc, used)

    if is_identificacion:
        if auth_doc:
            ordered.append(auth_doc)
        if recurso_doc:
            ordered.append(recurso_doc)
    else:
        if recurso_doc:
            ordered.append(recurso_doc)
        if auth_doc:
            ordered.append(auth_doc)

    for file_path in files:
        key = _stable_key(file_path)
        if key in used:
            continue
        used.add(key)
        ordered.append(file_path)
    return ordered


async def run_documentos(page: "Page", config: "ValenciaConfig", datos: "ValenciaTarget") -> "Page":
    _ = config
    files = [Path(p) for p in datos.archivos_para_subir if str(p).strip()]
    logger.info("valencia.run_documentos archivos detectados para subir=%s", len(files))
    if not files:
        return page
    ordered_files = order_documents_for_upload(files, datos.tramite_tipo)
    logger.info("valencia.run_documentos archivos ordenados para subir=%s", len(ordered_files))
    await upload_documents(page, ordered_files)
    return page
