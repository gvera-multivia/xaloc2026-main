from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ._dom import robust_click, select_option_by_label, set_bound_value, wait_after_action

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import AtcConfig
    from ..data_models import AtcTarget


class AtcCsvRejectedError(RuntimeError):
    """CSV rechazado por ATC: se debe desviar a flujo sin CSV."""


_THIRD_PERSON_RADIO_RE = re.compile(r"tercera\s+persona|third\s+person", re.IGNORECASE)
ATC_FORM_SHORT_TIMEOUT_MS = 5000
ATC_FORM_MEDIUM_TIMEOUT_MS = 15000
ATC_FORM_NAV_TIMEOUT_MS = 45000
ATC_FORM_VALIDATE_SETTLE_TIMEOUT_MS = 120000


def _matches_third_person_label(value: str) -> bool:
    return bool(_THIRD_PERSON_RADIO_RE.search(str(value or "").strip()))


def _is_third_person_selected(debug_state: dict | None) -> bool:
    state = debug_state or {}
    if bool(state.get("hasThirdNif")) and bool(state.get("hasThirdName")):
        return True

    selected_labels = state.get("selectedLabels") or []
    if any(_matches_third_person_label(label) for label in selected_labels):
        return True

    selected_indexes = state.get("selectedIndexes") or []
    for idx in selected_indexes:
        try:
            if int(idx) == 1:
                return True
        except Exception:
            continue
    return False


def _is_identification_dom_ready(debug_state: dict | None) -> bool:
    state = debug_state or {}
    if bool(state.get("hasThirdNif")) and bool(state.get("hasThirdName")):
        return True
    if bool(state.get("loading")):
        return False
    try:
        return int(state.get("radioCount") or 0) >= 2
    except Exception:
        return False


def _is_post_validate_ui_ready(debug_state: dict | None) -> bool:
    state = debug_state or {}
    if bool(state.get("loading")):
        return False
    return bool(state.get("hasCheckbox"))


def _is_csv_result_ready(debug_state: dict | None) -> bool:
    state = debug_state or {}
    if bool(state.get("loading")):
        return False
    if bool(state.get("hasCsvRejectedModal")):
        return True
    if bool(state.get("continueEnabled")):
        return True
    if bool(state.get("singleSelectableCheckbox")):
        return True
    return False


async def _collect_identification_debug_state(page: "Page") -> dict:
    return await page.evaluate(
        """() => {
            const normalize = (value) =>
                String(value || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();

            const dedupe = (items) => {
                const out = [];
                for (const item of items) {
                    if (!item || out.includes(item)) continue;
                    out.push(item);
                }
                return out;
            };

            const radios = dedupe(
                Array.from(
                    document.querySelectorAll(
                        "input[type='radio'][name='identification'], se-radio input[type='radio'], [role='radio'] input[type='radio']"
                    )
                )
            );

            const described = radios.map((radio, index) => {
                const container =
                    radio.closest("label, se-radio, [role='radio'], .radio-container, .form-check, .mat-radio-button") ||
                    radio.parentElement;
                const label = normalize(
                    container?.textContent ||
                    container?.getAttribute?.("aria-label") ||
                    radio.getAttribute("aria-label") ||
                    ""
                );
                const checked =
                    !!radio.checked ||
                    radio.getAttribute("aria-checked") === "true" ||
                    container?.getAttribute?.("aria-checked") === "true";
                return {
                    index,
                    value: String(radio.value || ""),
                    label,
                    checked,
                };
            });

            const selected = described.filter((item) => item.checked);
            return {
                radioCount: described.length,
                selectedValues: selected.map((item) => item.value),
                selectedIndexes: selected.map((item) => item.index),
                selectedLabels: selected.map((item) => item.label),
                allLabels: described.map((item) => item.label),
                hasThirdNif: !!document.querySelector("#thirdPresenterNif"),
                hasThirdName: !!document.querySelector("#thirdPresenterName"),
                loading: normalize(document.body?.innerText || "").includes("carregant")
                    || normalize(document.body?.innerText || "").includes("cargando")
                    || normalize(document.body?.innerText || "").includes("loading"),
            };
        }"""
    )


async def _wait_identification_dom_ready(page: "Page", *, timeout_ms: int = 45000) -> dict:
    waited = 0
    last_state: dict = {}
    while waited <= timeout_ms:
        try:
            last_state = await _collect_identification_debug_state(page)
        except Exception:
            last_state = {}
        if _is_identification_dom_ready(last_state):
            return last_state
        await page.wait_for_timeout(500)
        waited += 500
    return last_state


