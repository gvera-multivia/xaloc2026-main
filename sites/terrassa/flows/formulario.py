from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ._page_eval import evaluate_with_nav_retry

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget

logger = logging.getLogger("xaloc_automation.terrassa")


async def _blur_field(page: "Page", field: "Locator") -> None:
    try:
        await field.press("Tab", timeout=1000)
        return
    except PlaywrightTimeoutError:
        pass
    except Exception:
        pass

    try:
        await field.evaluate(
            """(el) => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                if (typeof el.blur === 'function') el.blur();
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }"""
        )
        return
    except Exception:
        pass

    try:
        field_id = await field.get_attribute("id")
        if not field_id:
            return
        await evaluate_with_nav_retry(
            page,
            """(selector) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                if (typeof el.blur === 'function') el.blur();
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                return true;
            }""",
            f"#{field_id}",
        )
    except Exception:
        pass


async def _fill_and_blur(page: "Page", selector: str, value: str) -> None:
    field = page.locator(selector).first
    await field.fill(value)
    await _blur_field(page, field)


async def _fill_and_verify(page: "Page", selector: str, value: str, *, label: str) -> None:
    expected = str(value or "").strip()
    field = page.locator(selector).first
    last_value = ""
    for attempt in range(1, 4):
        await field.wait_for(state="visible", timeout=15000)
        await field.fill(expected)
        await _blur_field(page, field)
        await page.wait_for_timeout(500)
        try:
            last_value = str(await field.input_value()).strip()
        except Exception:
            last_value = ""
        if last_value == expected:
            return
        logger.warning(
            "terrassa.formulario: campo %s no conserva el valor esperado intento=%s expected=%r actual=%r",
            label,
            attempt,
            expected,
            last_value,
        )

    raise RuntimeError(
        f"terrassa.formulario: el campo {label} no conserva el valor esperado "
        f"(expected={expected!r}, actual={last_value!r})."
    )


async def _fill_field_with_label_fallback(
    page: "Page",
    *,
    selector: str,
    value: str,
    label: str,
    label_patterns: list[str],
    multiline: bool = False,
) -> None:
    expected = str(value or "").strip()
    locator = page.locator(selector).first
    if await locator.count() > 0:
        await _fill_and_blur(page, selector, expected)
        return

    filled = await evaluate_with_nav_retry(
        page,
        """({ value, labelPatterns, multiline }) => {
            const norm = (txt) => String(txt || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, " ")
                .trim();
            const wanted = (labelPatterns || []).map(norm).filter(Boolean);
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style
                    && style.display !== "none"
                    && style.visibility !== "hidden"
                    && rect.width > 0
                    && rect.height > 0;
            };
            const isTargetControl = (el) => {
                if (!el || !isVisible(el) || el.disabled || el.readOnly) return false;
                const tag = String(el.tagName || "").toLowerCase();
                if (multiline) return tag === "textarea";
                if (tag !== "input") return false;
                const type = String(el.getAttribute("type") || "text").toLowerCase();
                return ["", "text", "search", "tel", "number", "date"].includes(type);
            };
            const dispatch = (el) => {
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                if (typeof el.blur === "function") el.blur();
                el.dispatchEvent(new Event("blur", { bubbles: true }));
            };
            const fill = (el) => {
                if (!isTargetControl(el)) return false;
                el.focus?.();
                el.value = value;
                dispatch(el);
                return String(el.value || "").trim() === String(value || "").trim();
            };

            const controls = Array.from(document.querySelectorAll(multiline ? "textarea" : "input"));
            const labels = Array.from(document.querySelectorAll("label, span, div, p, td, th"))
                .filter((el) => {
                    const text = norm(el.textContent || "");
                    return text && wanted.some((needle) => text.includes(needle));
                });

            for (const labelEl of labels) {
                const forId = labelEl.getAttribute("for");
                if (forId) {
                    const byFor = document.getElementById(forId);
                    if (fill(byFor)) return true;
                }

                const containers = [
                    labelEl.parentElement,
                    labelEl.closest("tr"),
                    labelEl.closest("div"),
                    labelEl.closest("fieldset"),
                    labelEl.closest("section"),
                ].filter(Boolean);
                for (const container of containers) {
                    const local = Array.from(container.querySelectorAll(multiline ? "textarea" : "input"));
                    for (const candidate of local) {
                        if (fill(candidate)) return true;
                    }
                }

                const labelRect = labelEl.getBoundingClientRect();
                const sameRow = controls
                    .filter(isTargetControl)
                    .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                    .filter(({ rect }) => Math.abs(rect.top - labelRect.top) < 35 || Math.abs(rect.bottom - labelRect.bottom) < 35)
                    .sort((a, b) => Math.abs(a.rect.left - labelRect.right) - Math.abs(b.rect.left - labelRect.right));
                for (const { el } of sameRow) {
                    if (fill(el)) return true;
                }

                const after = controls
                    .filter(isTargetControl)
                    .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                    .filter(({ rect }) => rect.top >= labelRect.top - 5)
                    .sort((a, b) => (a.rect.top - b.rect.top) || (a.rect.left - b.rect.left));
                for (const { el } of after.slice(0, 4)) {
                    if (fill(el)) return true;
                }
            }
            return false;
        }""",
        {"value": expected, "labelPatterns": label_patterns, "multiline": multiline},
    )
    if not filled:
        raise RuntimeError(
            f"terrassa.formulario: no se pudo rellenar {label} "
            f"(selector={selector!r}, labels={label_patterns!r})."
        )


