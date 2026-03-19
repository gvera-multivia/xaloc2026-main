from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from core.client_paths import resolve_client_docs_base_path

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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalized_lower_path(path_value: str) -> str:
    return str(path_value or "").replace("\\", "/").strip().lower()


def _runtime_path_candidates(path_value: str) -> list[Path]:
    raw = str(path_value or "").strip()
    if not raw:
        return []

    candidates: list[Path] = []
    seen: set[str] = set()

    def _append(candidate: Path | str | None) -> None:
        if not candidate:
            return
        text = str(candidate).strip()
        if not text:
            return
        key = _normalized_lower_path(text)
        if key in seen:
            return
        seen.add(key)
        candidates.append(Path(text).expanduser())

    raw_path = Path(raw).expanduser()
    _append(raw_path)

    if not raw_path.is_absolute():
        _append((_repo_root() / raw_path).resolve())

    normalized = raw.replace("\\", "/")
    repo_name = _repo_root().name.lower()
    repo_parts = [part for part in normalized.split("/") if part]
    for idx, part in enumerate(repo_parts):
        if part.lower() != repo_name:
            continue
        suffix = repo_parts[idx + 1 :]
        if suffix:
            _append(_repo_root().joinpath(*suffix))
        break

    clientes_match = re.search(r"(?i)(?:^|/)(clientes)(?:/|$)", normalized)
    if clientes_match:
        suffix_raw = normalized[clientes_match.end() :]
        suffix_parts = [part for part in suffix_raw.split("/") if part]
        client_mount = Path(resolve_client_docs_base_path())
        _append(client_mount.joinpath(*suffix_parts) if suffix_parts else client_mount)

    return candidates


async def _set_comment_value(page: "Page", text: str) -> str:
    comment_text = (text or "").strip()[:99]
    logger.info("Diputacio BCN docs: escribiendo ComentFile='%s' len=%s", comment_text, len(comment_text))
    comment_locator = page.locator("#ComentFile, input[name='ComentFile']").first
    if await comment_locator.count() == 0:
        raise RuntimeError("No se encuentra el campo obligatorio '#ComentFile' en la pantalla de documentos.")
    await comment_locator.wait_for(state="visible", timeout=30000)
    try:
        await comment_locator.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        await comment_locator.fill(comment_text)
    except Exception:
        pass
    await page.evaluate(
        """(txt) => {
            const el = document.querySelector("#ComentFile") || document.querySelector("input[name='ComentFile']");
            if (!el) return;
            const proto = window.HTMLInputElement?.prototype;
            const setter = proto ? Object.getOwnPropertyDescriptor(proto, "value")?.set : null;
            if (setter) setter.call(el, txt);
            else el.value = txt;
            for (const eventName of ["focus", "input", "change", "keyup", "blur"]) {
                el.dispatchEvent(new Event(eventName, { bubbles: true }));
            }
        }""",
        comment_text,
    )

    confirmed = await page.evaluate(
        """() => {
            const el = document.querySelector("#ComentFile") || document.querySelector("input[name='ComentFile']");
            return el ? (el.value || "") : "";
        }"""
    )
    confirmed_text = str(confirmed or "").strip()
    if not confirmed_text:
        raise RuntimeError("El campo '#ComentFile' no se ha rellenado correctamente.")
    logger.info("Diputacio BCN docs: ComentFile confirmado='%s' len=%s", confirmed_text, len(confirmed_text))
    return confirmed_text


def _existing_file(path_value: str) -> str:
    candidates = _runtime_path_candidates(path_value)
    logger.info("Diputacio BCN docs: resolviendo fichero raw='%s' candidates=%s", path_value, [str(p) for p in candidates])
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                resolved = str(candidate.resolve())
                logger.info("Diputacio BCN docs: fichero resuelto raw='%s' -> '%s'", path_value, resolved)
                return resolved
        except Exception:
            continue
    logger.warning("Diputacio BCN docs: no se encontro fichero para raw='%s'", path_value)
    return ""