async def _collect_post_validate_state(page: "Page") -> dict:
    try:
        return await page.evaluate(
            """() => {
                const normalize = (value) =>
                    String(value || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                const isVisible = (el) => {
                    if (!el) return false;
                    const st = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return !!st && st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                };
                const checkboxSelectors = [
                    "#checkbox-declaracio-responsable_checkbox-input",
                    "input#checkbox-declaracio-responsable_checkbox-input.checkbox-input",
                    "input[id^='checkbox-declaracio-responsable']",
                ];
                const checkbox = checkboxSelectors
                    .map((selector) => document.querySelector(selector))
                    .find(Boolean);
                const continueButton = Array.from(document.querySelectorAll("button, [role='button']"))
                    .find((el) => isVisible(el) && /continuar|continue/.test(normalize(el.textContent || el.getAttribute("aria-label") || "")));
                const validateButton = Array.from(document.querySelectorAll("button, [role='button']"))
                    .find((el) => isVisible(el) && /validant|validando|validating|validat|validado|validated/.test(normalize(el.textContent || el.getAttribute("aria-label") || "")));
                const bodyText = normalize(document.body?.innerText || "");
                return {
                    loading: bodyText.includes("carregant") || bodyText.includes("cargando") || bodyText.includes("loading"),
                    hasCheckbox: !!checkbox,
                    checkboxVisible: isVisible(checkbox),
                    continueDisabled: continueButton ? !!continueButton.disabled || continueButton.getAttribute("aria-disabled") === "true" : null,
                    validateText: normalize(validateButton?.textContent || validateButton?.getAttribute("aria-label") || ""),
                };
            }"""
        )
    except Exception:
        return {"loading": False, "hasCheckbox": False, "checkboxVisible": False, "continueDisabled": None}


async def _wait_post_validate_ui_ready(page: "Page", *, timeout_ms: int = ATC_FORM_VALIDATE_SETTLE_TIMEOUT_MS) -> dict:
    waited = 0
    last_state: dict = {}
    while waited <= timeout_ms:
        last_state = await _collect_post_validate_state(page)
        if _is_post_validate_ui_ready(last_state):
            return last_state
        await page.wait_for_timeout(1000)
        waited += 1000
    return last_state


async def _collect_csv_result_state(page: "Page") -> dict:
    try:
        return await page.evaluate(
            """() => {
                const normalize = (value) =>
                    String(value || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                const isVisible = (el) => {
                    if (!el) return false;
                    const st = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return !!st && st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                };
                const collectSelectableRows = () => {
                    const seen = new Set();
                    const rawNodes = Array.from(
                        document.querySelectorAll("input[type='checkbox'], [role='checkbox'], se-checkbox")
                    );
                    const items = [];
                    for (const node of rawNodes) {
                        if (!node) continue;
                        if (node.closest("dialog, [role='dialog'], app-modal-info, .cc_dialog, .cookie-consent-preferences-overlay")) continue;
                        const input =
                            (node.matches?.("input[type='checkbox']") ? node : null) ||
                            node.querySelector?.("input.checkbox-input, input[type='checkbox']") ||
                            node.closest?.("label, se-checkbox, .checkbox-container, .container, .allegations-form, tr, li, .card, .result-card, .search-result")
                                ?.querySelector?.("input.checkbox-input, input[type='checkbox']") ||
                            null;
                        const host =
                            node.closest?.("label, se-checkbox, .checkbox-container, .container, .allegations-form, tr, li, .card, .result-card, .search-result")
                            || node.parentElement
                            || node;
                        const inputId = String(input?.id || "").trim();
                        const labelNode =
                            (inputId ? document.querySelector(`label[for="${inputId}"]`) : null) ||
                            host?.querySelector?.(".checkbox-container-label, label, .container, .checkbox-container") ||
                            null;
                        const label = normalize(
                            input?.getAttribute?.("aria-label")
                            || node.getAttribute?.("aria-label")
                            || labelNode?.textContent
                            || host?.textContent
                            || ""
                        );
                        const id = normalize(input?.id || "");
                        const name = normalize(input?.name || "");
                        if (id.includes("declaracio-responsable") || name.includes("declaracio-responsable")) continue;
                        if (
                            label.includes("declaro sota la meva")
                            || label.includes("declaro bajo mi")
                            || label.includes("i declare")
                        ) continue;
                        const visible = isVisible(host) || isVisible(node) || isVisible(labelNode) || isVisible(input);
                        if (!visible) continue;
                        const key = inputId || String(host?.id || "") || label;
                        if (!key || seen.has(key)) continue;
                        seen.add(key);
                        const checked =
                            !!input?.checked ||
                            input?.getAttribute?.("aria-checked") === "true" ||
                            node.getAttribute?.("aria-checked") === "true" ||
                            host?.getAttribute?.("aria-checked") === "true";
                        items.push({ key, label, checked });
                    }
                    return items;
                };
                const bodyText = normalize(document.body?.innerText || "");
                const continueButton = Array.from(document.querySelectorAll("button, [role='button']"))
                    .find((el) => isVisible(el) && /continuar|continue/.test(normalize(el.textContent || el.getAttribute("aria-label") || "")));
                const selectableRows = collectSelectableRows();
                const csvRejected = !!Array.from(document.querySelectorAll("app-modal-info, dialog, [role='dialog']")).find((modal) => {
                    if (!isVisible(modal)) return false;
                    const txt = normalize(modal.textContent || "");
                    const hasCsvErrorBlock = !!modal.querySelector("app-csv-error");
                    return txt.includes("no identifiquem el csv")
                        || txt.includes("aquest acte no es pot afegir")
                        || txt.includes("no identificamos el csv")
                        || txt.includes("csv que heu indicat")
                        || txt.includes("csv que ha indicado")
                        || txt.includes("el csv no es correcte")
                        || txt.includes("csv no es correcto")
                        || txt.includes("aquest acte no es pot recorrer")
                        || txt.includes("este acto no se puede recurrir")
                        || (hasCsvErrorBlock && txt.includes("csv"));
                });
                return {
                    loading: bodyText.includes("carregant") || bodyText.includes("cargando") || bodyText.includes("loading"),
                    hasCsvRejectedModal: csvRejected,
                    continuePresent: !!continueButton,
                    continueEnabled: !!continueButton && !continueButton.disabled && continueButton.getAttribute("aria-disabled") !== "true",
                    visibleCheckboxCount: selectableRows.length,
                    checkedCheckboxCount: selectableRows.filter((el) => !!el.checked).length,
                    singleSelectableCheckbox: selectableRows.length === 1,
                };
            }"""
        )
    except Exception:
        return {
            "loading": False,
            "hasCsvRejectedModal": False,
            "continuePresent": False,
            "continueEnabled": False,
            "visibleCheckboxCount": 0,
            "checkedCheckboxCount": 0,
            "singleSelectableCheckbox": False,
        }


