from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


async def dismiss_cookie_banner_if_present(page: "Page", *, timeout_ms: int = 2500) -> bool:
    """
    Rechaza el banner de cookies (Piwik PRO) si aparece.
    Devuelve True si detecto banner (aunque lo haya ocultado por fallback).
    """
    try:
        wrapper = page.locator("#ppms_cm_popup_wrapper, #ppms_cm_popup").first
        if await wrapper.count() <= 0:
            return False
    except Exception:
        return False

    reject_candidates = [
        page.locator("#ppms_cm_reject-all").first,
        page.locator("button[id*='reject']").first,
        page.get_by_role("button", name=re.compile(r"Rech[áa]zalas", re.IGNORECASE)).first,
        page.get_by_role("button", name=re.compile(r"Rebutja-les|Rebutjar|Reject all|Reject", re.IGNORECASE)).first,
        page.locator("button.ppms_cm_button:has-text('Recházalas')").first,
        page.locator("#ppms_cm_close-popup, .ppms_cm_close_popup").first,
    ]
    for btn in reject_candidates:
        try:
            if await btn.count() > 0:
                await btn.click(timeout=timeout_ms, force=True)
                await page.wait_for_timeout(200)
                return True
        except Exception:
            continue

    try:
        await page.evaluate(
            """() => {
                const ids = ["ppms_cm_popup_wrapper", "ppms_cm_popup", "ppms_cm_overlay", "ppms_cm_wall"];
                for (const id of ids) {
                    const el = document.getElementById(id);
                    if (el) el.style.display = "none";
                }
                const wrappers = document.querySelectorAll(".ppms_cm_popup_wrapper, .ppms_cm_popup, .ppms_cm_overlay");
                wrappers.forEach((el) => { el.style.display = "none"; });
                document.body.style.overflow = "auto";
            }"""
        )
        return True
    except Exception:
        return True


async def ensure_cookie_banner_cleared(
    page: "Page",
    *,
    total_timeout_ms: int = 12000,
    poll_ms: int = 300,
) -> None:
    """
    Mantiene vigilancia activa durante una ventana de tiempo para
    cubrir banners que reaparecen justo antes/despues de clicks.
    """
    waited = 0
    stable_absent_hits = 0
    while waited <= total_timeout_ms:
        seen = await dismiss_cookie_banner_if_present(page, timeout_ms=min(2000, poll_ms * 4))
        if seen:
            stable_absent_hits = 0
        else:
            stable_absent_hits += 1
            if stable_absent_hits >= 2:
                return
        await page.wait_for_timeout(poll_ms)
        waited += poll_ms


async def dismiss_cookie_banners_in_context(page: "Page") -> None:
    """
    Aplica limpieza de cookies en la pagina actual y en cualquier popup/tab abierto.
    """
    pages = []
    try:
        pages = list(page.context.pages)
    except Exception:
        pages = [page]
    if page not in pages:
        pages.append(page)
    for p in pages:
        try:
            await ensure_cookie_banner_cleared(p, total_timeout_ms=5000, poll_ms=250)
        except Exception:
            continue