async def run_formulario(page: "Page", config: "TerrassaConfig", datos: "TerrassaTarget") -> "Page":
    await page.locator(f"a[href='{config.href_actuar_representant}']").first.click()
    await page.wait_for_load_state("domcontentloaded")

    await page.select_option("select#IDPersona_TD", value=str(datos.document_type_value or "1"))
    await page.wait_for_timeout(500)
    await _fill_and_verify(page, "input#IDPersona_ND", datos.document_number, label="IDPersona_ND")

    await _fill_and_verify(page, "input#nom", datos.nombre, label="nom")

    if not datos.is_company:
        await _fill_and_blur(page, "input#cognom1", datos.apellido1)
        if datos.apellido2:
            await _fill_and_blur(page, "input#cognom2", datos.apellido2)

    await _fill_field_with_label_fallback(
        page,
        selector="input#_NUM_EXPEDIENT",
        value=datos.expediente,
        label="expediente",
        label_patterns=["Expedient de la Multa", "Expediente de la multa", "Num expedient"],
    )
    await _fill_field_with_label_fallback(
        page,
        selector="input#_DATA_FET",
        value=datos.fecha_infraccion,
        label="fecha infraccion",
        label_patterns=["Data de la infraccio", "Data de la infracció", "Fecha de la infraccion"],
    )
    await _fill_field_with_label_fallback(
        page,
        selector="input#_MATRICULA",
        value=datos.matricula,
        label="matricula",
        label_patterns=["Matricula del vehicle", "Matrícula del vehicle", "Matricula del vehiculo"],
    )
    await _fill_field_with_label_fallback(
        page,
        selector="input#_MARCA",
        value=datos.marca,
        label="marca",
        label_patterns=["Marca del vehicle", "Marca del vehiculo"],
    )

    await _fill_field_with_label_fallback(
        page,
        selector="textarea#_MOTIUS",
        value=datos.alegaciones,
        label="motivos alegaciones",
        label_patterns=["Motius al legats", "Motius al·legats", "Motivos alegados"],
        multiline=True,
    )
    await _fill_field_with_label_fallback(
        page,
        selector="textarea#_OBSERV",
        value=datos.observaciones,
        label="observaciones",
        label_patterns=["Observacions", "Observaciones"],
        multiline=True,
    )
    return page