async def _wait_csv_result_ready(page: "Page", *, timeout_ms: int = ATC_FORM_NAV_TIMEOUT_MS) -> dict:
    waited = 0
    last_state: dict = {}
    while waited <= timeout_ms:
        last_state = await _collect_csv_result_state(page)
        if _is_csv_result_ready(last_state):
            return last_state
        await page.wait_for_timeout(1000)
        waited += 1000
    return last_state


async def _check_csv_result_checkbox_if_needed(page: "Page") -> dict:
    try:
        checked = bool(
            await page.evaluate(
                """() => {
                    const normalize = (value) =>
                        String(value || "")
                            .normalize("NFD")
                            .replace(/[\\u0300-\\u036f]/g, "")
                            .replace(/\\s+/g, " ")
                            .trim()
                            .toLowerCase();
                    const isVisible = (el) => {
                        if (!el) return false;
                        const st = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return !!st && st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                    };
                    const clickNode = (el) => {
                        if (!el) return;
                        try { el.scrollIntoView({ block: "center", inline: "center" }); } catch (_err) {}
                        for (const [name, Ctor] of [
                            ["pointerdown", PointerEvent],
                            ["mousedown", MouseEvent],
                            ["pointerup", PointerEvent],
                            ["mouseup", MouseEvent],
                            ["click", MouseEvent],
                            ["input", Event],
                            ["change", Event],
                        ]) {
                            try {
                                el.dispatchEvent(new Ctor(name, { bubbles: true, cancelable: true }));
                            } catch (_err) {}
                        }
                        try { if (typeof el.click === "function") el.click(); } catch (_err) {}
                    };
                    const seen = new Set();
                    const rawNodes = Array.from(document.querySelectorAll("input[type='checkbox'], [role='checkbox'], se-checkbox"));
                    const items = [];
                    for (const node of rawNodes) {
                        if (!node) continue;
                        if (node.closest("dialog, [role='dialog'], app-modal-info, .cc_dialog, .cookie-consent-preferences-overlay")) continue;
                        const input =
                            (node.matches?.("input[type='checkbox']") ? node : null) ||
                            node.querySelector?.("input.checkbox-input, input[type='checkbox']") ||
                            node.closest?.("label, se-checkbox, .checkbox-container, .container, .allegations-form, tr, li, .card, .result-card, .search-result")
                                ?.querySelector?.("input.checkbox-input, input[type='checkbox']") ||
                            null;
                        const host =
                            node.closest?.("label, se-checkbox, .checkbox-container, .container, .allegations-form, tr, li, .card, .result-card, .search-result")
                            || node.parentElement
                            || node;
                        const inputId = String(input?.id || "").trim();
                        const labelNode =
                            (inputId ? document.querySelector(`label[for="${inputId}"]`) : null) ||
                            host?.querySelector?.(".checkbox-container-label, label, .container, .checkbox-container") ||
                            null;
                        const label = normalize(
                            input?.getAttribute?.("aria-label")
                            || node.getAttribute?.("aria-label")
                            || labelNode?.textContent
                            || host?.textContent
                            || ""
                        );
                        const id = normalize(input?.id || "");
                        const name = normalize(input?.name || "");
                        if (id.includes("declaracio-responsable") || name.includes("declaracio-responsable")) continue;
                        if (
                            label.includes("declaro sota la meva")
                            || label.includes("declaro bajo mi")
                            || label.includes("i declare")
                        ) continue;
                        const visible = isVisible(host) || isVisible(node) || isVisible(labelNode) || isVisible(input);
                        if (!visible) continue;
                        const key = inputId || String(host?.id || "") || label;
                        if (!key || seen.has(key)) continue;
                        seen.add(key);
                        const checked =
                            !!input?.checked ||
                            input?.getAttribute?.("aria-checked") === "true" ||
                            node.getAttribute?.("aria-checked") === "true" ||
                            host?.getAttribute?.("aria-checked") === "true";
                        items.push({ input, node, host, labelNode, checked });
                    }
                    if (items.length !== 1) return false;
                    const target = items[0];
                    if (target.checked) return true;
                    for (const node of [target.input, target.labelNode, target.node, target.host]) {
                        clickNode(node);
                    }
                    if (target.input) {
                        try { target.input.checked = true; } catch (_err) {}
                        try { target.input.setAttribute("aria-checked", "true"); } catch (_err) {}
                        clickNode(target.input);
                    }
                    try { target.node?.setAttribute?.("aria-checked", "true"); } catch (_err) {}
                    try { target.host?.setAttribute?.("aria-checked", "true"); } catch (_err) {}
                    return !!target.input?.checked
                        || target.input?.getAttribute?.("aria-checked") === "true"
                        || target.node?.getAttribute?.("aria-checked") === "true"
                        || target.host?.getAttribute?.("aria-checked") === "true";
                }"""
            )
        )
        if checked:
            await wait_after_action(page)
            return await _collect_csv_result_state(page)
    except Exception:
        pass
    return await _collect_csv_result_state(page)