def _collect_upload_paths(datos: "DiputacioBcnTarget") -> list[str]:
    candidates: list[str] = []
    # Primero autorizacion (acreditativa), luego tramite.
    if datos.doc_acreditativa:
        candidates.append(datos.doc_acreditativa)
    if datos.doc_tramite:
        candidates.append(datos.doc_tramite)
    candidates.extend([str(p) for p in (datos.archivos_adjuntos or [])])

    merged: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        p = _existing_file(raw)
        if not p:
            continue
        key = str(Path(p).resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(p)
    logger.info("Diputacio BCN docs: lote raw=%s resolved=%s", candidates, merged)
    return merged


def _pick_latest_open_page(page: "Page") -> "Page":
    if not page.is_closed():
        return page
    pages = [p for p in page.context.pages if not p.is_closed()]
    if not pages:
        raise RuntimeError("No hay pestanas activas durante el paso de documentos.")
    return pages[-1]


async def _resolve_documents_page(page: "Page", timeout_ms: int = 30000) -> "Page":
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        for candidate in [p for p in page.context.pages if not p.is_closed()]:
            if await candidate.locator("#fakeBrowse").count() > 0:
                logger.info("Diputacio BCN docs: pantalla documentos localizada por #fakeBrowse url=%s", candidate.url)
                return candidate
            if await candidate.locator("#ComentFile").count() > 0:
                logger.info("Diputacio BCN docs: pantalla documentos localizada por #ComentFile url=%s", candidate.url)
                return candidate
        await page.wait_for_timeout(300)
    raise RuntimeError("No se ha localizado la pantalla de documentos (#fakeBrowse/#ComentFile) dentro del timeout.")


async def _uploaded_rows_count(page: "Page") -> int:
    count = await page.evaluate(
        """() => {
            const rows = Array.from(document.querySelectorAll("table tr, .document-row, .file-row, [class*='upload'] tr"));
            const uploadedRows = rows.filter((tr) => {
                const tds = tr.querySelectorAll("td");
                if (!tds || tds.length < 2) return false;
                const docName = (tds[0]?.textContent || "").trim();
                const size = (tds[1]?.textContent || "").trim();
                if (!docName || !size) return false;
                if (docName.toLowerCase() === "documento" && size.toLowerCase() === "tamaño") return false;
                return true;
            });
            return uploadedRows.length;
        }"""
    )
    return int(count or 0)


async def _uploaded_doc_names(page: "Page") -> list[str]:
    names = await page.evaluate(
        """() => {
            const rows = Array.from(document.querySelectorAll("table tr, .document-row, .file-row, [class*='upload'] tr"));
            return rows
                .map((tr) => {
                    const tds = tr.querySelectorAll("td");
                    if (!tds || tds.length < 2) return "";
                    const docName = (tds[0]?.textContent || "").trim();
                    const size = (tds[1]?.textContent || "").trim();
                    if (!docName || !size) return "";
                    if (docName.toLowerCase() === "documento" && size.toLowerCase() === "tamaño") return "";
                    return docName;
                })
                .filter(Boolean);
        }"""
    )
    return [str(x) for x in (names or [])]


async def _upload_single_document(page: "Page", doc_path: str) -> None:
    browse = page.locator("#fakeBrowse").first
    if await browse.count() == 0:
        raise RuntimeError("No se encuentra el boton de subida '#fakeBrowse' en la pantalla de documentos.")
    await browse.wait_for(state="visible", timeout=30000)
    expected = Path(doc_path).name.strip().lower()
    logger.info("Diputacio BCN docs: iniciando seleccion de fichero path='%s' expected='%s'", doc_path, expected)

    file_inputs = page.locator("input[type='file']")
    input_count = await file_inputs.count()
    logger.info("Diputacio BCN docs: inputs[type=file] detectados=%s", input_count)
    for idx in range(max(0, input_count - 1), -1, -1):
        current_input = file_inputs.nth(idx)
        try:
            await current_input.set_input_files(doc_path)
            await current_input.evaluate(
                """(el) => {
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                }"""
            )
        except Exception:
            logger.warning("Diputacio BCN docs: set_input_files fallo input_idx=%s path='%s'", idx, doc_path, exc_info=True)
            continue
        try:
            selected_value = await current_input.evaluate(
                """(el) => {
                    const fileName = el.files && el.files.length ? (el.files[0]?.name || "") : "";
                    return fileName || el.value || "";
                }"""
            )
        except Exception:
            selected_value = ""
        selected_norm = str(selected_value or "").strip().lower()
        logger.info(
            "Diputacio BCN docs: set_input_files input_idx=%s selected_value='%s' normalized='%s'",
            idx,
            selected_value,
            selected_norm,
        )
        if expected and expected in selected_norm:
            logger.info("Diputacio BCN docs: fichero seleccionado via set_input_files input_idx=%s", idx)
            return

    # Fallback: file chooser del boton Navega.
    try:
        logger.info("Diputacio BCN docs: fallback a file chooser sobre #fakeBrowse")
        async with page.expect_file_chooser(timeout=15000) as fc_info:
            await browse.click(force=True)
        fc = await fc_info.value
        await fc.set_files(doc_path)
        selected_value = await page.evaluate(
            """() => {
                const input = document.querySelector("input[type='file']");
                return input ? (input.value || "") : "";
            }"""
        )
        selected_norm = str(selected_value or "").strip().lower()
        logger.info(
            "Diputacio BCN docs: file chooser selected_value='%s' normalized='%s'",
            selected_value,
            selected_norm,
        )
        if expected and expected not in selected_norm:
            raise RuntimeError(
                "El file chooser no dejó seleccionado el fichero esperado. "
                f"esperado='{expected}' input_value='{selected_value}'"
            )
        logger.info("Diputacio BCN docs: fichero seleccionado via file chooser expected='%s'", expected)
        return
    except Exception:
        raise RuntimeError(
            "No se pudo abrir file chooser en '#fakeBrowse'. "
            "Se aborta para evitar subir el fichero equivocado por fallback."
        )


def _basename(path_value: str) -> str:
    return Path(path_value).name.strip().lower()


async def _wait_row_increment_or_fail(page: "Page", expected_rows: int, expected_doc_path: str) -> None:
    logger.info(
        "Diputacio BCN docs: esperando incremento de filas expected_rows=%s doc='%s'",
        expected_rows,
        expected_doc_path,
    )
    try:
        await page.wait_for_function(
            """(minRows) => {
                const rows = Array.from(document.querySelectorAll("table tr, .document-row, .file-row, [class*='upload'] tr"));
                const uploadedRows = rows.filter((tr) => {
                    const tds = tr.querySelectorAll("td");
                    if (!tds || tds.length < 2) return false;
                    const docName = (tds[0]?.textContent || "").trim();
                    const size = (tds[1]?.textContent || "").trim();
                    if (!docName || !size) return false;
                    if (docName.toLowerCase() === "documento" && size.toLowerCase() === "tamaño") return false;
                    return true;
                });
                return uploadedRows.length >= minRows;
            }""",
            arg=expected_rows,
            timeout=25000,
        )
    except Exception as exc:
        names = await _uploaded_doc_names(page)
        raise RuntimeError(
            "No se registró la nueva fila de upload. "
            f"esperadas={expected_rows} actual={len(names)} "
            f"doc_esperado='{Path(expected_doc_path).name}' rows={names}"
        ) from exc

    # Validación semántica: el último nombre debería corresponder al archivo recién subido.
    names = await _uploaded_doc_names(page)
    if not names:
        raise RuntimeError("Upload sin filas visibles tras confirmación de incremento.")
    last_name = names[-1].strip().lower()
    expected_name = _basename(expected_doc_path)
    logger.info(
        "Diputacio BCN docs: filas detectadas tras upload rows=%s last='%s' expected='%s'",
        names,
        last_name,
        expected_name,
    )
    if expected_name not in last_name:
        raise RuntimeError(
            "El documento registrado no coincide con el esperado. "
            f"esperado='{expected_name}' ultimo='{last_name}' rows={names}"
        )


def _description_for_doc(doc_path: str) -> str:
    # La sede limita la longitud de descripcion.
    return Path(doc_path).name[:99]


async def _upload_documents_block(page: "Page", docs: list[str]) -> tuple[int, str]:
    if not docs:
        return 0, ""
    previous_rows = await _uploaded_rows_count(page)
    logger.info("Diputacio BCN docs: filas iniciales de adjuntos=%s docs=%s", previous_rows, docs)
    last_comment = ""
    for doc_path in docs:
        per_file_comment = _description_for_doc(doc_path)
        last_comment = await _set_comment_value(page, per_file_comment)
        logger.info(
            "Diputacio BCN docs: descripcion por archivo '%s' (len=%s)",
            per_file_comment,
            len(last_comment),
        )
        await page.wait_for_timeout(150)
        logger.info("Diputacio BCN docs: subiendo '%s'", doc_path)
        await _upload_single_document(page, doc_path)
        await page.wait_for_function(
            "() => !window.jQuery || window.jQuery.active === 0",
            timeout=20000,
        )
        await page.wait_for_timeout(500)
        expected_rows = previous_rows + 1
        await _wait_row_increment_or_fail(page, expected_rows, doc_path)
        previous_rows = expected_rows
        logger.info("Diputacio BCN docs: upload confirmado doc='%s' total_rows=%s", doc_path, previous_rows)
    return previous_rows, last_comment


async def run_documentos(page: "Page", config: "DiputacioBcnConfig", datos: "DiputacioBcnTarget") -> "Page":
    _ = config
    page = _pick_latest_open_page(page)
    page = await _resolve_documents_page(page, timeout_ms=45000)
    logger.info("Diputacio BCN docs: entrando en run_documentos idRecurso=%s url=%s", datos.idRecurso, page.url)

    doc_acr = _existing_file(datos.doc_acreditativa)
    doc_tra = _existing_file(datos.doc_tramite)
    missing_required: list[str] = []
    if not doc_acr:
        missing_required.append(f"doc_acreditativa='{datos.doc_acreditativa}'")
    if not doc_tra:
        missing_required.append(f"doc_tramite='{datos.doc_tramite}'")
    if missing_required:
        raise RuntimeError(
            "Faltan documentos obligatorios en disco antes de subir. "
            + ", ".join(missing_required)
        )
    doc_acr_norm = str(Path(doc_acr).resolve()).lower()
    doc_tra_norm = str(Path(doc_tra).resolve()).lower()
    if doc_acr_norm == doc_tra_norm:
        logger.warning(
            "Diputacio BCN docs: doc_acreditativa y doc_tramite apuntan al mismo fichero; "
            "se reutilizara un unico upload. ruta='%s'",
            doc_acr,
        )
    logger.info(
        "Diputacio BCN docs: obligatorios resueltos doc_acreditativa='%s' doc_tramite='%s'",
        doc_acr,
        doc_tra,
    )

    all_docs = _collect_upload_paths(datos)
    if not all_docs:
        raise RuntimeError(
            "Faltan documentos para la pantalla de documentos. "
            "Define payload.doc_tramite/doc_acreditativa y/o payload.archivos."
        )
    all_docs_norm = {str(Path(p).resolve()).lower() for p in all_docs}
    missing_in_batch: list[str] = []
    if doc_acr_norm not in all_docs_norm:
        missing_in_batch.append(f"doc_acreditativa='{doc_acr}'")
    if doc_tra_norm not in all_docs_norm:
        missing_in_batch.append(f"doc_tramite='{doc_tra}'")
    if missing_in_batch:
        raise RuntimeError(
            "Lote de subida inconsistente: faltan documentos obligatorios en all_docs. "
            + ", ".join(missing_in_batch)
        )

    for doc_path in all_docs:
        suffix = Path(doc_path).suffix.lower()
        if suffix not in ALLOWED_DOC_EXTENSIONS:
            raise RuntimeError(
                f"Extension de documento no permitida para Diputacio BCN: '{suffix or '(sin extension)'}' en '{doc_path}'."
            )

    upload_docs = list(all_docs)
    logger.info("Diputacio BCN docs: total=%s (misma pantalla)", len(upload_docs))
    try:
        debug_path = Path("tmp") / f"diputacio_bcn_runtime_docs_{datos.idRecurso or 'unknown'}.json"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(
            json.dumps(
                {
                    "idRecurso": datos.idRecurso,
                    "url": page.url,
                    "doc_acreditativa": doc_acr,
                    "doc_tramite": doc_tra,
                    "required_docs_share_same_file": doc_acr_norm == doc_tra_norm,
                    "all_docs": all_docs,
                    "upload_docs": upload_docs,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    await _upload_documents_block(page, upload_docs)

    # En esta sede el campo ComentFile puede vaciarse tras adjuntar.
    # La estructura de tabla puede variar por idioma/plantilla, así que esta validación es solo diagnóstica.
    expected_desc_by_doc = {Path(doc).name.strip().lower(): _description_for_doc(doc).strip().lower() for doc in upload_docs}
    uploaded_table_rows = await page.evaluate(
        """() => {
            const rows = Array.from(document.querySelectorAll("table tr, .document-row, .file-row, [class*='upload'] tr"));
            return rows
                .map((tr) => {
                    const tds = tr.querySelectorAll("td");
                    if (!tds || tds.length < 2) return null;
                    const doc = (tds[0]?.textContent || "").trim();
                    const size = (tds[1]?.textContent || "").trim();
                    const desc = (tds.length >= 3 ? (tds[tds.length - 2]?.textContent || "") : "").trim();
                    if (!doc || !size) return null;
                    if (doc.toLowerCase() === "documento" && size.toLowerCase() === "tamaño") return null;
                    return { doc, size, desc };
                })
                .filter(Boolean);
        }"""
    )
    normalized_uploaded = [
        {
            "doc": str(item.get("doc") or "").strip().lower(),
            "desc": str(item.get("desc") or "").strip().lower(),
        }
        for item in (uploaded_table_rows or [])
    ]
    missing_desc_matches: list[str] = []
    for expected_doc, expected_desc in expected_desc_by_doc.items():
        found = False
        for row in normalized_uploaded:
            if expected_doc == row["doc"] and expected_desc == row["desc"]:
                found = True
                break
        if not found:
            missing_desc_matches.append(f"{expected_doc}=>{expected_desc}")
    if missing_desc_matches:
        logger.warning(
            "Descripcion por archivo no reflejada en tabla (no bloqueante). faltan=%s rows=%s",
            missing_desc_matches,
            normalized_uploaded,
        )
    else:
        logger.info("Diputacio BCN docs: la tabla refleja todas las descripciones esperadas")

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
                    if (!docName || !size) return false;
                    if (docName.toLowerCase() === "documento" && size.toLowerCase() === "tamaño") return false;
                    return true;
                });
                const errors = Array.from(document.querySelectorAll(".error, .text-danger, .field-validation-error, .validation-summary-errors"))
                    .map((el) => (el.textContent || "").trim())
                    .filter(Boolean);
                return { uploadedRows: uploadedRows.length, errors };
            }"""
        )
        if int(upload_state.get("uploadedRows") or 0) >= len(upload_docs):
            break
        await page.wait_for_timeout(1000)

    uploaded_rows = int(upload_state.get("uploadedRows") or 0)
    logger.info(
        "Diputacio BCN docs: estado final adjuntos uploaded_rows=%s expected=%s errors=%s",
        uploaded_rows,
        len(upload_docs),
        upload_state.get("errors"),
    )
    if uploaded_rows < len(upload_docs):
        raise RuntimeError(
            f"No se han subido todos los documentos esperados ({uploaded_rows}/{len(upload_docs)}). "
            f"errores={upload_state.get('errors')}"
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
    logger.info("Diputacio BCN docs: click en Continuar tras adjuntos")
    await submit.click()

    # Paso /Home/dadesnotif
    await page.wait_for_url("**/Home/dadesnotif**", timeout=25000)
    representative_radios = [
        page.locator("input[name='Secc1Radio'][value='R'], input[name='Secc1Radio'][data-radio='R1']").first,
        page.locator("#uncheckNEPO2, input[name='NotifElecPuntualOP2'][value='R']").first,
    ]
    for radio in representative_radios:
        if await radio.count() > 0:
            try:
                if await radio.is_visible():
                    await radio.check(force=True)
            except Exception:
                pass

    phone_selectors = [
        "#InfoMobil1",
        "input[name='InfoMobil1']",
        "#InfoMobil2",
        "input[name='InfoMobil2']",
    ]
    email_selectors = [
        "#InfoMail1",
        "input[name='InfoMail1']",
        "#InfoMail2",
        "input[name='InfoMail2']",
    ]

    phone_filled = False
    for selector in phone_selectors:
        field = page.locator(selector).first
        if await field.count() == 0:
            continue
        try:
            if await field.is_visible():
                await field.fill(datos.telefon or "600000000")
                phone_filled = True
        except Exception:
            continue

    email_filled = False
    for selector in email_selectors:
        field = page.locator(selector).first
        if await field.count() == 0:
            continue
        try:
            if await field.is_visible():
                await field.fill(datos.email or "notificacions@example.com")
                email_filled = True
        except Exception:
            continue

    if not phone_filled or not email_filled:
        raise RuntimeError(
            f"No se pudieron rellenar los campos visibles de datos de notificacion. phone_filled={phone_filled} email_filled={email_filled}"
        )

    await page.locator("input.btn.btn-info[name='accio'][value='Continuar']").first.click()
    await page.wait_for_url("**/Home/correuElectronic**", timeout=25000)

    lopd = page.locator("#LOPD").first
    await lopd.wait_for(state="visible", timeout=15000)
    await lopd.check(force=True)

    await page.locator("input.btn.btn-info[name='accio'][value='Acceder al trámite']").first.click()
    return _pick_latest_open_page(page)
