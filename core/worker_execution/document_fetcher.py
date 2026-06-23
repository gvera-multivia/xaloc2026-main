from __future__ import annotations

import logging
import os
from pathlib import Path

import aiohttp

from core.attachments import AttachmentDownloader, AttachmentInfo
from core.xvia_auth import _reauth_xvia_session
from .utils import extract_expediente_number, sanitize_filename_component

DOCUMENT_URL_TEMPLATE = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/{idRecurso}"
DOWNLOAD_DIR = Path("tmp/downloads")

logger = logging.getLogger("worker.document_fetcher")


def _looks_like_html_response(content: bytes) -> bool:
    sample = content[:512].decode(errors="ignore").lstrip().lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html")


def _looks_like_login_or_xvia_html(content: bytes) -> bool:
    sample = content[:1500].decode(errors="ignore").lower()
    return (
        "xvia" in sample
        or "grupoeuropa" in sample
        or 'name="_token"' in sample
        or "csrf-token" in sample
        or "type=\"password\"" in sample
        or "type='password'" in sample
        or "iniciar sesion" in sample
        or "inicia sesion" in sample
    )


async def _download_primary_pdf_bytes(
    *,
    target_url: str,
    auth_session: aiohttp.ClientSession,
) -> bytes:
    last_error: RuntimeError | None = None

    for attempt in (1, 2):
        async with auth_session.get(target_url, allow_redirects=True) as resp:
            final_url = str(resp.url)
            content_type = str(resp.headers.get("content-type") or "")
            content = await resp.read()

        logger.info(
            "document_fetcher: intento=%s status=%s final_url=%s content_type=%s prefix=%r",
            attempt,
            getattr(resp, "status", "unknown"),
            final_url,
            content_type,
            content[:40],
        )

        if resp.status != 200:
            raise RuntimeError(f"El servidor respondio con status {resp.status} al pedir el PDF.")

        if content.startswith(b"%PDF"):
            return content

        login_redirect = "login" in final_url.lower()
        html_like = _looks_like_html_response(content)
        xvia_like = _looks_like_login_or_xvia_html(content)
        if attempt == 1 and (login_redirect or (html_like and xvia_like)):
            logger.warning(
                "document_fetcher: respuesta no PDF con pinta de sesion expirada/login. "
                "Reautenticando y reintentando una vez. final_url=%s content_type=%s",
                final_url,
                content_type,
            )
            if await _reauth_xvia_session(auth_session):
                continue
            raise RuntimeError("Sesion invalida o expirada (redirigido al login).")

        sample = content[:200].decode(errors="ignore")
        if login_redirect or (html_like and xvia_like):
            raise RuntimeError("Sesion invalida o expirada (redirigido al login).")

        last_error = RuntimeError(
            "El archivo descargado no es un PDF valido. "
            f"content_type={content_type or 'unknown'} final_url={final_url} sample={sample!r}"
        )
        break

    if last_error is not None:
        raise last_error
    raise RuntimeError("El archivo descargado no es un PDF valido.")


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
    if id_recurso in (None, ""):
        id_recurso = payload.get("external_resource_id")
    if id_recurso in (None, ""):
        id_recurso = payload.get("resource_id")
    if not id_recurso:
        raise ValueError("Falta 'idRecurso' en el payload para descargar el documento.")
    payload["idRecurso"] = id_recurso

    target_url = DOCUMENT_URL_TEMPLATE.format(idRecurso=id_recurso)
    logger.info("Iniciando descarga autenticada desde: %s", target_url)

    n_expediente = sanitize_filename_component(extract_expediente_number(payload))
    local_pdf_path = DOWNLOAD_DIR / f"RECURSO exp - {n_expediente}.pdf"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    content = await _download_primary_pdf_bytes(target_url=target_url, auth_session=auth_session)
    local_pdf_path.write_bytes(content)

    archivos_para_subir: list[Path] = [local_pdf_path]
    payload["xvia_recurso_path"] = str(local_pdf_path)
    xvia_attachment_paths: list[str] = []
    adjuntos_metadata = payload.get("adjuntos", [])
    if adjuntos_metadata:
        attachment_downloader = AttachmentDownloader()
        attachments_info: list[AttachmentInfo] = []
        for adj in adjuntos_metadata:
            if not isinstance(adj, dict):
                logger.warning("Adjunto invalido (no dict), se omite: %r", adj)
                continue

            raw_id = adj.get("id")
            if raw_id is None:
                raw_id = adj.get("attachment_id")
            if raw_id is None:
                raw_id = adj.get("adjunto_id")
            if raw_id is None:
                logger.warning("Adjunto sin id, se omite: %r", adj)
                continue
            att_id = str(raw_id).strip()
            if not att_id:
                logger.warning("Adjunto con id vacio, se omite: %r", adj)
                continue

            raw_filename = adj.get("filename")
            if raw_filename is None:
                raw_filename = adj.get("name")
            if raw_filename is None:
                raw_filename = f"adjunto_{att_id}.pdf"
            filename = str(raw_filename).strip() or f"adjunto_{att_id}.pdf"

            raw_url = adj.get("url")
            if raw_url is None:
                raw_url = adj.get("download_url")
            if raw_url is None:
                raw_url = adj.get("href")
            url = str(raw_url).strip() if raw_url is not None else ""
            if not url:
                url = attachment_downloader.build_url(att_id)

            attachments_info.append(AttachmentInfo(id=att_id, filename=filename, url=url))

        if not attachments_info:
            logger.info("No hay adjuntos descargables validos para idRecurso=%s.", id_recurso)
            payload["archivos"] = [str(p) for p in archivos_para_subir if p]
            return archivos_para_subir

        download_results = await attachment_downloader.download_batch(
            attachments_info,
            str(id_recurso),
            session=auth_session,
        )
        for result in download_results:
            if result.success and result.local_path:
                archivos_para_subir.append(result.local_path)
                xvia_attachment_paths.append(str(result.local_path))
            else:
                logger.warning("No se pudo descargar adjunto %s: %s", result.filename, result.error)
    payload["xvia_attachment_paths"] = xvia_attachment_paths

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
            p_norm = _key(p)
            if "tmp" in p_norm and "ayunta_palma" in p_norm:
                logger.info("Archivo temporal antiguo de payload, se omite: %s", p)
            else:
                logger.warning("Archivo del payload no encontrado, se omite: %s", p)
            continue
        seen_keys.add(k)
        merged.append(p)

    payload["archivos"] = [str(p) for p in merged if p]
    return merged