async def _wait_for_first_ready_locator(
    page: "Page",
    candidates: list,
    *,
    timeout_ms: int,
    poll_ms: int = 500,
) -> object | None:
    waited = 0
    while waited <= timeout_ms:
        for locator in candidates:
            try:
                if await locator.count() <= 0:
                    continue
                first = locator.first
                try:
                    if await first.is_visible():
                        return first
                except Exception:
                    return first
            except Exception:
                continue
        await page.wait_for_timeout(poll_ms)
        waited += poll_ms
    return None


async def _force_select_third_person_radio(page: "Page") -> None:
    await page.evaluate(
        """() => {
            const normalize = (value) =>
                String(value || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();
            const isThirdPerson = (value) => {
                const text = normalize(value);
                return text.includes("tercera persona") || text.includes("third person");
            };
            const dedupe = (items) => {
                const out = [];
                for (const item of items) {
                    if (!item || out.includes(item)) continue;
                    out.push(item);
                }
                return out;
            };

            const radios = dedupe(
                Array.from(
                    document.querySelectorAll(
                        "input[type='radio'][name='identification'], se-radio input[type='radio'], [role='radio'] input[type='radio']"
                    )
                )
            );

            const withMeta = radios.map((radio, index) => {
                const container =
                    radio.closest("label, se-radio, [role='radio'], .radio-container, .form-check, .mat-radio-button") ||
                    radio.parentElement;
                return {
                    index,
                    radio,
                    container,
                    label: normalize(
                        container?.textContent ||
                        container?.getAttribute?.("aria-label") ||
                        radio.getAttribute("aria-label") ||
                        ""
                    ),
                };
            });

            const target = withMeta.find((item) => isThirdPerson(item.label)) || withMeta[1] || null;
            if (!target) {
                return;
            }

            const clickable = target.container || target.radio;
            if (clickable && typeof clickable.click === "function") {
                clickable.click();
            }

            target.radio.checked = true;
            target.radio.setAttribute("checked", "checked");
            target.radio.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
            target.radio.dispatchEvent(new Event("input", { bubbles: true }));
            target.radio.dispatchEvent(new Event("change", { bubbles: true }));

            if (target.container && typeof target.container.dispatchEvent === "function") {
                target.container.setAttribute("aria-checked", "true");
                target.container.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
            }
        }"""
    )


