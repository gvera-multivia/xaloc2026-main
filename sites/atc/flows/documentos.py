from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from core.pdf_bundle import bundle_documents_to_single_pdf_for_palma, bundle_documents_with_size_limit

from ._dom import robust_click, select_option_by_label, set_bound_value, wait_after_action, wait_locator_ready

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AtcConfig
    from ..data_models import AtcTarget

DESC_MAX_LEN = 15
REGISTRO_UPLOAD_GAP_MS = 1000
ATC_DOC_SHORT_TIMEOUT_MS = 5000
ATC_DOC_MEDIUM_TIMEOUT_MS = 15000
ATC_DOC_LONG_TIMEOUT_MS = 30000
ATC_DOC_NAV_TIMEOUT_MS = 45000


def _short_desc(value: str, *, fallback: str = "Documento") -> str:
    base = str(value or "").strip()
    if not base:
        base = fallback
    base = re.sub(r"\s+", " ", base).strip()
    return base[:DESC_MAX_LEN]


def _normalize_doc_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _is_resource_doc(file_path: Path) -> bool:
    token = _normalize_doc_name(file_path.stem or file_path.name)
    return "recurso" in token


def _is_authorization_doc(file_path: Path) -> bool:
    token = _normalize_doc_name(file_path.stem or file_path.name)
    return "aut" in token or "autoriza" in token


def _classify_upload_kind(file_path: Path) -> str:
    if _is_resource_doc(file_path):
        return "resource"
    if _is_authorization_doc(file_path):
        return "authorization"
    return "other"


def _assert_registro_minimum_upload_set(upload_files: list[Path]) -> tuple[bool, bool]:
    has_resource = any(_is_resource_doc(path) for path in upload_files)
    has_authorization = any(_is_authorization_doc(path) for path in upload_files)
    if not has_resource or not has_authorization:
        missing_parts: list[str] = []
        if not has_resource:
            missing_parts.append("RECURSO")
        if not has_authorization:
            missing_parts.append("AUTORIZACION")
        raise RuntimeError(
            "atc.documentos: no se puede continuar en ATC sin documentos minimos. "
            f"faltan: {', '.join(missing_parts)}"
        )
    return has_resource, has_authorization


def _build_rea_repos_upload_plan(documentos: list["AtcDocumento"], *, protocol: str) -> list[dict[str, object]]:
    resource_docs = [doc for doc in documentos if _classify_upload_kind(doc.fitxer) == "resource"]
    authorization_docs = [doc for doc in documentos if _classify_upload_kind(doc.fitxer) == "authorization"]
    other_docs = [doc for doc in documentos if _classify_upload_kind(doc.fitxer) == "other"]

    _assert_registro_minimum_upload_set([doc.fitxer for doc in documentos])

    ordered_docs = [*resource_docs, *authorization_docs, *other_docs]
    plan: list[dict[str, object]] = []
    for doc in ordered_docs:
        kind = _classify_upload_kind(doc.fitxer)
        desc_doc = _short_desc(doc.descripcio or doc.fitxer.stem, fallback="Documento")
        tipus_doc = (doc.tipus or "").strip()
        if kind == "resource":
            desc_doc = _short_desc("RECURSO")
        elif kind == "authorization":
            desc_doc = _short_desc("AUTORIZACION")

        if protocol == "rea":
            tipus_doc = "Al-legacions" if kind == "resource" else "Documentacio acreditativa"
        elif not tipus_doc:
            tipus_doc = "Documentacio acreditativa si escau"

        plan.append(
            {
                "fitxer": doc.fitxer,
                "kind": kind,
                "tipus": tipus_doc,
                "descripcio": desc_doc,
            }
        )
    return plan


def _normalize_attachment_text(value: str) -> str:
    txt = str(value or "").strip().lower()
    txt = re.sub(r"[\u00b7]+", "", txt)
    txt = re.sub(r"[^a-z0-9]+", " ", txt)
    return " ".join(txt.split())


def _is_reposicio_warning_button_text(value: str) -> bool:
    text = _normalize_attachment_text(value)
    return (
        "continuar amb aquest motiu" in text
        or ("continuar" in text and "motiu" in text)
        or text.startswith("si vull continuar")
        or text.startswith("sí vull continuar")
    )


