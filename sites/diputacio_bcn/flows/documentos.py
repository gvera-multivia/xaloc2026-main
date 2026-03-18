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
ALLOWED_DOC_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xml",
    ".xsig",
    ".pptx",
    ".odg",
    ".odt",
    ".ods",
    ".odp",
    ".txt",
    ".rtf",
    ".svg",
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".bmp",
    ".dwg",
    ".dxf",
    ".y",
    ".gml",
    ".zip",
}


async def _set_comment_value(page: "Page", text: str) -> str:
    comment_text = (text or "").strip()[:99]
    comment_locator = page.locator("#ComentFile, input[name='ComentFile']").first
    if await comment_locator.count() == 0:
        raise RuntimeError("No se encuentra el campo obligatorio '#ComentFile' en la pantalla de documentos.")
    await comment_locator.wait_for(state="visible", timeout=30000)

    # Click para enfocar y triple-click para seleccionar todo el contenido previo
    await comment_locator.click(click_count=3)

    # press_sequentially simula pulsaciones de teclado reales (keydown/keypress/keyup/input)
    # evitando que frameworks ASP.NET/jQuery ignoren el valor puesto con fill() directo
    await comment_locator.press_sequentially(comment_text, delay=20)

    confirmed = await page.evaluate(
        """() => {
            const el = document.querySelector("#ComentFile") || document.querySelector("input[name='ComentFile']");
            return el ? (el.value || "") : "";
        }"""
    )
    if not str(confirmed or "").strip():
        raise RuntimeError("El campo '#ComentFile' no se ha rellenado correctamente.")
    return str(confirmed or "").strip()


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
    suffix = Path(doc_path).suffix.lower()
    if suffix not in ALLOWED_DOC_EXTENSIONS:
        raise RuntimeError(
            f"Extension de documento no permitida para Diputacio BCN: '{suffix or '(sin extension)'}' en '{doc_path}'."
        )
    logger.info("Diputacio BCN docs: usando fichero '%s'", doc_path)

    comment_text = datos.comentari or f"Presentacio documentacio expedient {datos.expediente or 'N/A'}"
    real_comment_before_upload = await _set_comment_value(page, comment_text)
    logger.info("Diputacio BCN docs: descripcion establecida antes de subir (len=%s)", len(real_comment_before_upload))

    browse = page.locator("#fakeBrowse").first
    if await browse.count() == 0:
        raise RuntimeError("No se encuentra el boton de subida '#fakeBrowse' en la pantalla de documentos.")
    await browse.wait_for(state="visible", timeout=30000)

    chooser_ok = False
    try:
        async with page.expect_file_chooser(timeout=15000) as fc_info:
            await browse.click(force=True)
        fc = await fc_info.value
        await fc.set_files(doc_path)
        chooser_ok = True
    except Exception:
        chooser_ok = False

    if not chooser_ok:
        # Fallback: set_input_files directamente sobre el input file (visible u oculto)
        file_input = page.locator("input[type='file']").first
        if await file_input.count() == 0:
            raise RuntimeError(
                "No se ha podido abrir el selector de ficheros desde '#fakeBrowse' y no hay input file alternativo."
            )
        # Usar evaluate para forzar la asignación en inputs con display:none
        import base64 as _b64
        from pathlib import Path as _Path
        _file_bytes = _Path(doc_path).read_bytes()
        _file_b64 = _b64.b64encode(_file_bytes).decode()
        _file_name = _Path(doc_path).name
        await page.evaluate(
            """([b64, name]) => {
                const input = document.querySelector("input[type='file']");
                if (!input) return;
                const byteChars = atob(b64);
                const byteArr = new Uint8Array(byteChars.length);
                for (let i = 0; i < byteChars.length; i++) byteArr[i] = byteChars.charCodeAt(i);
                const file = new File([byteArr], name, { type: 'application/octet-stream' });
                const dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            [_file_b64, _file_name],
        )
        chooser_ok = True

    # Esperar a que el portal procese el upload (puede ser AJAX con UpdatePanel)
    await page.wait_for_timeout(1500)

    real_comment_after_upload = await _set_comment_value(page, comment_text)
    logger.info("Diputacio BCN docs: descripcion confirmada tras subir (len=%s)", len(real_comment_after_upload))

    # Verificar estado del formulario con espera progresiva para upload async
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
    if real_comment != real_comment_after_upload:
        raise RuntimeError(
            "El valor real de '#ComentFile' no coincide con el esperado antes de continuar."
        )
    real_file_value = str(form_state.get("fileValue") or "").strip()

    # Esperar hasta 10s a que aparezcan filas de documentos subidos (upload AJAX)
    upload_state: dict = {"uploadedRows": 0, "errors": []}
    for _attempt in range(10):
        upload_state = await page.evaluate(
            """() => {
                const rows = Array.from(document.querySelectorAll("table tr, .document-row, .file-row, [class*='upload'] tr"));
                const uploadedRows = rows.filter((tr) => {
                    const tds = tr.querySelectorAll("td");
                    if (!tds || tds.length < 2) return false;
                    const docName = (tds[0]?.textContent || "").trim();
                    const size = (tds[1]?.textContent || "").trim();
                    return Boolean(docName) && Boolean(size);
                });
                const errors = Array.from(document.querySelectorAll(".error, .text-danger, .field-validation-error, .validation-summary-errors"))
                    .map((el) => (el.textContent || "").trim())
                    .filter(Boolean);
                return {
                    uploadedRows: uploadedRows.length,
                    errors,
                };
            }"""
        )
        if int(upload_state.get("uploadedRows") or 0) > 0 or real_file_value:
            break
        await page.wait_for_timeout(1000)

    if not real_file_value and int(upload_state.get("uploadedRows") or 0) == 0:
        raise RuntimeError("No hay evidencia de fichero seleccionado antes de continuar.")
    if int(upload_state.get("uploadedRows") or 0) == 0 and not real_file_value:
        raise RuntimeError(
            f"El portal no muestra ningun documento adjunto tras la carga. errores={upload_state.get('errors')}"
        )
    logger.info(
        "Diputacio BCN docs: validado antes de continuar (comment_len=%s, file='%s', uploaded_rows=%s)",
        len(real_comment),
        real_file_value,
        upload_state.get("uploadedRows"),
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