async def _click_button(page: "Page", patterns: list[str], *, timeout: int = 12000) -> None:
    candidates = [
        page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
        for pattern in patterns
    ]
    button = await _wait_for_first_ready_locator(page, candidates, timeout_ms=timeout)
    if button is not None:
        await button.click(timeout=timeout)
        await wait_after_action(page)
        return
    raise RuntimeError(f"atc.formulario: no se encontro boton esperado ({patterns}).")


async def _fill_csv(page: "Page", csv_acto: str) -> None:
    # Priority: stable IDs/aria first, then placeholder fallbacks
    candidates = [
        page.locator("#csvActInput"),                                              # recurs: id estable
        page.get_by_placeholder("Introduiu el codi CSV"),                         # rea: placeholder
        page.get_by_placeholder("Introduiu el codi CSV\u200b"),                   # rea: con ZWSP
        page.locator("[aria-label='CSV input']"),                                  # recurs: aria-label
        page.get_by_role("textbox", name=re.compile(r"CSV input", re.IGNORECASE)),
    ]
    target = await _wait_for_first_ready_locator(page, candidates, timeout_ms=ATC_FORM_MEDIUM_TIMEOUT_MS)
    if target is not None:
        await target.fill(csv_acto)
        await wait_after_action(page)
        return
    raise RuntimeError("atc.formulario: no se encontro campo CSV.")