def _row_matches_expected_upload(row_text: str, *, desc: str, tipus: str) -> bool:
    row_norm = _normalize_attachment_text(row_text)
    desc_norm = _normalize_attachment_text(desc)
    tipus_norm = _normalize_attachment_text(tipus)
    if desc_norm and desc_norm not in row_norm:
        return False
    if "al leg" in tipus_norm or "alleg" in tipus_norm or "alega" in tipus_norm:
        return "al leg" in row_norm or "alleg" in row_norm or "alega" in row_norm
    if "acredit" in tipus_norm:
        return "acredit" in row_norm
    return True


async def _collect_attachment_row_texts(page: "Page") -> list[str]:
    try:
        return await page.evaluate(
            """() => {
                const rows = Array.from(document.querySelectorAll("table tbody tr"));
                return rows
                    .filter((row) => {
                        const st = window.getComputedStyle(row);
                        return st && st.display !== "none" && st.visibility !== "hidden";
                    })
                    .map((row) => String(row.textContent || "").trim())
                    .filter(Boolean);
            }"""
        )
    except Exception:
        return []


async def _assert_rea_upload_plan_registered(
    page: "Page",
    upload_plan: list[dict[str, object]],
    *,
    timeout_ms: int = 20000,
) -> None:
    waited = 0
    last_rows: list[str] = []
    while waited <= timeout_ms:
        last_rows = await _collect_attachment_row_texts(page)
        missing: list[str] = []
        for item in upload_plan:
            desc = str(item.get("descripcio") or "").strip()
            tipus = str(item.get("tipus") or "").strip()
            if not any(_row_matches_expected_upload(row, desc=desc, tipus=tipus) for row in last_rows):
                missing.append(f"{desc}:{tipus}")
        if not missing:
            return
        await page.wait_for_timeout(500)
        waited += 500
    raise RuntimeError(
        "atc.documentos: ATC no registro correctamente los adjuntos REA esperados. "
        f"faltan={missing} rows={last_rows[:6]}"
    )


async def _wait_registro_attachment_slot(page: "Page", idx: int, expected_desc: str) -> None:
    desc_selector = f"#inputAttach{idx}"
    tipo_selector = f"#selectAttach-{idx}"
    desc = page.locator(desc_selector).first
    tipo = page.locator(tipo_selector).first

    await desc.wait_for(state="attached", timeout=ATC_DOC_LONG_TIMEOUT_MS)
    await tipo.wait_for(state="attached", timeout=ATC_DOC_LONG_TIMEOUT_MS)
    await set_bound_value(page, desc_selector, expected_desc)

    selected = False
    try:
        selected = bool(
            await tipo.evaluate(
                """(el) => {
                    const wanted = "17";
                    const opts = Array.from(el.options || []);
                    const hasWanted = opts.some((o) => String(o.value) === wanted);
                    if (!hasWanted) return false;
                    el.value = wanted;
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                    return String(el.value) === wanted;
                }"""
            )
        )
    except Exception:
        selected = False
    if not selected:
        try:
            await select_option_by_label(page, tipo_selector, "Otros")
            selected = True
        except Exception:
            selected = False
    if not selected:
        raise RuntimeError(f"atc.documentos: no se pudo seleccionar tipo 'Otros' en selectAttach-{idx}.")


async def _collect_registro_attachment_issues(
    page: "Page",
    *,
    expected_descs: dict[int, str],
    expected_count: int,
) -> list[str]:
    issues: list[str] = []
    for idx in range(1, expected_count + 1):
        desc = page.locator(f"#inputAttach{idx}").first
        if await desc.count() <= 0:
            issues.append(f"inputAttach{idx}")
        else:
            current_desc = str(await desc.evaluate("(el) => el.value || ''")).strip()
            if not current_desc:
                try:
                    await set_bound_value(page, f"#inputAttach{idx}", expected_descs.get(idx, f"Documento {idx}"))
                    current_desc = str(await desc.evaluate("(el) => el.value || ''")).strip()
                except Exception:
                    current_desc = ""
            if not current_desc:
                issues.append(f"inputAttach{idx}")

        tipo = page.locator(f"#selectAttach-{idx}").first
        if await tipo.count() <= 0:
            issues.append(f"selectAttach-{idx}")
            continue
        current_type = str(await tipo.evaluate("(el) => el.value || ''")).strip()
        if current_type:
            continue
        try:
            await tipo.evaluate(
                """(el) => {
                    const wanted = "17";
                    const opts = Array.from(el.options || []);
                    const picked = opts.find((o) => String(o.value) === wanted)
                        || opts.find((o) => /otros/i.test(String(o.textContent || o.label || "")));
                    if (!picked) return;
                    el.value = String(picked.value);
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                }"""
            )
            current_type = str(await tipo.evaluate("(el) => el.value || ''")).strip()
        except Exception:
            current_type = ""
        if not current_type:
            issues.append(f"selectAttach-{idx}")
    return issues


