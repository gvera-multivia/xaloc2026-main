from __future__ import annotations

import logging
import os
from pathlib import Path

import aiohttp

from core.attachments import AttachmentDownloader, AttachmentInfo
from .utils import extract_expediente_number, sanitize_filename_component

DOCUMENT_URL_TEMPLATE = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/{idRecurso}"
DOWNLOAD_DIR = Path("tmp/downloads")

logger = logging.getLogger("worker.document_fetcher")


async def download_document_and_attachments(
    *,
    payload: dict,
    auth_session: aiohttp.ClientSession,
) -> list[Path]:
    payload_file_keys = ("archivos", "archivos_adjuntos", "p1_archivos", "p2_archivos", "p3_archivos")
    payload_files_raw: list[Path] = []
    for key in payload_file_keys:
        raw_val = payload.get(key)
        if not raw_val:
            continue
        if isinstance(raw_val, (str, Path)):
            payload_files_raw.append(Path(raw_val))
            continue
        if isinstance(raw_val, list):
            for item in raw_val:
                if isinstance(item, (str, Path)):
                    payload_files_raw.append(Path(item))

    id_recurso = payload.get("idRecurso")
    if not id_recurso:
        raise ValueError("Falta 'idRecurso' en el payload para descargar el documento.")

    target_url = DOCUMENT_URL_TEMPLATE.format(idRecurso=id_recurso)
    logger.info("Iniciando descarga autenticada desde: %s", target_url)

    n_expediente = sanitize_filename_component(extract_expediente_number(payload))
    local_pdf_path = DOWNLOAD_DIR / f"RECURSO exp - {n_expediente}.pdf"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    async with auth_session.get(target_url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"El servidor respondio con status {resp.status} al pedir el PDF.")

        content = await resp.read()
        if content.startswith(b"%PDF"):
            local_pdf_path.write_bytes(content)
        else:
            sample = content[:200].decode(errors="ignore")
            if "login" in sample.lower() or "password" in sample.lower():
                raise RuntimeError("Sesion invalida o expirada (redirigido al login).")
            raise RuntimeError("El archivo descargado no es un PDF valido.")

    archivos_para_subir: list[Path] = [local_pdf_path]
    adjuntos_metadata = payload.get("adjuntos", [])
    if adjuntos_metadata:
        attachment_downloader = AttachmentDownloader()
        attachments_info = [
            AttachmentInfo(id=adj["id"], filename=adj["filename"], url=adj["url"])
            for adj in adjuntos_metadata
        ]
        download_results = await attachment_downloader.download_batch(
            attachments_info,
            str(id_recurso),
            session=auth_session,
        )
        for result in download_results:
            if result.success and result.local_path:
                archivos_para_subir.append(result.local_path)
            else:
                logger.warning("No se pudo descargar adjunto %s: %s", result.filename, result.error)

    merged: list[Path] = []
    seen_keys: set[str] = set()

    def _key(p: Path) -> str:
        return os.path.normcase(os.path.normpath(str(p)))

    for p in archivos_para_subir:
        if not p:
            continue
        k = _key(p)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        merged.append(p)

    for p in payload_files_raw:
        if not p:
            continue
        k = _key(p)
        if k in seen_keys:
            continue
        if not p.exists():
            logger.warning("Archivo del payload no encontrado, se omite: %s", p)
            continue
        seen_keys.add(k)
        merged.append(p)

    payload["archivos"] = [str(p) for p in merged if p]
    return merged