async def _identificar_representado(page: "Page", datos: "AtcTarget") -> None:
    await page.wait_for_url("**/identificacio**", timeout=ATC_FORM_NAV_TIMEOUT_MS)
    debug_state = await _wait_identification_dom_ready(page, timeout_ms=ATC_FORM_NAV_TIMEOUT_MS)
    if not _is_identification_dom_ready(debug_state):
        raise RuntimeError(
            "atc.formulario: la pagina de identificacion no termino de cargar antes de buscar tercera persona. "
            f"debug={debug_state}"
        )
    radio_by_role = page.get_by_role("radio", name=_THIRD_PERSON_RADIO_RE)
    radio_click_targets = [
        "se-radio#radio-2",
        "se-radio#radio-2 .radio-container",
        "se-radio#radio-2 label",
        "se-radio#radio-2 .radio-icon-container",
        "se-radio#radio-2 ng-icon[tabindex='0']",
        "se-radio:nth-of-type(2)",
        "se-radio:nth-of-type(2) .radio-container",
        "se-radio:nth-of-type(2) label",
        "se-radio:nth-of-type(2) .radio-icon-container",
        "se-radio:nth-of-type(2) ng-icon[tabindex='0']",
    ]
    debug_state = debug_state or None
    for _ in range(8):
        try:
            if await radio_by_role.count():
                try:
                    await radio_by_role.first.click(timeout=ATC_FORM_SHORT_TIMEOUT_MS)
                    await wait_after_action(page)
                except Exception:
                    await radio_by_role.first.click(timeout=ATC_FORM_SHORT_TIMEOUT_MS, force=True)
                    await wait_after_action(page)
        except Exception:
            pass

        for selector in radio_click_targets:
            try:
                await robust_click(page, selector, timeout=ATC_FORM_SHORT_TIMEOUT_MS)
            except Exception:
                continue
        try:
            await _force_select_third_person_radio(page)
        except Exception:
            pass

        try:
            debug_state = await _collect_identification_debug_state(page)
        except Exception:
            debug_state = None
        if _is_third_person_selected(debug_state):
            break
        await page.wait_for_timeout(350)

    third_nif = page.locator("#thirdPresenterNif")
    third_name = page.locator("#thirdPresenterName")
    third_nif_ready = await _wait_for_first_ready_locator(page, [third_nif], timeout_ms=ATC_FORM_MEDIUM_TIMEOUT_MS)
    third_name_ready = await _wait_for_first_ready_locator(page, [third_name], timeout_ms=ATC_FORM_MEDIUM_TIMEOUT_MS)
    fields_ready = third_nif_ready is not None and third_name_ready is not None
    if not fields_ready:
        debug_state = await _collect_identification_debug_state(page)
        raise RuntimeError(f"atc.formulario: no se activaron campos de tercera persona. debug={debug_state}")

    nif_third = (datos.representado_nif or datos.nifempresa or datos.nif or "").strip()
    name_third = (datos.representado_nombre or datos.nombre_interesado or "").strip()
    await set_bound_value(page, "#thirdPresenterNif", nif_third)
    await set_bound_value(page, "#thirdPresenterName", name_third)
    # CA: "Validar" / ES: "Validar" / EN: "Validate"
    await _click_button(page, [r"Validar", r"Validate"])
    # Tras validar, la vista puede rerenderizarse unos segundos.
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    post_validate_state = await _wait_post_validate_ui_ready(page, timeout_ms=ATC_FORM_VALIDATE_SETTLE_TIMEOUT_MS)
    if not _is_post_validate_ui_ready(post_validate_state):
        raise RuntimeError(
            "atc.formulario: la validacion del NIF no termino de estabilizar antes de marcar la declaracion responsable. "
            f"debug={post_validate_state}"
        )
    # CA: "Validat" / ES: "Validado" / EN: "Validated"
    validado = page.get_by_role("button", name=re.compile(r"Validat|Validado|Validated", re.IGNORECASE))
    if await validado.count():
        await validado.first.wait_for(state="visible", timeout=ATC_FORM_MEDIUM_TIMEOUT_MS)
    # Declaracion responsable: priorizar id estable de input.
    checkbox_candidates = [
        page.locator("#checkbox-declaracio-responsable_checkbox-input"),
        page.locator("input#checkbox-declaracio-responsable_checkbox-input.checkbox-input"),
        page.locator("input[id^='checkbox-declaracio-responsable']"),
        page.get_by_role("checkbox", name=re.compile(r"Declaro sota la meva|Declaro bajo mi|I declare", re.IGNORECASE)),
    ]
    checked_ok = False
    for _ in range(24):
        checkbox = await _wait_for_first_ready_locator(page, checkbox_candidates, timeout_ms=ATC_FORM_SHORT_TIMEOUT_MS)
        if checkbox is not None:
            try:
                if not await checkbox.is_checked():
                    await checkbox.check(timeout=ATC_FORM_SHORT_TIMEOUT_MS)
                    await wait_after_action(page)
                checked_ok = await checkbox.is_checked()
            except Exception:
                try:
                    await checkbox.evaluate(
                        """(el) => {
                            el.checked = true;
                            el.setAttribute('aria-checked', 'true');
                            el.dispatchEvent(new Event('click', { bubbles: true }));
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }"""
                    )
                    checked_ok = bool(await checkbox.evaluate("(el) => !!el.checked"))
                except Exception:
                    checked_ok = False
            if checked_ok:
                break
        await page.wait_for_timeout(500)

    if not checked_ok:
        post_validate_state = await _collect_post_validate_state(page)
        raise RuntimeError(
            "atc.formulario: no se pudo marcar la declaracion responsable tras Validar. "
            f"debug={post_validate_state}"
        )
    # CA/ES: "Continuar" / EN: "Continue"
    await _click_button(page, [r"Continuar", r"Continue"])
    await page.wait_for_url("**/actes-impugnables**", timeout=ATC_FORM_NAV_TIMEOUT_MS)