async def _count_attached_rows(page: "Page") -> int:
    try:
        return int(
            await page.evaluate(
                """() => {
                    const rows = Array.from(document.querySelectorAll("table tbody tr"));
                    const visible = rows.filter((r) => {
                        const st = window.getComputedStyle(r);
                        return st && st.display !== "none" && st.visibility !== "hidden";
                    });
                    return visible.length;
                }"""
            )
        )
    except Exception:
        return 0


async def _wait_attachment_registered(page: "Page", file_path: Path, *, previous_rows: int, timeout_ms: int = 30000) -> None:
    token = (file_path.stem or file_path.name or "").strip().lower()[:18]
    waited = 0
    while waited < timeout_ms:
        try:
            state = await page.evaluate(
                """({ prevRows, token }) => {
                    const norm = (v) =>
                        String(v || "")
                            .normalize("NFD")
                            .replace(/[\\u0300-\\u036f]/g, "")
                            .replace(/\\s+/g, " ")
                            .trim()
                            .toLowerCase();
                    const rows = Array.from(document.querySelectorAll("table tbody tr"));
                    const visible = rows.filter((r) => {
                        const st = window.getComputedStyle(r);
                        return st && st.display !== "none" && st.visibility !== "hidden";
                    });
                    const rowCount = visible.length;
                    const foundByText = visible.some((r) => norm(r.textContent).includes(norm(token)));
                    return { rowCount, foundByText };
                }""",
                {"prevRows": previous_rows, "token": token},
            )
            if state.get("rowCount", 0) > previous_rows or state.get("foundByText", False):
                return
        except Exception:
            pass
        await page.wait_for_timeout(500)
        waited += 500
    raise RuntimeError(f"atc.documentos: timeout esperando confirmacion de adjunto {file_path.name}.")


async def _collect_reposicio_warning_state(page: "Page") -> dict:
    try:
        return await page.evaluate(
            """() => {
                const normalize = (value) =>
                    String(value || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/[^a-z0-9]+/gi, " ")
                        .trim()
                        .toLowerCase();
                const isVisible = (el) => {
                    if (!el) return false;
                    const st = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return !!st && st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                };
                const dialogs = Array.from(document.querySelectorAll("app-allegation-modal, dialog, [role='dialog'], .modal"));
                const visibleDialogs = dialogs
                    .filter((el) => isVisible(el))
                    .map((el) => normalize(el.textContent || ""))
                    .filter(Boolean);
                const buttons = Array.from(document.querySelectorAll("button, [role='button']"))
                    .filter((el) => isVisible(el))
                    .map((el) => normalize(el.textContent || el.getAttribute("aria-label") || ""))
                    .filter(Boolean);
                return {
                    visibleDialogCount: visibleDialogs.length,
                    visibleDialogs: visibleDialogs.slice(0, 5),
                    buttons: buttons.slice(0, 12),
                    loading: normalize(document.body?.innerText || "").includes("carregant"),
                };
            }"""
        )
    except Exception:
        return {"visibleDialogCount": 0, "visibleDialogs": [], "buttons": [], "loading": False}


