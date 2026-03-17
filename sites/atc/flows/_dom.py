from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


ATC_ACTION_DELAY_MS = 1000
ATC_DOM_TIMEOUT_MS = 20000


def _norm_text(value: str) -> str:
    txt = str(value or "").strip().lower()
    if not txt:
        return ""
    txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
    return " ".join(txt.split())


def _norm_digits(value: str) -> str:
    return re.sub(r"\D+", "", str(value or ""))


async def wait_locator_ready(locator: "Locator", *, timeout: int = ATC_DOM_TIMEOUT_MS) -> None:
    if await locator.count() <= 0:
        raise RuntimeError("atc.dom: locator sin elementos.")

    try:
        await locator.wait_for(state="visible", timeout=timeout)
    except Exception:
        await locator.wait_for(state="attached", timeout=timeout)

    try:
        await locator.scroll_into_view_if_needed(timeout=timeout)
    except Exception:
        pass


async def wait_after_action(page: "Page", *, delay_ms: int = ATC_ACTION_DELAY_MS) -> None:
    await page.wait_for_timeout(delay_ms)


async def robust_click(page: "Page", selector: str, *, timeout: int = ATC_DOM_TIMEOUT_MS) -> None:
    locator = page.locator(selector).first
    await wait_locator_ready(locator, timeout=timeout)

    for kwargs in ({}, {"force": True}):
        try:
            await locator.click(timeout=timeout, **kwargs)
            await wait_after_action(page)
            return
        except Exception:
            continue

    await locator.evaluate("(el) => el.click()")
    await wait_after_action(page)


async def set_bound_value(
    page: "Page",
    selector: str,
    value: str,
    *,
    timeout: int = ATC_DOM_TIMEOUT_MS,
    digits_only: bool = False,
) -> None:
    wanted = str(value or "").strip()
    if not wanted:
        return

    locator = page.locator(selector).first
    await wait_locator_ready(locator, timeout=timeout)

    try:
        await locator.click(timeout=timeout)
    except Exception:
        pass

    try:
        await locator.fill("")
    except Exception:
        pass

    try:
        if digits_only:
            await locator.type(wanted, delay=35)
        else:
            await locator.fill(wanted)
    except Exception:
        pass

    await locator.evaluate(
        """(el, wantedValue) => {
            const proto =
                el.tagName === "TEXTAREA"
                    ? window.HTMLTextAreaElement.prototype
                    : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
            if (setter) {
                setter.call(el, wantedValue);
            } else {
                el.value = wantedValue;
            }
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Tab" }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
            if (typeof el.blur === "function") {
                el.blur();
            }
            el.dispatchEvent(new Event("blur", { bubbles: true }));
            return el.value || "";
        }""",
        wanted,
    )

    await wait_after_action(page)

    current = await locator.evaluate("(el) => el.value || ''")
    if digits_only:
        if _norm_digits(current) != _norm_digits(wanted):
            raise RuntimeError(f"atc.dom: no se pudo fijar valor '{wanted}' en {selector}. actual='{current}'.")
    elif _norm_text(current) != _norm_text(wanted):
        raise RuntimeError(f"atc.dom: no se pudo fijar valor '{wanted}' en {selector}. actual='{current}'.")


async def select_option_by_label(page: "Page", selector: str, label: str, *, timeout: int = ATC_DOM_TIMEOUT_MS) -> None:
    wanted = str(label or "").strip()
    if not wanted:
        return

    locator = page.locator(selector).first
    await wait_locator_ready(locator, timeout=timeout)

    for _ in range(20):
        try:
            option_count = await locator.evaluate("(el) => Array.from(el.options || []).length")
        except Exception:
            option_count = 0
        if option_count > 1:
            break
        await page.wait_for_timeout(200)

    selected_value = None
    try:
        result = await locator.select_option(label=wanted)
        selected_value = result[0] if result else None
    except Exception:
        try:
            result = await locator.select_option(value=wanted)
            selected_value = result[0] if result else None
        except Exception:
            selected_value = await locator.evaluate(
                """(el, wantedLabel) => {
                    const normalize = (value) =>
                        String(value || "")
                            .normalize("NFD")
                            .replace(/[\\u0300-\\u036f]/g, "")
                            .trim()
                            .toLowerCase()
                            .replace(/\\s+/g, " ");

                    const wantedNorm = normalize(wantedLabel);
                    const options = Array.from(el.options || []);
                    const match = options.find((option) => {
                        return (
                            normalize(option.textContent) === wantedNorm ||
                            normalize(option.label) === wantedNorm ||
                            normalize(option.value) === wantedNorm
                        );
                    });

                    if (!match) {
                        return null;
                    }

                    el.value = match.value;
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                    if (typeof el.blur === "function") {
                        el.blur();
                    }
                    el.dispatchEvent(new Event("blur", { bubbles: true }));
                    return match.value;
                }""",
                wanted,
            )

    await wait_after_action(page)

    current_value = await locator.evaluate("(el) => el.value || ''")
    current_text = await locator.evaluate(
        "(el) => el.selectedOptions && el.selectedOptions[0] ? (el.selectedOptions[0].textContent || '') : ''"
    )
    if not (selected_value or current_value):
        raise RuntimeError(f"atc.dom: no se pudo seleccionar '{wanted}' en {selector}.")

    if _norm_text(current_text) not in {_norm_text(wanted), ""} and _norm_text(current_value) != _norm_text(wanted):
        raise RuntimeError(
            f"atc.dom: seleccion inesperada en {selector}. esperado='{wanted}' actual='{current_text or current_value}'."
        )


async def get_invalid_required_fields(page: "Page") -> list[str]:
    try:
        return await page.evaluate(
            """() => {
                const nodes = Array.from(document.querySelectorAll(".required.invalid, .invalid"));
                return nodes
                    .map((node) => node.id || node.name || node.getAttribute("data-bind") || node.tagName)
                    .filter(Boolean)
                    .slice(0, 20);
            }"""
        )
    except Exception:
        return []