async def _search_csv_and_continue(page: "Page", datos: "AtcTarget") -> None:
    if datos.protocol == "rea":
        # CA: "Tancar" / ES: "Cerrar" / EN: "Close"
        modal_tancar = page.get_by_role("button", name=re.compile(r"Tancar|Cerrar|Close", re.IGNORECASE))
        if await modal_tancar.count():
            try:
                await modal_tancar.first.click(timeout=3000)
                await wait_after_action(page)
            except Exception:
                pass

    await page.wait_for_url("**/actes-impugnables**", timeout=ATC_FORM_NAV_TIMEOUT_MS)
    await _fill_csv(page, datos.csv_acto)
    # CA: "Cercar" / ES: "Buscar" / EN: "Search"
    cercar_clicked = False
    for selector in [
        "button#btnSearchAct",
        "button[id*='search']",
        "button[type='submit']",
        "se-button button",
        "[role='button']",
    ]:
        try:
            await robust_click(page, selector, timeout=ATC_FORM_SHORT_TIMEOUT_MS)
            cercar_clicked = True
            break
        except Exception:
            continue
    if not cercar_clicked:
        try:
            await _click_button(page, [r"Cercar", r"Buscar", r"Search"])
            cercar_clicked = True
        except Exception:
            pass
    if not cercar_clicked:
        cercar_clicked = bool(
            await page.evaluate(
                """() => {
                    const norm = (v) => String(v || "").replace(/\\s+/g, " ").trim().toLowerCase();
                    const candidates = Array.from(document.querySelectorAll("button, a, [role='button'], se-button"));
                    const el = candidates.find((n) => /^(cercar|buscar|search)$/.test(norm(n.textContent)));
                    if (!el) return false;
                    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                    return true;
                }"""
            )
        )
    if not cercar_clicked:
        raise RuntimeError("atc.formulario: no se pudo clicar el boton Cercar en actes-impugnables.")

    # Si aparece modal de CSV no reconocido (REA o reposicio), activamos fallback estructural sin CSV.
    csv_rejected = False
    for _ in range(20):
        try:
            csv_rejected = bool(
                await page.evaluate(
                    """() => {
                        const modal = document.querySelector("app-modal-info, dialog, [role='dialog']");
                        if (!modal) return false;
                        const txt = (modal.textContent || "")
                            .normalize("NFD")
                            .replace(/[\\u0300-\\u036f]/g, "")
                            .toLowerCase();
                        const hasCsvErrorBlock = !!modal.querySelector("app-csv-error");
                        return txt.includes("no identifiquem el csv")
                            || txt.includes("aquest acte no es pot afegir")
                            || txt.includes("no identificamos el csv")
                            || txt.includes("csv que heu indicat")
                            || txt.includes("csv que ha indicado")
                            || txt.includes("el csv no es correcte")
                            || txt.includes("csv no es correcto")
                            || txt.includes("aquest acte no es pot recorrer")
                            || txt.includes("este acto no se puede recurrir")
                            || (hasCsvErrorBlock && txt.includes("csv"));
                    }"""
                )
            )
        except Exception:
            csv_rejected = False
        if csv_rejected:
            break
        await page.wait_for_timeout(300)

    if csv_rejected:
        accept_clicked = False
        for selector in [
            "app-modal-info button:has-text('Acceptar')",
            "app-modal-info button:has-text('Aceptar')",
            "dialog button:has-text('Acceptar')",
            "dialog button:has-text('Aceptar')",
            "[role='dialog'] button:has-text('Acceptar')",
            "[role='dialog'] button:has-text('Aceptar')",
        ]:
            try:
                await robust_click(page, selector, timeout=ATC_FORM_SHORT_TIMEOUT_MS)
                accept_clicked = True
                break
            except Exception:
                continue
        if not accept_clicked:
            modal_error = page.get_by_role("button", name=re.compile(r"Acceptar|Aceptar|Accept|^OK$", re.IGNORECASE))
            if await modal_error.count():
                await modal_error.first.click(timeout=ATC_FORM_SHORT_TIMEOUT_MS)
        raise AtcCsvRejectedError(f"atc.formulario: CSV rechazado por ATC ({datos.csv_acto}).")

    csv_state = await _wait_csv_result_ready(page, timeout_ms=ATC_FORM_NAV_TIMEOUT_MS)
    if (
        not csv_state.get("hasCsvRejectedModal")
        and not csv_state.get("continueEnabled")
        and csv_state.get("singleSelectableCheckbox")
    ):
        csv_state = await _check_csv_result_checkbox_if_needed(page)
        csv_state = await _wait_csv_result_ready(page, timeout_ms=ATC_FORM_MEDIUM_TIMEOUT_MS)

    if not csv_state.get("hasCsvRejectedModal") and not csv_state.get("continueEnabled"):
        raise RuntimeError(
            "atc.formulario: el resultado del CSV no quedo listo para continuar. "
            f"debug={csv_state}"
        )

    if datos.protocol == "rea":
        dialog = page.locator("dialog, [role='dialog']").first
        # CA/ES: "Continuar" / EN: "Continue"
        cont = dialog.get_by_role("button", name=re.compile(r"Continuar|Continue", re.IGNORECASE))
        if await cont.count():
            try:
                await cont.first.click(timeout=ATC_FORM_SHORT_TIMEOUT_MS)
            except Exception:
                pass

    await _click_button(page, [r"Continuar", r"Continue"])
    await page.wait_for_url("**/allegacions**", timeout=ATC_FORM_NAV_TIMEOUT_MS)


def _build_registro_claim_text(datos: "AtcTarget") -> str:
    preferred = (datos.alegaciones or "").strip()
    if preferred:
        return preferred[:950]
    fallback = (datos.asunto or "").strip()
    if fallback:
        return fallback[:950]
    return f"Aportacion de documentacion expediente {(datos.expediente or 'N/A').strip()}"[:950]