async def _click_reposicio_warning_button(page: "Page") -> bool:
    selectors = [
        "app-allegation-modal button.se-button--primary",
        "app-allegation-modal button",
        "[role='dialog'] button.se-button--primary",
        "[role='dialog'] button",
        "dialog button.se-button--primary",
        "dialog button",
        "button.se-button--primary",
        "button",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        count = 0
        try:
            count = await locator.count()
        except Exception:
            count = 0
        for idx in range(count):
            btn = locator.nth(idx)
            try:
                text = str(await btn.evaluate("(el) => el.textContent || el.getAttribute('aria-label') || ''")).strip()
            except Exception:
                text = ""
            if not _is_reposicio_warning_button_text(text):
                continue
            try:
                await btn.click(timeout=ATC_DOC_SHORT_TIMEOUT_MS)
                await wait_after_action(page)
                return True
            except Exception:
                try:
                    await btn.click(timeout=ATC_DOC_SHORT_TIMEOUT_MS, force=True)
                    await wait_after_action(page)
                    return True
                except Exception:
                    continue

    clicked = bool(
        await page.evaluate(
            """() => {
                const normalize = (value) =>
                    String(value || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/[^a-z0-9]+/gi, " ")
                        .trim()
                        .toLowerCase();
                const isVisible = (el) => {
                    if (!el) return false;
                    const st = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return !!st && st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                };
                const buttons = Array.from(document.querySelectorAll("button, [role='button']"));
                const target = buttons.find((el) => {
                    if (!isVisible(el)) return false;
                    const text = normalize(el.textContent || el.getAttribute("aria-label") || "");
                    return (
                        text.includes("continuar amb aquest motiu") ||
                        (text.includes("continuar") && text.includes("motiu")) ||
                        text.startsWith("si vull continuar")
                    );
                });
                if (!target) return false;
                target.click();
                return true;
            }"""
        )
    )
    if clicked:
        await wait_after_action(page)
    return clicked


async def _confirm_reposicio_warning_modal(page: "Page") -> None:
    last_state: dict = {}
    click_attempted = False
    for _ in range(24):
        last_state = await _collect_reposicio_warning_state(page)
        has_visible_modal = bool(last_state.get("visibleDialogCount"))
        if not has_visible_modal and click_attempted:
            return
        if has_visible_modal:
            clicked = await _click_reposicio_warning_button(page)
            click_attempted = click_attempted or clicked
            if clicked:
                post_click_state = await _collect_reposicio_warning_state(page)
                if not post_click_state.get("visibleDialogCount"):
                    return
                last_state = post_click_state
        await page.wait_for_timeout(500)

    if click_attempted and not last_state.get("visibleDialogCount"):
        return
    if not last_state.get("visibleDialogCount"):
        return
    raise RuntimeError(
        "atc.documentos: no se pudo confirmar el modal de advertencia de motivo en reposicion. "
        f"debug={last_state}"
    )


async def _attach_rea_repos_doc(page: "Page", *, file_path: Path, tipus: str, descripcio: str) -> None:
    # Preferir el input oculto #se_upload_file_input (id estable) sobre el link por nombre
    file_input = page.locator("#se_upload_file_input").first
    if await file_input.count():
        await file_input.set_input_files(str(file_path))
        await wait_after_action(page)
    else:
        # CA: "feu clic aquÃ­" / ES: "haga clic aquÃ­" / EN: "click here"
        link = page.get_by_role("link", name=re.compile(
            r"feu clic aqu[iÃ­]|haga clic aqu[iÃ­]|click here", re.IGNORECASE
        )).first
        async with page.expect_file_chooser() as fc_info:
            await link.click()
            await wait_after_action(page)
        chooser = await fc_info.value
        await chooser.set_files(str(file_path))
        await wait_after_action(page)

    dialog = page.locator("dialog, [role='dialog']").first
    await wait_locator_ready(dialog, timeout=20000)

    selected_type = False
    wanted_norm = str(tipus or "").strip().lower()
    wants_allegations = ("al-leg" in wanted_norm) or ("alÂ·leg" in wanted_norm) or ("alega" in wanted_norm)
    # Strategy 1: native <select> inside modal
    try:
        selected_type = bool(
            await dialog.evaluate(
                """(wanted) => {
                    const normalize = (v) =>
                        String(v || "")
                            .normalize("NFD")
                            .replace(/[\\u0300-\\u036f]/g, "")
                            .trim()
                            .toLowerCase();
                    const target = normalize(wanted);
                    const selects = Array.from(document.querySelectorAll("select"));
                    const sel = selects.find((s) => s.closest("dialog,[role='dialog']"));
                    if (!sel) return false;
                    const opts = Array.from(sel.options || []);
                    const match = opts.find((o) => {
                        const t = normalize(o.textContent || o.label || "");
                        return t === target || t.includes(target) || target.includes(t);
                    }) || (() => {
                        const byText = (rx) => opts.find((o) => rx.test(normalize(o.textContent || o.label || "")));
                        if (normalize(wanted).includes("alega") || normalize(wanted).includes("al-leg") || normalize(wanted).includes("alÂ·leg")) {
                            return byText(/al.?leg|alega/);
                        }
                        return byText(/acredit/);
                    })();
                    if (!match) return false;
                    sel.value = match.value;
                    sel.dispatchEvent(new Event("input", { bubbles: true }));
                    sel.dispatchEvent(new Event("change", { bubbles: true }));
                    return true;
                }""",
                tipus,
            )
        )
    except Exception:
        selected_type = False

    # Strategy 2: custom combo (se-select / ARIA combobox)
    if not selected_type:
        for combo_selector in [
            "[role='combobox']",
            "se-select [role='button']",
            "se-select button",
            "button[aria-haspopup='listbox']",
        ]:
            combo = dialog.locator(combo_selector).first
            if await combo.count() <= 0:
                continue
            try:
                await combo.click(timeout=ATC_DOC_SHORT_TIMEOUT_MS)
                await wait_after_action(page)
            except Exception:
                continue
            option = page.get_by_role("option", name=re.compile(re.escape(tipus), re.IGNORECASE)).first
            if await option.count():
                try:
                    await option.click(timeout=ATC_DOC_SHORT_TIMEOUT_MS)
                    await wait_after_action(page)
                    selected_type = True
                    break
                except Exception:
                    pass
            if wants_allegations:
                alt_option = page.get_by_role("option", name=re.compile(r"al.?leg|alega", re.IGNORECASE)).first
            else:
                alt_option = page.get_by_role("option", name=re.compile(r"acredit", re.IGNORECASE)).first
            if await alt_option.count():
                try:
                    await alt_option.click(timeout=ATC_DOC_SHORT_TIMEOUT_MS)
                    await wait_after_action(page)
                    selected_type = True
                    break
                except Exception:
                    pass

    if not selected_type:
        raise RuntimeError(f"atc.documentos: no se pudo seleccionar tipo de documento '{tipus}' para {file_path.name}.")

    desc_value = _short_desc(descripcio, fallback=(file_path.stem or "Documento"))
    desc_filled = False
    for desc_selector in [
        "input[type='text']",
        "textarea",
        "[aria-label*='Descrip']",
        "[id*='descrip']",
    ]:
        field = dialog.locator(desc_selector).first
        if await field.count() <= 0:
            continue
        try:
            await field.fill(desc_value)
            desc_filled = True
            break
        except Exception:
            try:
                await field.evaluate(
                    """(el, v) => {
                        el.value = v;
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                    }""",
                    desc_value,
                )
                desc_filled = True
                break
            except Exception:
                continue

    if not desc_filled:
        raise RuntimeError(f"atc.documentos: no se pudo rellenar descripcion para {file_path.name}.")

    # CA/ES: "Adjuntar" / EN: "Attach"
    btn = dialog.get_by_role("button", name=re.compile(r"Adjuntar|Attach", re.IGNORECASE))
    await btn.first.click()
    await wait_after_action(page)
    try:
        await dialog.wait_for(state="hidden", timeout=ATC_DOC_MEDIUM_TIMEOUT_MS)
    except Exception:
        pass


async def _run_rea_repos_docs(page: "Page", datos: "AtcTarget") -> "Page":
    if datos.protocol == "rea":
        await page.wait_for_url("**/allegacions**", timeout=ATC_DOC_NAV_TIMEOUT_MS)
        textarea = page.locator("textarea#se-recurs-allegations-textarea:visible").first
        if await textarea.count() <= 0:
            textarea = page.locator("textarea#se-recurs-allegations-textarea").first
        if await textarea.count() <= 0:
            raise RuntimeError("atc.documentos: no se encontro textarea de alegaciones.")

        try:
            await textarea.wait_for(state="visible", timeout=20000)
        except Exception:
            await textarea.wait_for(state="attached", timeout=20000)

        texto = (datos.alegaciones or "").strip()[:1000]
        if not texto:
            raise RuntimeError("atc.documentos: texto de alegaciones vacio.")

        try:
            await textarea.click(timeout=ATC_DOC_SHORT_TIMEOUT_MS)
        except Exception:
            pass

        # Escritura directa sobre el nodo visible (sin depender de UUIDs/labels).
        await textarea.evaluate(
            """(el, v) => {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
                if (setter) setter.call(el, v); else el.value = v;
                el.dispatchEvent(new Event("focus", { bubbles: true }));
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                if (typeof el.blur === "function") el.blur();
                el.dispatchEvent(new Event("blur", { bubbles: true }));
            }""",
            texto,
        )

        current_text = (await textarea.input_value()).strip()
        if not current_text:
            try:
                await textarea.fill(texto)
            except Exception:
                pass
            current_text = (await textarea.input_value()).strip()
        if not current_text:
            raise RuntimeError("atc.documentos: no se pudo escribir el texto de alegaciones.")
    else:
        motivo = page.get_by_role("checkbox", name=re.compile(re.escape(datos.motivo_reposicion), re.IGNORECASE))
        if await motivo.count():
            await motivo.first.check()
        else:
            # CA: "Altres motius" / ES: "Otros motivos" / EN: "Other reasons"
            fallback = page.get_by_role("checkbox", name=re.compile(
                r"Altres motius|Otros motivos|Other reasons", re.IGNORECASE
            ))
            if await fallback.count():
                await fallback.first.check()
        # Confirmación en dos pasos del popup de advertencia.
        await _confirm_reposicio_warning_modal(page)
        await page.wait_for_timeout(1000)

    existing_docs = [doc for doc in datos.documentos[:20] if doc.fitxer.exists()]
    source_docs_count = len(existing_docs)
    bundled_upload = False
    has_resource_doc = False
    has_authorization_doc = False
    if existing_docs:
        has_resource_doc, has_authorization_doc = _assert_registro_minimum_upload_set([doc.fitxer for doc in existing_docs])
    # En reposicion/apremios solo se permite 1 adjunto: fusionar todo en un unico PDF.
    if datos.protocol != "rea" and len(existing_docs) > 1:
        merged_pdf = bundle_documents_to_single_pdf_for_palma(
            [doc.fitxer for doc in existing_docs],
            id_recurso=getattr(datos, "idRecurso", None),
            output_dir=Path("tmp/atc_reposicio_bundle"),
        )
        existing_docs = [type(existing_docs[0])(fitxer=merged_pdf, tipus="Documentacio acreditativa si escau", descripcio=merged_pdf.stem)]
        bundled_upload = True

    upload_plan = _build_rea_repos_upload_plan(existing_docs, protocol=datos.protocol) if existing_docs and datos.protocol == "rea" else [
        {
            "fitxer": doc.fitxer,
            "kind": _classify_upload_kind(doc.fitxer),
            "tipus": (doc.tipus or "").strip() or "Documentacio acreditativa si escau",
            "descripcio": _short_desc(doc.descripcio or doc.fitxer.stem, fallback="Documento"),
        }
        for doc in existing_docs
    ]

    uploaded_count = 0
    for idx, item in enumerate(upload_plan, start=1):
        file_path = Path(item["fitxer"])
        prev_rows = await _count_attached_rows(page)
        await _attach_rea_repos_doc(
            page,
            file_path=file_path,
            tipus=str(item["tipus"]),
            descripcio=str(item["descripcio"]),
        )
        await _wait_attachment_registered(page, file_path, previous_rows=prev_rows)
        if datos.protocol == "rea":
            await _assert_rea_upload_plan_registered(page, upload_plan[:idx])
        uploaded_count += 1

    if existing_docs and uploaded_count < len(existing_docs):
        raise RuntimeError(
            f"atc.documentos: subidas incompletas ({uploaded_count}/{len(existing_docs)}). No se continua."
        )
    if datos.protocol == "rea" and upload_plan:
        await _assert_rea_upload_plan_registered(page, upload_plan)
    try:
        datos.payload["atc_source_docs_count"] = source_docs_count
        datos.payload["atc_uploaded_docs_count"] = uploaded_count
        datos.payload["atc_bundled_upload"] = bundled_upload
        datos.payload["atc_uploaded_files"] = [str(Path(item["fitxer"])) for item in upload_plan]
        datos.payload["atc_has_recurso_doc"] = has_resource_doc
        datos.payload["atc_has_authorization_doc"] = has_authorization_doc
        datos.payload["atc_expected_upload_plan"] = [
            {
                "fitxer": str(Path(item["fitxer"])),
                "kind": str(item["kind"]),
                "tipus": str(item["tipus"]),
                "descripcio": str(item["descripcio"]),
            }
            for item in upload_plan
        ]
    except Exception:
        pass

    # CA/ES: "Continuar" / EN: "Continue"
    continue_btn = page.get_by_role("button", name=re.compile(r"Continuar|Continue|Seg[uÃ¼]ent|Seguir", re.IGNORECASE))
    await continue_btn.last.click()
    await wait_after_action(page)
    if datos.protocol == "rea":
        await page.wait_for_url("**/tramitacio-notificacions**", timeout=ATC_DOC_NAV_TIMEOUT_MS)
    else:
        await page.wait_for_url("**/notificacions**", timeout=ATC_DOC_NAV_TIMEOUT_MS)
    return page


async def _upload_registro_doc(page: "Page", *, file_path: Path) -> None:
    await robust_click(page, "#MainContent_TramitsGenericsControl_btnValidDocUpload")

    dialog = page.locator("dialog, [role='dialog'], .modal:visible").last
    if await dialog.count():
        try:
            await wait_locator_ready(dialog, timeout=ATC_DOC_MEDIUM_TIMEOUT_MS)
        except Exception:
            pass

    file_input = page.locator("input[type='file']").last
    if await file_input.count():
        await file_input.set_input_files(str(file_path))
        await wait_after_action(page)
    else:
        async with page.expect_file_chooser() as fc_info:
            # ES: "Agregar Archivos" / EN: "Add Files"
            await page.get_by_role("button", name=re.compile(r"Agregar Archivos|Add Files", re.IGNORECASE)).click()
            await wait_after_action(page)
        chooser = await fc_info.value
        await chooser.set_files(str(file_path))
        await wait_after_action(page)

    # ES: "Subir" / EN: "Upload"
    subir = page.get_by_role("button", name=re.compile(r"Subir|Upload", re.IGNORECASE)).last
    await subir.click()
    await wait_after_action(page)
    # ES: "Cerrar" / CA: "Tancar" / EN: "Close"
    cerrar = page.get_by_role("button", name=re.compile(r"Cerrar|Tancar|Close", re.IGNORECASE)).last
    await cerrar.click()
    await wait_after_action(page)


async def _repair_registro_attachment_fields(page: "Page", expected_descs: dict[int, str]) -> list[str]:
    try:
        return await page.evaluate(
            """({ expected }) => {
                const normDesc = (v, idx) => {
                    const txt = String(v || "").trim().replace(/\\s+/g, " ");
                    if (txt) return txt.slice(0, 60);
                    return `Documento ${idx}`.slice(0, 60);
                };
                const invalid = [];

                const inputNodes = Array.from(document.querySelectorAll("input[id^='inputAttach']"));
                inputNodes.forEach((el) => {
                    const m = /inputAttach(\\d+)/.exec(el.id || "");
                    const idx = m ? Number(m[1]) : 0;
                    const wanted = normDesc((expected && expected[idx]) || "", idx || 1);
                    const current = String(el.value || "").trim();
                    if (!current) {
                        el.value = wanted;
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                        if (typeof el.blur === "function") el.blur();
                        el.dispatchEvent(new Event("blur", { bubbles: true }));
                    }
                    if (!String(el.value || "").trim()) invalid.push(el.id || "inputAttach");
                });

                const selectNodes = Array.from(document.querySelectorAll("select[id^='selectAttach-']"));
                selectNodes.forEach((el) => {
                    const current = String(el.value || "").trim();
                    if (!current) {
                        const options = Array.from(el.options || []);
                        const byValue = options.find((o) => String(o.value) === "17");
                        const byText = options.find((o) => /otros/i.test(String(o.textContent || o.label || "")));
                        const chosen = byValue || byText;
                        if (chosen) {
                            el.value = String(chosen.value);
                            el.dispatchEvent(new Event("input", { bubbles: true }));
                            el.dispatchEvent(new Event("change", { bubbles: true }));
                            if (typeof el.blur === "function") el.blur();
                            el.dispatchEvent(new Event("blur", { bubbles: true }));
                        }
                    }
                    if (!String(el.value || "").trim()) invalid.push(el.id || "selectAttach");
                });
                return invalid;
            }""",
            {"expected": expected_descs},
        )
    except Exception:
        return []


async def _run_registro_docs(page: "Page", datos: "AtcTarget") -> "Page":
    source_docs = [doc for doc in datos.documentos if doc.fitxer.exists()]
    upload_files = [doc.fitxer for doc in source_docs]
    source_docs_count = len(upload_files)
    bundled_upload = False
    has_resource_doc, has_authorization_doc = _assert_registro_minimum_upload_set(upload_files)

    # Si hay más de 5 documentos, agrupar en bundles (<10MB) para estabilizar el flujo de registro.
    if len(upload_files) > 5:
        upload_files = bundle_documents_with_size_limit(
            upload_files,
            id_recurso=getattr(datos, "idRecurso", None),
            output_dir=Path("tmp/atc_registro_bundles"),
            max_bundle_size_bytes=10 * 1024 * 1024,
        )
        bundled_upload = True

    expected_descs: dict[int, str] = {}
    for idx, file_path in enumerate(upload_files, start=1):
        await _upload_registro_doc(page, file_path=file_path)
        expected_descs[idx] = _short_desc(file_path.stem, fallback=f"Documento {idx}")
        try:
            await _wait_registro_attachment_slot(page, idx, expected_descs[idx])
        except Exception as exc:
            raise RuntimeError(
                "atc.documentos: el servidor ATC no registro correctamente el adjunto "
                f"{idx} ({file_path.name})."
            ) from exc
        residual_invalid = await _repair_registro_attachment_fields(page, expected_descs)
        if residual_invalid:
            await page.wait_for_timeout(250)
            residual_invalid = await _repair_registro_attachment_fields(page, expected_descs)
            if residual_invalid:
                raise RuntimeError(
                    "atc.documentos: adjuntos en registro incompletos tras subida. "
                    f"campos: {', '.join(residual_invalid)}"
                )
        if idx < len(upload_files):
            await page.wait_for_timeout(REGISTRO_UPLOAD_GAP_MS)
    # Final verification: ensure ALL attachment fields exist and have values.
    # A subsequent upload postback can clear earlier fields; this catches it.
    if upload_files:
        for _verify_pass in range(3):
            issues = await _collect_registro_attachment_issues(
                page,
                expected_descs=expected_descs,
                expected_count=len(upload_files),
            )
            if not issues:
                break
            await page.wait_for_timeout(800)
        else:
            raise RuntimeError(
                "atc.documentos: ATC no dejo todos los adjuntos registrados antes de validar. "
                f"campos: {', '.join(issues)}"
            )

    try:
        datos.payload["atc_source_docs_count"] = source_docs_count
        datos.payload["atc_uploaded_docs_count"] = len(upload_files)
        datos.payload["atc_bundled_upload"] = bundled_upload
        datos.payload["atc_uploaded_files"] = [str(p) for p in upload_files]
        datos.payload["atc_expected_registro_attachment_count"] = len(upload_files)
        datos.payload["atc_expected_registro_descs"] = {str(idx): desc for idx, desc in expected_descs.items()}
        datos.payload["atc_has_recurso_doc"] = has_resource_doc
        datos.payload["atc_has_authorization_doc"] = has_authorization_doc
    except Exception:
        pass
    return page


async def run_documentos(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    _ = config
    if datos.protocol == "registro_sin_csv":
        return await _run_registro_docs(page, datos)
    return await _run_rea_repos_docs(page, datos)
