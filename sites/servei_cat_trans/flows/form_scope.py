from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Frame, Page
    FormScope = Page | Frame


async def _scope_has_guide_root(scope: "FormScope") -> bool:
    try:
        return await scope.locator("[id^='guideContainer-rootPanel']").first.count() > 0
    except Exception:
        return False


async def _scope_is_loading(scope: "FormScope") -> bool:
    try:
        return bool(
            await scope.evaluate(
                """() => {
                    const normalize = (txt) => String(txt || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                    const txt = normalize(document.body?.innerText || "");
                    return ["carregant", "cargando", "loading"].some((token) => txt.includes(token));
                }"""
            )
        )
    except Exception:
        return True


async def _scope_has_writable_fields(scope: "FormScope") -> bool:
    try:
        return bool(
            await scope.evaluate(
                """() => {
                    const isVisible = (el) => {
                        const st = window.getComputedStyle(el);
                        if (!st || st.display === "none" || st.visibility === "hidden") return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    };
                    const fields = Array.from(document.querySelectorAll("input, select, textarea"));
                    return fields.some((el) => {
                        if (!isVisible(el)) return false;
                        const disabled = !!el.disabled || el.getAttribute("aria-disabled") === "true";
                        const readonly = !!el.readOnly || el.hasAttribute("readonly") || el.getAttribute("aria-readonly") === "true";
                        return !disabled && !readonly;
                    });
                }"""
            )
        )
    except Exception:
        return False


async def get_form_scope(page: "Page") -> "FormScope":
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        if await _scope_has_guide_root(frame):
            return frame
    return page


async def wait_form_scope(page: "Page", timeout_ms: int, step_ms: int = 1000) -> "FormScope":
    waited = 0
    last_scope = await get_form_scope(page)

    while waited <= timeout_ms:
        scope = await get_form_scope(page)
        last_scope = scope

        has_root = await _scope_has_guide_root(scope)
        if has_root:
            loading = await _scope_is_loading(scope)
            writable = await _scope_has_writable_fields(scope)
            if (not loading) or writable:
                return scope

        if has_root and waited >= 4000:
            return scope

        await page.wait_for_timeout(step_ms)
        waited += step_ms

    return last_scope