async def _fill_registro(page: "Page", datos: "AtcTarget") -> None:
    await page.wait_for_url("**TramitsGenerics.aspx**", timeout=90000)
    await select_option_by_label(page, "#tipusTramits", datos.tipo_tramite)
    await select_option_by_label(page, "#MainContent_TramitsGenericsControl_ctlTipoDocument_SelectTipusDoc", datos.tipo_documento)
    await select_option_by_label(page, "#MainContent_TramitsGenericsControl_ctlTipoDocument_SelectTipusImpost", datos.impuesto)
    await set_bound_value(page, "#MainContent_TramitsGenericsControl_ctlTipoDocument_NumDoc", datos.num_documento)
    await robust_click(page, "#MainContent_TramitsGenericsControl_ctlTipoDocument_btnCercar")
    await page.locator("#MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxCorreo").first.wait_for(
        state="visible",
        timeout=30000,
    )

    if datos.email:
        await set_bound_value(
            page,
            "#MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxCorreo",
            datos.email,
        )
    if datos.telefono:
        await set_bound_value(
            page,
            "#MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxTelefon",
            datos.telefono,
            digits_only=True,
        )
    if datos.nif_interesado:
        await set_bound_value(page, "#MainContent_TramitsGenericsControl_ctlSubjectepassiu_Text1", datos.nif_interesado)
    if datos.nombre_interesado:
        await set_bound_value(page, "#MainContent_TramitsGenericsControl_ctlSubjectepassiu_Text2", datos.nombre_interesado)

    # Seleccion robusta de organismo: por value estable + verificacion persistente.
    organo_value_hint = None
    organo_norm = str(datos.organo or "").strip().lower()
    if "oficina central de gestion tributaria" in organo_norm:
        organo_value_hint = "56467"
    elif "oficina central de recaudacion" in organo_norm:
        organo_value_hint = "56497"
    elif "oficina central de inspeccion" in organo_norm:
        organo_value_hint = "56496"

    selected_organo = False
    for _ in range(36):  # ~9s max
        try:
            sel = page.locator("#tipusOrgans").first
            if await sel.count() <= 0:
                await page.wait_for_timeout(250)
                continue
            # Esperar opciones cargadas (>1 por optionsCaption vacío)
            opt_count = await sel.evaluate("(el) => Array.from(el.options || []).length")
            if int(opt_count or 0) <= 1:
                await page.wait_for_timeout(250)
                continue

            if organo_value_hint:
                try:
                    await sel.select_option(value=organo_value_hint)
                except Exception:
                    pass
            if not organo_value_hint:
                try:
                    await sel.select_option(label=str(datos.organo or "").strip())
                except Exception:
                    pass

            await sel.evaluate(
                """(el) => {
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                    if (typeof el.blur === "function") el.blur();
                    el.dispatchEvent(new Event("blur", { bubbles: true }));
                }"""
            )
            await page.wait_for_timeout(300)
            current_value = (await sel.evaluate("(el) => String(el.value || '')")).strip()
            selected_organo = current_value != ""
            if selected_organo:
                break
        except Exception:
            selected_organo = False
        await page.wait_for_timeout(250)

    if not selected_organo:
        # Fallback final por label normalizada del helper existente.
        await select_option_by_label(page, "#tipusOrgans", datos.organo, timeout=ATC_FORM_MEDIUM_TIMEOUT_MS)
        await page.wait_for_timeout(300)
        current_value = (await page.locator("#tipusOrgans").first.evaluate("(el) => String(el.value || '')")).strip()
        if not current_value:
            raise RuntimeError("atc.formulario: no se pudo fijar el órgano destinatario (#tipusOrgans).")
    await set_bound_value(page, "#txtAssumpteDesc", _build_registro_claim_text(datos))


async def run_formulario(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    if datos.protocol == "registro_sin_csv":
        await _fill_registro(page, datos)
        return page

    await _identificar_representado(page, datos)
    try:
        await _search_csv_and_continue(page, datos)
        return page
    except AtcCsvRejectedError:
        # Desvio estructural: CSV rechazado -> flujo sin CSV en la misma sesion.
        original_protocol = str(getattr(datos, "protocol", "") or "").strip().lower()
        await page.goto(config.url_registro_form, wait_until="domcontentloaded", timeout=config.navigation_timeout)
        await _fill_registro(page, datos)
        datos.protocol = "registro_sin_csv"
        try:
            datos.payload["protocol"] = "registro_sin_csv"
            if original_protocol:
                datos.payload["atc_original_protocol"] = original_protocol
        except Exception:
            pass
        return page
