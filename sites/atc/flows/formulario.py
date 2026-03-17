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
            };
        }"""
    )


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
    for pattern in patterns:
        btn = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
        if await btn.count():
            await btn.first.click(timeout=timeout)
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
    for locator in candidates:
        if await locator.count():
            await locator.first.fill(csv_acto)
            await wait_after_action(page)
            return
    raise RuntimeError("atc.formulario: no se encontro campo CSV.")


async def _identificar_representado(page: "Page", datos: "AtcTarget") -> None:
    await page.wait_for_url("**/identificacio**", timeout=ATC_FORM_NAV_TIMEOUT_MS)
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
    debug_state: dict | None = None
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

    third_nif = page.locator("#thirdPresenterNif").first
    third_name = page.locator("#thirdPresenterName").first
    fields_ready = False
    for _ in range(24):
        try:
            if await third_nif.count() and await third_name.count():
                if await third_nif.is_visible() and await third_name.is_visible():
                    fields_ready = True
                    break
        except Exception:
            pass
        await page.wait_for_timeout(500)
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
    # CA: "Validat" / ES: "Validado" / EN: "Validated"
    validado = page.get_by_role("button", name=re.compile(r"Validat|Validado|Validated", re.IGNORECASE))
    if await validado.count():
        await validado.first.wait_for(state="visible", timeout=ATC_FORM_MEDIUM_TIMEOUT_MS)
    # Declaracion responsable: priorizar id estable de input.
    checked_ok = False
    for _ in range(24):
        checkbox = None
        for selector in [
            "#checkbox-declaracio-responsable_checkbox-input",
            "input#checkbox-declaracio-responsable_checkbox-input.checkbox-input",
            "input[id^='checkbox-declaracio-responsable']",
        ]:
            loc = page.locator(selector).first
            if await loc.count():
                checkbox = loc
                break
        if checkbox is None:
            checkbox = page.get_by_role("checkbox", name=re.compile(
                r"Declaro sota la meva|Declaro bajo mi|I declare", re.IGNORECASE
            )).first

        if await checkbox.count():
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
        raise RuntimeError("atc.formulario: no se pudo marcar la declaracion responsable tras Validar.")
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
