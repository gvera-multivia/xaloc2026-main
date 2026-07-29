from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
import unicodedata
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ._page_eval import evaluate_with_nav_retry

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget

logger = logging.getLogger("xaloc_automation.terrassa")


def _norm_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("?", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


async def _visible_upload_indices(page: "Page") -> list[int]:
    indices = await evaluate_with_nav_retry(
        page,
        """() => {
            const out = [];
            const nodes = Array.from(document.querySelectorAll("input[id^='fileUpload']"));
            for (const el of nodes) {
                const m = (el.id || "").match(/^fileUpload(\\d+)$/);
                if (!m) continue;
                const idx = Number(m[1]);
                if (!Number.isFinite(idx)) continue;
                const form = document.getElementById(`fitxers${idx}`);
                const block = document.getElementById(`uploadFitxer${idx}`);
                if (!form || !block) continue;
                const blockStyle = window.getComputedStyle(block);
                const formStyle = window.getComputedStyle(form);
                if (!blockStyle || !formStyle) continue;
                if (blockStyle.display === "none" || blockStyle.visibility === "hidden") continue;
                if (formStyle.display === "none" || formStyle.visibility === "hidden") continue;
                out.push(idx);
            }
            out.sort((a, b) => a - b);
            return Array.from(new Set(out));
        }"""
    )
    return [int(x) for x in (indices or [])]


async def _try_click_add_upload_block(page: "Page") -> bool:
    """
    Intenta forzar la aparición de un nuevo bloque de upload pulsando el botón
    de adjuntar/añadir documento. Terrassa a veces muestra un popup aleatorio
    que no hace nada; si aparece un dialog JS, se acepta automáticamente.
    """
    try:
        dialog_task_ref: dict[str, asyncio.Task | None] = {"task": None}

        def _on_dialog(dialog):
            async def _accept_dialog():
                try:
                    await dialog.accept()
                except Exception:
                    pass

            dialog_task_ref["task"] = asyncio.create_task(_accept_dialog())

        page.once("dialog", _on_dialog)
    except Exception:
        dialog_task_ref = {"task": None}

    try:
        clicked = await evaluate_with_nav_retry(
            page,
            """() => {
                const norm = (v) => String(v || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, " ")
                    .trim();
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return !!s && s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
                };
                const isEnabled = (el) => !el.disabled && el.getAttribute("aria-disabled") !== "true";

                const preferredSelectors = [
                    "button[onclick*='Fitxer']",
                    "button[onclick*='fitxer']",
                    "button[onclick*='upload']",
                    "a[onclick*='Fitxer']",
                    "a[onclick*='fitxer']",
                    "a[onclick*='upload']",
                    ".se-button",
                    "button",
                    "a[role='button']",
                    "a",
                ];
                const preferredTokens = [
                    "adjuntar",
                    "afegir",
                    "anadir",
                    "añadir",
                    "add",
                    "nou document",
                    "nuevo documento",
                    "document adjunt",
                ];

                for (const sel of preferredSelectors) {
                    const nodes = Array.from(document.querySelectorAll(sel));
                    for (const el of nodes) {
                        if (!isVisible(el) || !isEnabled(el)) continue;
                        const txt = norm(el.textContent || el.getAttribute("aria-label") || el.getAttribute("title") || "");
                        const onclick = norm(el.getAttribute("onclick") || "");
                        const looksLikeAdd =
                            preferredTokens.some((t) => txt.includes(norm(t))) ||
                            onclick.includes("fitxer") ||
                            onclick.includes("upload");
                        if (!looksLikeAdd) continue;
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
        )
        return bool(clicked)
    except Exception:
        return False
    finally:
        try:
            task = dialog_task_ref.get("task")
            if task is not None:
                await asyncio.wait_for(task, timeout=0.3)
        except Exception:
            pass


async def _resolve_upload_index(
    page: "Page",
    *,
    preferred_index: int,
    used_indices: set[int],
    timeout_ms: int,
) -> int:
    waited = 0
    step_ms = 500
    last_visible: list[int] = []
    nudge_interval_ms = 1000
    next_nudge_at = 0
    while waited <= timeout_ms:
        visible = await _visible_upload_indices(page)
        last_visible = visible
        free = [idx for idx in visible if idx not in used_indices]
        if preferred_index in free:
            return preferred_index
        if free:
            return min(free)
        if waited >= next_nudge_at:
            nudged = await _try_click_add_upload_block(page)
            if nudged:
                logger.info(
                    "[terrassa-docs] sin bloque libre (waited=%sms); pulsado boton adjuntar para abrir nuevo bloque. "
                    "visible=%s used=%s",
                    waited,
                    visible,
                    sorted(used_indices),
                )
            next_nudge_at = waited + nudge_interval_ms
        await page.wait_for_timeout(step_ms)
        waited += step_ms

    # Modo resistente: si hay bloques visibles pero todos estan marcados como usados,
    # comprobamos primero si algun bloque esta vaciado en DOM (el servidor lo reseteo
    # pero used_indices no lo sabe). Solo reutilizamos bloques verdaderamente vacios.
    if last_visible:
        free_last_visible = [idx for idx in last_visible if idx not in used_indices]
        if preferred_index in free_last_visible:
            return preferred_index
        if free_last_visible:
            return min(free_last_visible)
        # Todos visibles estan en used_indices: verificar vaciado real en DOM
        candidates = ([preferred_index] if preferred_index in last_visible else []) + sorted(last_visible)
        for candidate in candidates:
            if await _is_block_truly_empty(page, upload_index=candidate):
                used_indices.discard(candidate)
                logger.warning(
                    "[terrassa-docs] fallback: bloque %s en used_indices pero vacio en DOM, "
                    "liberando para reuso. visible=%s used=%s",
                    candidate,
                    last_visible,
                    sorted(used_indices),
                )
                return candidate
        # Ningun bloque visible esta realmente vacio: no reutilizar, dejar que falle
        logger.error(
            "[terrassa-docs] sin bloques libres y ningun bloque vacio en DOM. "
            "visible=%s used=%s",
            last_visible,
            sorted(used_indices),
        )

    # Último intento anti-aleatorio: re-pulsar adjuntar y re-evaluar visibles.
    nudged_last = await _try_click_add_upload_block(page)
    if nudged_last:
        await page.wait_for_timeout(500)
        final_visible = await _visible_upload_indices(page)
        if final_visible:
            if preferred_index in final_visible:
                return preferred_index
            return min(final_visible)

    raise RuntimeError(
        f"terrassa-docs: no hay bloques de subida libres para doc index={preferred_index}. "
        f"bloques_visibles={last_visible} bloques_ya_usados={sorted(used_indices)}"
    )


async def _is_block_truly_empty(page: "Page", *, upload_index: int) -> bool:
    """Devuelve True si el bloque no tiene un fichero activamente cargado en el input.
    Solo comprueba fileCount == 0: los campos de texto (descripcion, fitxerPle) pueden
    tener valores iniciales o residuales sin que haya riesgo real de sobrescritura."""
    result = await evaluate_with_nav_retry(
        page,
        """({ uploadIndex }) => {
            const fileInput = document.getElementById(`fileUpload${uploadIndex}`);
            if (!fileInput) return true;
            return (fileInput.files?.length ?? 0) === 0;
        }""",
        {"uploadIndex": upload_index},
    )
    return bool(result)


async def _snapshot_upload_state(page: "Page", *, upload_index: int, file_name: str) -> dict[str, object]:
    state = await evaluate_with_nav_retry(
        page,
        """({ uploadIndex, fileName }) => {
            const norm = (txt) => String(txt || "").replace(/\\s+/g, " ").trim().toLowerCase();
            const filename = norm(fileName);
            const block = document.getElementById(`uploadFitxer${uploadIndex}`);
            const form = document.getElementById(`fitxers${uploadIndex}`);
            const fileInput = document.getElementById(`fileUpload${uploadIndex}`);
            const iframe = document.querySelector(`iframe[name='iframeUpload${uploadIndex}']`) || null;
            const descInput = form?.querySelector("input[type='text']") || null;
            const typeSelect = form?.querySelector("select") || null;
            const fullFileInput = form?.querySelector("input[name='fitxerPle']") || null;
            const descTypeInput = form?.querySelector("input[name='descr_tipologia_documental']") || null;

            const visibleIndices = Array.from(document.querySelectorAll("input[id^='fileUpload']"))
                .map((el) => {
                    const match = (el.id || "").match(/^fileUpload(\\d+)$/);
                    return match ? Number(match[1]) : NaN;
                })
                .filter((idx) => Number.isFinite(idx))
                .filter((idx) => {
                    const formNode = document.getElementById(`fitxers${idx}`);
                    const blockNode = document.getElementById(`uploadFitxer${idx}`);
                    if (!formNode || !blockNode) return false;
                    const blockStyle = window.getComputedStyle(blockNode);
                    const formStyle = window.getComputedStyle(formNode);
                    return !!blockStyle
                        && !!formStyle
                        && blockStyle.display !== "none"
                        && blockStyle.visibility !== "hidden"
                        && formStyle.display !== "none"
                        && formStyle.visibility !== "hidden";
                })
                .sort((a, b) => a - b);

            let outsideMentions = 0;
            if (filename) {
                const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const node = walker.currentNode;
                    const parent = node?.parentElement;
                    if (!parent) continue;
                    if (block && block.contains(parent)) continue;
                    const text = norm(node.textContent || "");
                    if (text.includes(filename)) outsideMentions += 1;
                }
            }

            return {
                visible_indices: visibleIndices,
                outside_mentions: outsideMentions,
                block_present: !!block,
                form_present: !!form,
                file_present: !!fileInput,
                file_count: fileInput?.files?.length ?? -1,
                iframe_src: iframe?.getAttribute('src') || "",
                desc_value: descInput?.value || "",
                selected_type: typeSelect?.selectedOptions?.[0]?.textContent || typeSelect?.value || "",
                full_file_value: fullFileInput?.value || "",
                desc_type_value: descTypeInput?.value || "",
            };
        }""",
        {"uploadIndex": upload_index, "fileName": file_name},
    )
    if not isinstance(state, dict):
        return {
            "visible_indices": [],
            "outside_mentions": 0,
            "block_present": False,
            "form_present": False,
            "file_present": False,
            "file_count": -1,
            "iframe_src": "",
            "desc_value": "",
            "selected_type": "",
            "full_file_value": "",
            "desc_type_value": "",
        }
    return state


def _submission_has_started(*, before_state: dict[str, object], current_state: dict[str, object]) -> bool:
    before_iframe_src = str(before_state.get("iframe_src") or "").strip()
    current_iframe_src = str(current_state.get("iframe_src") or "").strip()
    if current_iframe_src and current_iframe_src != before_iframe_src:
        return True

    before_outside = int(before_state.get("outside_mentions") or 0)
    current_outside = int(current_state.get("outside_mentions") or 0)
    if current_outside > before_outside:
        return True

    before_file_count = int(before_state.get("file_count") or 0)
    current_file_count = int(current_state.get("file_count") or 0)
    if before_file_count > 0 and current_file_count == 0:
        return True

    before_visible = [int(idx) for idx in (before_state.get("visible_indices") or [])]
    current_visible = [int(idx) for idx in (current_state.get("visible_indices") or [])]
    if current_visible != before_visible:
        return True

    if not bool(current_state.get("block_present")) or not bool(current_state.get("form_present")) or not bool(current_state.get("file_present")):
        return True

    return False


async def _prime_upload_form_fields(page: "Page", *, upload_index: int) -> None:
    await evaluate_with_nav_retry(
        page,
        """({ uploadIndex }) => {
            const form = document.getElementById(`fitxers${uploadIndex}`);
            if (!form) return;
            const typeSelect = form.querySelector("select");
            const fullFileInput = form.querySelector("input[name='fitxerPle']");
            const descTypeInput = form.querySelector("input[name='descr_tipologia_documental']");
            const typeLabel = String(typeSelect?.selectedOptions?.[0]?.textContent || "").trim();

            if (fullFileInput) {
                fullFileInput.value = "ple";
            }
            if (descTypeInput) {
                descTypeInput.value = typeLabel;
            }
        }""",
        {"uploadIndex": upload_index},
    )


def _analyze_upload_state(
    *,
    before_state: dict[str, object],
    current_state: dict[str, object],
    upload_index: int,
    used_indices: set[int],
    expected_desc: str,
    expected_type: str,
) -> dict[str, object]:
    outside_before = int(before_state.get("outside_mentions") or 0)
    outside_now = int(current_state.get("outside_mentions") or 0)
    visible_now = [int(idx) for idx in (current_state.get("visible_indices") or [])]

    has_name_outside_block = outside_now > outside_before
    has_fresh_block = any(idx not in used_indices and idx != upload_index for idx in visible_now)
    block_missing = not bool(current_state.get("block_present"))
    form_missing = not bool(current_state.get("form_present"))
    file_missing = not bool(current_state.get("file_present"))

    desc_now = _norm_text(current_state.get("desc_value"))
    type_now = _norm_text(current_state.get("selected_type"))
    desc_expected = _norm_text(expected_desc)
    type_expected = _norm_text(expected_type)
    file_count = int(current_state.get("file_count") or 0)
    desc_matches = (not desc_expected) or (desc_now == desc_expected or desc_expected in desc_now or desc_now in desc_expected)
    type_strict_matches = (
        (not type_expected)
        or (type_now == type_expected)
        or (len(type_now) >= 8 and type_expected.startswith(type_now))
        or (len(type_expected) >= 8 and type_now.startswith(type_expected))
    )

    block_recycled = (
        not block_missing
        and not form_missing
        and not file_missing
        and file_count == 0
        and desc_now != desc_expected
        and type_now != type_expected
    )
    same_block_soft_candidate = (
        has_name_outside_block
        and not has_fresh_block
        and not block_missing
        and not form_missing
        and not file_missing
        and file_count > 0
        # Si el nombre exacto del fichero ya aparece fuera del bloque activo,
        # Terrassa lo ha registrado aunque mantenga el input cargado. La
        # descripcion/tipologia pueden normalizarse o truncarse en la UI.
        and (desc_matches or has_name_outside_block)
        and type_strict_matches
    )
    # Regla estricta anti-sobrescritura:
    # no confirmamos si el input de fichero sigue cargado en el mismo bloque.
    # Si "confirmamos" con file_count>=1, el siguiente documento puede pisar el anterior.
    same_block_registered = False
    structural_progress = has_fresh_block or block_missing or form_missing or file_missing or block_recycled
    confirmed = has_name_outside_block and structural_progress

    return {
        "confirmed": confirmed,
        "recycled_current_block": block_recycled,
        "same_block_registered": same_block_registered,
        "same_block_soft_candidate": same_block_soft_candidate,
        "has_name_outside_block": has_name_outside_block,
        "has_fresh_block": has_fresh_block,
        "visible_indices": visible_now,
        "outside_mentions": outside_now,
        "file_count": file_count,
        "desc_value": str(current_state.get("desc_value") or ""),
        "selected_type": str(current_state.get("selected_type") or ""),
    }


async def _wait_until_upload_committed(
    page: "Page",
    *,
    before_state: dict[str, object],
    upload_index: int,
    file_name: str,
    used_indices: set[int],
    expected_desc: str,
    expected_type: str,
    timeout_ms: int,
) -> dict[str, object]:
    waited = 0
    step_ms = 500
    soft_candidate_hits = 0
    soft_confirm_after_hits = 6
    last_analysis: dict[str, object] = {}

    while waited <= timeout_ms:
        current_state = await _snapshot_upload_state(page, upload_index=upload_index, file_name=file_name)
        last_analysis = _analyze_upload_state(
            before_state=before_state,
            current_state=current_state,
            upload_index=upload_index,
            used_indices=used_indices,
            expected_desc=expected_desc,
            expected_type=expected_type,
        )
        if bool(last_analysis.get("confirmed")):
            return last_analysis
        # Confirmacion blanda controlada:
        # Terrassa, a veces, deja el mismo bloque visible con file_count>0
        # aunque el upload haya quedado registrado. Exigimos varios ciclos
        # consecutivos en ese estado para minimizar falsos positivos.
        if bool(last_analysis.get("same_block_soft_candidate")):
            soft_candidate_hits += 1
            if soft_candidate_hits >= soft_confirm_after_hits:
                return {
                    **last_analysis,
                    "confirmed": True,
                    "same_block_registered": True,
                    "soft_confirmed": True,
                    "soft_hits": soft_candidate_hits,
                }
        else:
            soft_candidate_hits = 0
        await page.wait_for_timeout(step_ms)
        waited += step_ms

    raise RuntimeError(
        "terrassa-docs: no se pudo confirmar la subida del fichero "
        f"{file_name} en el bloque {upload_index}. estado={last_analysis}"
    )


async def _dispatch_legacy_upload_submit(page: "Page", *, upload_index: int) -> bool:
    try:
        return bool(
            await evaluate_with_nav_retry(
                page,
                """({ uploadIndex }) => {
                    const form = document.getElementById(`fitxers${uploadIndex}`);
                    const fileInput = document.getElementById(`fileUpload${uploadIndex}`);
                    if (!form || !fileInput || !fileInput.files || !fileInput.files.length) return false;

                    const descInput = form.querySelector("input[type='text']");
                    const typeSelect = form.querySelector("select");
                    const fullFileInput = form.querySelector("input[name='fitxerPle']");
                    const descTypeInput = form.querySelector("input[name='descr_tipologia_documental']");
                    const descValue = String(descInput?.value || "").trim();
                    const typeValue = String(typeSelect?.value || "").trim();
                    const typeLabel = String(typeSelect?.selectedOptions?.[0]?.textContent || "").trim();
                    if (!descValue || !typeValue || typeValue === "-") return false;

                    if (fullFileInput) {
                        fullFileInput.value = "ple";
                    }
                    if (descTypeInput) {
                        descTypeInput.value = typeLabel;
                    }

                    if (typeof window.ferSubmitFitxer === "function") {
                        window.ferSubmitFitxer(uploadIndex, descValue, fullFileInput, typeValue);
                        return true;
                    }
                    return false;
                }""",
                {"uploadIndex": upload_index},
            )
        )
    except Exception:
        return False


async def _dispatch_direct_form_submit(page: "Page", *, upload_index: int) -> bool:
    try:
        return bool(
            await evaluate_with_nav_retry(
                page,
                """({ uploadIndex }) => {
                    const form = document.getElementById(`fitxers${uploadIndex}`);
                    const fileInput = document.getElementById(`fileUpload${uploadIndex}`);
                    if (!form || !fileInput || !fileInput.files || !fileInput.files.length) return false;

                    const descInput = form.querySelector("input[type='text']");
                    const typeSelect = form.querySelector("select");
                    const fullFileInput = form.querySelector("input[name='fitxerPle']");
                    const descTypeInput = form.querySelector("input[name='descr_tipologia_documental']");
                    const descValue = String(descInput?.value || "").trim();
                    const typeValue = String(typeSelect?.value || "").trim();
                    const typeLabel = String(typeSelect?.selectedOptions?.[0]?.textContent || "").trim();
                    if (!descValue || !typeValue || typeValue === "-") return false;

                    if (fullFileInput) {
                        fullFileInput.value = "ple";
                    }
                    if (descTypeInput) {
                        descTypeInput.value = typeLabel;
                    }

                    try {
                        HTMLFormElement.prototype.submit.call(form);
                        return true;
                    } catch (_err) {
                        return false;
                    }
                }""",
                {"uploadIndex": upload_index},
            )
        )
    except Exception:
        return False


async def _queue_upload_submission(
    page: "Page",
    *,
    file_input,
    upload_index: int,
    file_path: Path,
    before_state: dict[str, object],
) -> str:
    try:
        async with page.expect_file_chooser(timeout=1500) as chooser_info:
            await file_input.click(force=True)
        chooser = await chooser_info.value
        await chooser.set_files(str(file_path))
        method = "chooser"
    except PlaywrightTimeoutError:
        await file_input.set_input_files(str(file_path))
        method = "set_input_files"

    try:
        await file_input.evaluate(
            """(el) => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }"""
        )
    except Exception:
        pass

    await _prime_upload_form_fields(page, upload_index=upload_index)
    await page.wait_for_timeout(1200)
    submitted = await _dispatch_legacy_upload_submit(page, upload_index=upload_index)
    if submitted:
        await page.wait_for_timeout(1800)
        post_legacy_state = await _snapshot_upload_state(page, upload_index=upload_index, file_name=file_path.name)
        if _submission_has_started(before_state=before_state, current_state=post_legacy_state):
            return f"{method}+legacy_submit"

    direct_submitted = await _dispatch_direct_form_submit(page, upload_index=upload_index)
    if direct_submitted:
        await page.wait_for_timeout(1800)
        return f"{method}+direct_submit"
    return method


async def _try_release_soft_confirmed_block(
    page: "Page",
    *,
    upload_index: int,
    file_name: str,
) -> bool:
    file_sel = f"input#fileUpload{upload_index}"
    try:
        file_input = page.locator(file_sel).first
        await file_input.set_input_files([])
        await file_input.evaluate(
            """(el) => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }"""
        )
        await page.wait_for_timeout(500)
        released_state = await _snapshot_upload_state(page, upload_index=upload_index, file_name=file_name)
        released = int(released_state.get("file_count") or 0) == 0
        if released:
            logger.warning(
                "[terrassa-docs] soft-confirm: bloque %s liberado limpiando el file input. file=%s",
                upload_index,
                file_name,
            )
        else:
            logger.warning(
                "[terrassa-docs] soft-confirm: no se pudo liberar el bloque %s tras limpiar el file input. "
                "estado=%s",
                upload_index,
                released_state,
            )
        return released
    except Exception as exc:
        logger.warning(
            "[terrassa-docs] soft-confirm: error liberando bloque %s para file=%s: %s",
            upload_index,
            file_name,
            exc,
        )
        return False


async def run_documentos(page: "Page", config: "TerrassaConfig", datos: "TerrassaTarget") -> "Page":
    docs = list(datos.documentos or [])
    if not docs:
        docs = [
            {"fitxer": str(p), "descripcio": p.stem[:70] or "Documento", "tipus": "Al-legacio"}
            for p in (datos.archivos_para_subir or [])
        ]

    if not docs:
        base_path = str(datos.payload.get("docs_base_path") or r"\\SERVER-DOC\clientes")
        sujeto = str(datos.payload.get("nombre") or "").strip()
        raise ValueError(
            f"terrassa: faltan documentos para subida. Revisar carpeta cliente en {base_path} (sujeto: {sujeto})."
        )

    total_docs = len(docs)
    used_upload_indices: set[int] = set()

    for index, doc in enumerate(docs):
        file_path = Path(str(doc.get("fitxer") or "")).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(str(file_path))

        descripcio = str(doc.get("descripcio") or "Documento").strip()[:16]
        tipus = str(doc.get("tipus") or "Al-legacio").strip()

        block_timeout = min(int(config.timeouts.subida_archivo), 12000)
        upload_index = await _resolve_upload_index(
            page,
            preferred_index=index,
            used_indices=used_upload_indices,
            timeout_ms=block_timeout,
        )

        block_sel = f"#uploadFitxer{upload_index}"
        form_sel = f"form#fitxers{upload_index}"
        file_sel = f"input#fileUpload{upload_index}"

        logger.info(
            "[terrassa-docs] doc %s/%s -> upload_index=%s file=%s block_sel=%s form_sel=%s file_sel=%s",
            index + 1,
            total_docs,
            upload_index,
            str(file_path),
            block_sel,
            form_sel,
            file_sel,
        )

        await page.wait_for_selector(f"{block_sel} {form_sel} {file_sel}", timeout=min(block_timeout, 8000))
        await page.locator(block_sel).scroll_into_view_if_needed()
        await page.wait_for_timeout(400)
        form = page.locator(form_sel).first
        # Evitar dependencia de labels o idioma: usar estructura del bloque por id.
        desc_input = form.locator("input[type='text']").first
        tipo_select = form.locator("select").first
        file_input = form.locator(file_sel).first

        await desc_input.fill(descripcio)
        try:
            await desc_input.evaluate(
                """(el) => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    if (typeof el.blur === 'function') el.blur();
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }"""
            )
        except Exception:
            pass
        await page.wait_for_timeout(350)
        try:
            await tipo_select.select_option(label=tipus, timeout=5000)
            logger.info("[terrassa-docs] tipo seleccionado por label exacta: %s", tipus)
        except PlaywrightTimeoutError:
            # Fallback robusto por acentos/codificacion: buscar por texto normalizado.
            option_value = await tipo_select.evaluate(
                """(sel, targetLabel) => {
                    const norm = (txt) => (txt || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .trim()
                        .toLowerCase();
                    const wanted = norm(targetLabel);
                    const options = Array.from(sel.options || []);
                    let found = options.find((o) => norm(o.textContent || "") === wanted);
                    if (!found) {
                        found = options.find((o) => norm(o.textContent || "").includes(wanted));
                    }
                    if (!found) {
                        found = options.find((o) => (o.value || "").trim() && (o.value || "") !== "-");
                    }
                    return found ? found.value : null;
                }""",
                tipus,
            )
            if option_value:
                await tipo_select.select_option(value=str(option_value), timeout=5000)
                logger.info(
                    "[terrassa-docs] tipo seleccionado por fallback normalizado. label=%s value=%s",
                    tipus,
                    option_value,
                )
            else:
                logger.warning("[terrassa-docs] no se encontro opcion de tipo para label=%s", tipus)
        try:
            await tipo_select.evaluate(
                """(el) => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    if (typeof el.blur === 'function') el.blur();
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }"""
            )
        except Exception:
            pass
        await page.wait_for_timeout(500)

        # Guard anti-sobrescritura: verificar que el bloque esta vacio antes de cargar el fichero.
        # Si no esta vacio, intentamos pulsar el boton de continuar/adjuntar para que la pagina
        # avance el estado del bloque. Hasta 3 reintentos antes de cancelar.
        block_empty = await _is_block_truly_empty(page, upload_index=upload_index)
        if not block_empty:
            _overwrite_guard_retries = 3
            for _retry in range(_overwrite_guard_retries):
                logger.warning(
                    "[terrassa-docs] bloque %s no vacio antes de subir %s "
                    "(reintento %s/%s), pulsando boton continuar para avanzar estado...",
                    upload_index,
                    file_path.name,
                    _retry + 1,
                    _overwrite_guard_retries,
                )
                await _try_click_add_upload_block(page)
                await page.wait_for_timeout(2000)
                block_empty = await _is_block_truly_empty(page, upload_index=upload_index)
                if block_empty:
                    logger.info(
                        "[terrassa-docs] bloque %s vaciado tras reintento %s, continuando.",
                        upload_index,
                        _retry + 1,
                    )
                    break
            if not block_empty:
                raise RuntimeError(
                    f"terrassa-docs: bloque {upload_index} no esta vacio antes de subir "
                    f"{file_path.name} tras {_overwrite_guard_retries} reintentos. "
                    f"Riesgo de sobrescritura detectado."
                )

        before_upload_state = await _snapshot_upload_state(
            page,
            upload_index=upload_index,
            file_name=file_path.name,
        )
        upload_method = await _queue_upload_submission(
            page,
            file_input=file_input,
            upload_index=upload_index,
            file_path=file_path,
            before_state=before_upload_state,
        )
        logger.info(
            "[terrassa-docs] submit de upload lanzado index=%s file=%s method=%s",
            upload_index,
            file_path.name,
            upload_method,
        )

        confirmation = await _wait_until_upload_committed(
            page,
            before_state=before_upload_state,
            upload_index=upload_index,
            file_name=file_path.name,
            used_indices=used_upload_indices,
            expected_desc=descripcio,
            expected_type=tipus,
            timeout_ms=min(int(config.timeouts.subida_archivo), 30000),
        )
        if bool(confirmation.get("recycled_current_block")):
            used_upload_indices.discard(upload_index)
            logger.info(
                "[terrassa-docs] upload confirmado y bloque reciclado para reuse index=%s file=%s",
                upload_index,
                file_path.name,
            )
        else:
            # same_block_registered (soft-confirm): el fichero sigue cargado en el input.
            if bool(confirmation.get("same_block_registered")):
                released = await _try_release_soft_confirmed_block(
                    page,
                    upload_index=upload_index,
                    file_name=file_path.name,
                )
                if released:
                    used_upload_indices.discard(upload_index)
                else:
                    used_upload_indices.add(upload_index)
                    logger.warning(
                        "[terrassa-docs] soft-confirm: bloque %s mantiene fichero cargado, "
                        "marcado como usado para evitar sobrescritura. file=%s",
                        upload_index,
                        file_path.name,
                    )
            else:
                used_upload_indices.add(upload_index)
                logger.info(
                    "[terrassa-docs] upload confirmado en bloque index=%s file=%s visible_indices=%s",
                    upload_index,
                    file_path.name,
                    confirmation.get("visible_indices"),
                )

        if index < (total_docs - 1):
            await page.wait_for_timeout(2000)

    return page
