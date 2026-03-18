from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import DiputacioBcnConfig
    from ..data_models import DiputacioBcnTarget

logger = logging.getLogger("sites.diputacio_bcn.documentos")


def _existing_file(path_value: str) -> str:
    candidate = Path(str(path_value or "").strip())
    if candidate and candidate.exists() and candidate.is_file():
        return str(candidate)
    return ""


def _pick_latest_open_page(page: "Page") -> "Page":
    if not page.is_closed():
        return page
    pages = [p for p in page.context.pages if not p.is_closed()]
    if not pages:
        raise RuntimeError("No hay pestañas activas durante el paso de documentos.")
    return pages[-1]


async def _resolve_documents_page(page: "Page", timeout_ms: int = 30000) -> "Page":
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        for candidate in [p for p in page.context.pages if not p.is_closed()]:
            if await candidate.locator("#fakeBrowse").count() > 0:
                return candidate
            if await candidate.locator("#ComentFile").count() > 0:
                return candidate
        await page.wait_for_timeout(300)
    raise RuntimeError(
        "No se ha localizado la pantalla de documentos (#fakeBrowse/#ComentFile) dentro del timeout."
    )


async def run_documentos(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = config
    page = _pick_latest_open_page(page)
    page = await _resolve_documents_page(page, timeout_ms=45000)

    doc_path = _existing_file(datos.doc_tramite) or _existing_file(datos.doc_acreditativa)
    if not doc_path:
        raise RuntimeError(
            "Falta documento de tramite. Define DIPUTACIO_BCN_DOC_TRAMITE o payload.doc_tramite."
        )
    logger.info("Diputacio BCN docs: usando fichero '%s'", doc_path)

    browse = page.locator("#fakeBrowse").first
    if await browse.count() == 0:
        raise RuntimeError("No se encuentra el boton de subida '#fakeBrowse' en la pantalla de documentos.")
    await browse.wait_for(state="visible", timeout=30000)

    chooser_ok = False
    try:
        async with page.expect_file_chooser() as fc_info:
            await browse.click(force=True)
        fc = await fc_info.value
        await fc.set_files(doc_path)
        chooser_ok = True
    except Exception:
        chooser_ok = False

    if not chooser_ok:
        file_input = page.locator("input[type='file']").first
        if await file_input.count() == 0:
            raise RuntimeError(
                "No se ha podido abrir el selector de ficheros desde '#fakeBrowse' y no hay input file alternativo."
            )
        await file_input.set_input_files(doc_path)

    coment = page.locator("#ComentFile").first
    if await coment.count() == 0:
        raise RuntimeError("No se encuentra el campo obligatorio '#ComentFile' en la pantalla de documentos.")
    await coment.wait_for(state="visible", timeout=30000)
    comment_text = datos.comentari or f"Presentacio documentacio expedient {datos.expediente or 'N/A'}"
    await coment.fill(comment_text)
    filled_value = await coment.input_value()
    if not filled_value.strip():
        raise RuntimeError("El campo '#ComentFile' no se ha rellenado correctamente.")

    form_state = await page.evaluate(
        """() => {
            const file = document.querySelector("input[type='file']");
            const comment = document.querySelector("#ComentFile");
            return {
                fileValue: file ? (file.value || "") : "",
                commentValue: comment ? (comment.value || "") : "",
            };
        }"""
    )
    real_comment = str(form_state.get("commentValue") or "").strip()
    if real_comment != comment_text.strip():
        raise RuntimeError(
            "El valor real de '#ComentFile' no coincide con el esperado antes de continuar."
        )
    real_file_value = str(form_state.get("fileValue") or "").strip()
    if not real_file_value:
        raise RuntimeError("No hay evidencia de fichero seleccionado antes de continuar.")
    logger.info(
        "Diputacio BCN docs: validado antes de continuar (comment_len=%s, file='%s')",
        len(real_comment),
        real_file_value,
    )
    try:
        await page.screenshot(
            path=config.dir_screenshots / "diputacio_bcn_docs_before_continue.png",
            full_page=True,
        )
    except Exception:
        pass

    submit = page.locator("input[type='submit'][value='Continuar']").first
    if await submit.count() == 0:
        raise RuntimeError("No se encuentra el boton 'Continuar' tras subir documento/comentario.")
    await submit.click()

    try:
        await page.locator("#InfoMobil2").first.wait_for(state="visible", timeout=12000)
    except Exception as exc:
        diagnostics = await page.evaluate(
            """() => {
                const pickText = (selectors) =>
                    selectors
                        .flatMap((sel) => Array.from(document.querySelectorAll(sel)))
                        .map((el) => (el.textContent || "").trim())
                        .filter(Boolean);
                const errors = pickText([
                    ".validation-summary-errors",
                    ".field-validation-error",
                    ".error",
                    ".alert",
                    ".alert-danger",
                    ".text-danger",
                ]);
                const file = document.querySelector("input[type='file']");
                const comment = document.querySelector("#ComentFile");
                return {
                    errors,
                    fileValue: file ? (file.value || "") : "",
                    commentValue: comment ? (comment.value || "") : "",
                    url: window.location.href,
                };
            }"""
        )
        raise RuntimeError(
            "No avanza a pantalla de contacto tras continuar documentos. "
            f"url={diagnostics.get('url')} "
            f"file='{diagnostics.get('fileValue')}' "
            f"comment_len={len(str(diagnostics.get('commentValue') or ''))} "
            f"errors={diagnostics.get('errors')}"
        ) from exc

    await page.locator("#InfoMobil2").fill(datos.telefon or "600000000")
    await page.locator("#InfoMail2").fill(datos.email or "notificacions@example.com")

    uncheck = page.locator("#uncheckNEPO2")
    if await uncheck.count() > 0:
        await uncheck.first.click()

    await page.locator("input[type='submit'][value='Continuar']").first.click()
    return _pick_latest_open_page(page)
