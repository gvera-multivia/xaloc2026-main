from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from ._dom import wait_after_action

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page
    from ..config import AtcConfig
    from ..data_models import AtcTarget


_AUTH_URL_MARKERS = (
    "valid.aoc.cat",
    "autenticaciogicar",
    "/o/oauth2/auth",
    "/saml2/post/sso",
)

_POST_AUTH_READY_URL_MARKERS = (
    "tramitsgenerics.aspx",
    "/secured/reas/identificacio",
    "/secured/recurs/identificacio",
)

_PUBLIC_REPOSICIO_URL_MARKERS = (
    "/gestions/impugnacions/recurs/",
    "/gestions/impugnacions/recurs/index.html",
    "/gestions/impugnacions/recursos/",
)

ATC_LOGIN_SHORT_TIMEOUT_MS = 5000
ATC_LOGIN_MEDIUM_TIMEOUT_MS = 15000
ATC_LOGIN_LONG_TIMEOUT_MS = 30000
ATC_LOGIN_ENTRY_TIMEOUT_MS = 30000
ATC_LOGIN_AUTH_TIMEOUT_MS = 120000

_CERT_BUTTON_SELECTOR = (
    "#btnContinuaCert, "
    "[data-testid='certificate-btn'], "
    "button.btn-certificatDigital, "
    "button:has-text('Certificat digital'), "
    "button:has-text('Certificado digital'), "
    "[role='button']:has-text('Certificat digital'), "
    "[role='button']:has-text('Certificado digital')"
)


def _is_auth_url(url: str) -> bool:
    current = (url or "").lower()
    return any(marker in current for marker in _AUTH_URL_MARKERS)


def _is_post_auth_ready_url(url: str) -> bool:
    current = (url or "").lower()
    return any(marker in current for marker in _POST_AUTH_READY_URL_MARKERS)


def _is_reposicio_public_url(url: str) -> bool:
    current = (url or "").lower()
    return any(marker in current for marker in _PUBLIC_REPOSICIO_URL_MARKERS)


async def _click_first_selector(page: "Page", selectors: list[str], *, timeout: int = ATC_LOGIN_MEDIUM_TIMEOUT_MS) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() <= 0:
            continue
        try:
            await locator.wait_for(state="visible", timeout=timeout)
        except Exception:
            try:
                await locator.wait_for(state="attached", timeout=timeout)
            except Exception:
                continue

        try:
            await locator.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass

        for kwargs in ({}, {"force": True}):
            try:
                await locator.click(timeout=timeout, **kwargs)
                await wait_after_action(page)
                return True
            except Exception:
                continue

        try:
            await locator.evaluate("(el) => el.click()")
            await wait_after_action(page)
            return True
        except Exception:
            continue
    return False


async def _click_first_link(page: "Page", patterns: list[str], *, timeout: int = ATC_LOGIN_MEDIUM_TIMEOUT_MS) -> None:
    for pattern in patterns:
        locator = page.get_by_role("link", name=re.compile(pattern, re.IGNORECASE))
        if await locator.count():
            await locator.first.click(timeout=timeout)
            await wait_after_action(page)
            return
    raise RuntimeError(f"atc.login: no se encontro enlace esperado ({patterns}).")


async def _click_presentar_reposicio(page: "Page", *, timeout: int = ATC_LOGIN_MEDIUM_TIMEOUT_MS) -> bool:
    selectors = [
        "a[href*='index.html?moda=1']",
        "a[href*='/recurs/index.html']",
        "a:has-text('Presentar recurs de reposició')",
        "a:has-text('Presentar recurs de reposicio')",
        "a:has-text('Presentar recurs de reposici')",
        "a:has-text('Presentar recurso de reposición')",
        "button:has-text('Presentar recurs de reposició')",
        "button:has-text('Presentar recurs de reposicio')",
        "button:has-text('Presentar recurso de reposición')",
        "[role='button']:has-text('Presentar recurs de reposició')",
        "a:has-text('Presentar recurs')",
        "button:has-text('Presentar recurs')",
    ]
    if await _click_first_selector(page, selectors, timeout=timeout):
        return True

    # Fallback cuando el texto visible no casa con el role accesible.
    return bool(
        await page.evaluate(
            """() => {
                const norm = (s) => String(s || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();
                const candidates = Array.from(document.querySelectorAll("a,button,[role='button']"));
                const target = candidates.find((el) => {
                    const t = norm(el.textContent);
                    return t.includes("presentar") && (t.includes("reposic") || t.includes("recurso"));
                });
                if (!target) return false;
                target.click();
                return true;
            }"""
        )
    )


async def _reposicio_start_link_available(page: "Page") -> bool:
    selectors = [
        "a[href*='seu2.atc.gencat.cat/ca/secured/recurs/identificacio']",
        "a[href*='/ca/secured/recurs/identificacio']",
        "a[href*='/secured/recurs/identificacio']",
        "a[href*='/secured/recurs']",
        "button:has-text('Inicia el tràmit')",
        "button:has-text('Inicia el tramit')",
        "a:has-text('Inicia el tràmit')",
        "a:has-text('Inicia el tramit')",
    ]
    for selector in selectors:
        try:
            if await page.locator(selector).count():
                return True
        except Exception:
            continue
    return False


async def _force_click_reposicio_online_access(page: "Page") -> bool:
    clicked = bool(
        await page.evaluate(
            """() => {
                const norm = (s) => String(s || "")
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
                const fire = (node) => {
                    if (!node) return false;
                    try { node.scrollIntoView({ block: "center", inline: "center" }); } catch (_err) {}
                    for (const [name, Ctor] of [
                        ["pointerdown", PointerEvent],
                        ["mousedown", MouseEvent],
                        ["pointerup", PointerEvent],
                        ["mouseup", MouseEvent],
                        ["click", MouseEvent],
                    ]) {
                        try {
                            node.dispatchEvent(new Ctor(name, { bubbles: true, cancelable: true }));
                        } catch (_err) {}
                    }
                    try { if (typeof node.click === "function") node.click(); } catch (_err) {}
                    return true;
                };
                const nodes = Array.from(document.querySelectorAll("*")).filter(isVisible);
                const matches = nodes.filter((el) => {
                    const text = norm(el.textContent || "");
                    return text === "per internet" || text === "por internet" || text === "online";
                });
                if (!matches.length) return false;
                for (const labelNode of matches) {
                    const targets = [
                        labelNode.closest("[role='button']"),
                        labelNode.closest("button"),
                        labelNode.closest("a"),
                        labelNode.closest(".p-panel-header"),
                        labelNode,
                        labelNode.closest("li"),
                        labelNode.previousElementSibling,
                        labelNode.parentElement,
                    ].filter(Boolean);
                    const seen = new Set();
                    for (const target of targets) {
                        if (seen.has(target)) continue;
                        seen.add(target);
                        if (fire(target)) return true;
                    }
                }
                return false;
            }"""
        )
    )
    if clicked:
        await wait_after_action(page)
    return clicked


async def _expand_reposicio_online_access(page: "Page", *, timeout: int = ATC_LOGIN_MEDIUM_TIMEOUT_MS) -> bool:
    if _is_auth_url(page.url or "") or _is_post_auth_ready_url(page.url or ""):
        return True
    if await _force_click_reposicio_online_access(page):
        return True
    if await _reposicio_start_link_available(page):
        return True

    selectors = [
        "a.hiperDesple",
        "button.hiperDesple",
        "[role='button'].hiperDesple",
        "a:has-text('Per internet')",
        "a:has-text('Por internet')",
        "a:has-text('Online')",
        "button:has-text('Per internet')",
        "button:has-text('Por internet')",
        "button:has-text('Online')",
        "[role='button']:has-text('Per internet')",
        "[role='button']:has-text('Por internet')",
        "[role='button']:has-text('Online')",
    ]
    clicked = await _click_first_selector(page, selectors, timeout=timeout)
    if not clicked:
        clicked = bool(
            await page.evaluate(
                """() => {
                    const norm = (s) => String(s || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                    const candidates = Array.from(document.querySelectorAll("a,button,[role='button']"));
                    const target = candidates.find((el) => {
                        const text = norm(el.textContent);
                        return text === "per internet" || text === "por internet" || text === "online";
                    });
                    if (!target) return false;
                    target.click();
                    return true;
                }"""
            )
        )
        if clicked:
            await wait_after_action(page)

    if not clicked:
        clicked = bool(
            await page.evaluate(
                """() => {
                    const norm = (s) => String(s || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                    const isVisible = (el) => {
                        if (!el) return false;
                        const st = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return !!st && st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                    };
                    const all = Array.from(document.querySelectorAll("*")).filter(isVisible);
                    const labelNode = all.find((el) => {
                        const text = norm(el.textContent || "");
                        return text === "per internet" || text === "por internet" || text === "online";
                    });
                    if (!labelNode) return false;

                    const chain = [
                        labelNode.closest("button"),
                        labelNode.closest("a"),
                        labelNode.closest("[role='button']"),
                        labelNode.closest(".p-panel-header"),
                        labelNode.closest(".p-toggleable-content"),
                        labelNode.closest("li"),
                        labelNode.closest("div"),
                    ].filter(Boolean);

                    for (const node of chain) {
                        try {
                            node.click();
                            return true;
                        } catch (_err) {}
                    }

                    const prev = labelNode.previousElementSibling;
                    if (prev && typeof prev.click === "function") {
                        prev.click();
                        return true;
                    }
                    return false;
                }"""
            )
        )
        if clicked:
            await wait_after_action(page)

    if _is_auth_url(page.url or "") or _is_post_auth_ready_url(page.url or ""):
        return True
    return clicked or await _reposicio_start_link_available(page)


async def _click_inicia_tramit_reposicio(page: "Page", *, timeout: int = 20000) -> bool:
    selectors = [
        "a[href*='seu2.atc.gencat.cat/ca/secured/recurs/identificacio']",
        "a[href*='/ca/secured/recurs/identificacio']",
        "a[href*='/secured/recurs/identificacio']",
        "a[href*='/secured/recurs']",
        "a.tit[href*='/secured/recurs']",
    ]
    if await _click_first_selector(page, selectors, timeout=timeout):
        return True

    try:
        await _click_first_link(
            page,
            [r"[Ii]nici[ao].*tr[aàá]mit[e]?", r"Recu[rs]+.*reposic.*[Ii]nici", r"Recurso.*Inicia"],
            timeout=timeout,
        )
        return True
    except Exception:
        pass

    return bool(
        await page.evaluate(
            """() => {
                const norm = (s) => String(s || "")
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
                const links = Array.from(document.querySelectorAll("a,button,[role='button'],se-link,.se-link,.p-panel-header"))
                    .filter(isVisible);
                const target = links.find((el) => {
                    const t = norm(el.textContent);
                    const href = norm(el.getAttribute("href"));
                    const txtOk = t.includes("inicia") && (t.includes("tramit") || t.includes("tramite"));
                    const hrefOk = href.includes("/secured/recurs/identificacio") || href.includes("/secured/recurs");
                    return txtOk || hrefOk;
                });
                if (!target) return false;
                const clickable = target.closest("a,button,[role='button']") || target.querySelector?.("a,button,[role='button']") || target;
                clickable.click();
                return true;
            }"""
        )
    )


async def _wait_for_reposicio_entry(page: "Page", *, timeout_ms: int = ATC_LOGIN_ENTRY_TIMEOUT_MS) -> "Page":
    deadline = time.monotonic() + (timeout_ms / 1000)
    context = page.context
    current = page
    last_url = current.url or ""

    while time.monotonic() < deadline:
        current = await _pick_auth_page(context, current)
        await _accept_cookies_if_present(current)
        url = (current.url or "").lower()
        if url:
            last_url = current.url

        if _is_auth_url(url) or _is_post_auth_ready_url(url):
            return current

        expanded_online_access = False
        if _is_reposicio_public_url(url):
            expanded_online_access = await _expand_reposicio_online_access(current, timeout=ATC_LOGIN_SHORT_TIMEOUT_MS)
            current = await _pick_auth_page(context, current)
            url = (current.url or "").lower()
            if url:
                last_url = current.url
            if _is_auth_url(url) or _is_post_auth_ready_url(url):
                return current

        if await _reposicio_start_link_available(current):
            try:
                async with context.expect_page(timeout=4000) as pop:
                    clicked = await _click_inicia_tramit_reposicio(current, timeout=ATC_LOGIN_SHORT_TIMEOUT_MS)
                    if not clicked:
                        await current.wait_for_timeout(500)
                    else:
                        current = await pop.value
                        await current.wait_for_load_state("domcontentloaded")
                        return current
            except Exception:
                clicked = await _click_inicia_tramit_reposicio(current, timeout=ATC_LOGIN_SHORT_TIMEOUT_MS)
                if clicked:
                    await current.wait_for_timeout(1500)
        elif expanded_online_access:
            await current.wait_for_timeout(1200)

        try:
            await current.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        await current.wait_for_timeout(750)

    raise RuntimeError(
        "atc.login: la landing publica de reposicion no avanzo al inicio del tramite. "
        f"ultima_url={last_url}"
    )


async def _click_inicia_tramit_rea(page: "Page", *, timeout: int = 20000) -> bool:
    selectors = [
        "a.tit[href='https://seu2.atc.gencat.cat/ca/secured/reas/identificacio']",
        "a.tit[href*='/ca/secured/reas/identificacio']",
        "a.tit[href*='/secured/reas/identificacio']",
        "a.tit[href*='seu2.atc.gencat.cat'][href*='/secured/reas']",
        "a[href*='seu2.atc.gencat.cat/ca/secured/reas']",
    ]
    if await _click_first_selector(page, selectors, timeout=timeout):
        return True

    try:
        await _click_first_link(
            page,
            [r"[Ii]nici[ao].*tr[aÃ Ã¡]mit[e]?\b|Start.*procedure"],
            timeout=timeout,
        )
        return True
    except Exception:
        pass

    # Fallback when accessible-name matching fails due hidden sr-only text.
    return bool(
        await page.evaluate(
            """() => {
                const normalize = (v) => String(v || "").replace(/\\s+/g, " ").trim().toLowerCase();
                const links = Array.from(document.querySelectorAll("a.tit, a[href*='/secured/reas']"));
                const target = links.find((a) => {
                    const text = normalize(a.textContent);
                    const href = normalize(a.getAttribute("href"));
                    const textOk = /inicia\\s+el\\s+tr[aÃ Ã¡]mit(e)?/.test(text) || /start\\s+the\\s+procedure/.test(text);
                    const hrefOk = href.includes("/secured/reas/identificacio") || href.includes("/secured/reas");
                    return textOk || hrefOk;
                });
                if (!target) return false;
                target.click();
                return true;
            }"""
        )
    )


async def _accept_cookies_if_present(page: "Page") -> None:
    selectors = [
        "#ppms_cm_agree-to-all",
        "button.ppms_cm_button_primary",
    ]
    patterns = [
        r"Ac[eÃ©]ptalas todas",
        r"Aceptar",
        r"Acceptar",
        r"Accept all",
        r"Guardar los cambios",
    ]

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() <= 0:
                continue
            await locator.click(timeout=ATC_LOGIN_SHORT_TIMEOUT_MS)
            await page.wait_for_timeout(400)
            return
        except Exception:
            try:
                await locator.click(timeout=ATC_LOGIN_SHORT_TIMEOUT_MS, force=True)
                await page.wait_for_timeout(400)
                return
            except Exception:
                continue

    for pattern in patterns:
        button = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first
        try:
            if await button.count() <= 0:
                continue
            await button.click(timeout=ATC_LOGIN_SHORT_TIMEOUT_MS)
            await page.wait_for_timeout(400)
            return
        except Exception:
            try:
                await button.click(timeout=ATC_LOGIN_SHORT_TIMEOUT_MS, force=True)
                await page.wait_for_timeout(400)
                return
            except Exception:
                continue


async def _robust_click(page: "Page", selector: str, *, timeout: int = 15000) -> bool:
    locator = page.locator(selector).first
    if await locator.count() <= 0:
        return False

    try:
        await locator.wait_for(state="visible", timeout=timeout)
    except Exception:
        try:
            await locator.wait_for(state="attached", timeout=timeout)
        except Exception:
            return False

    try:
        await locator.scroll_into_view_if_needed(timeout=timeout)
    except Exception:
        pass

    for kwargs in ({}, {"force": True}):
        try:
            await locator.click(timeout=timeout, **kwargs)
            await wait_after_action(page)
            return True
        except Exception:
            continue

    try:
        await locator.evaluate("(el) => el.click()")
        await wait_after_action(page)
        return True
    except Exception:
        return False


async def _has_certificate_button(page: "Page") -> bool:
    try:
        if await page.locator(_CERT_BUTTON_SELECTOR).count():
            return True
    except Exception:
        pass
    button = page.get_by_role("button", name=re.compile(r"certificat|certificado", re.IGNORECASE))
    return await button.count() > 0


async def _resolve_cert_button(page: "Page", selector: str, timeout_ms: int):
    locator = page.locator(selector)
    deadline = time.monotonic() + (max(1, int(timeout_ms)) / 1000.0)
    last_count = 0

    while time.monotonic() < deadline:
        try:
            await locator.first.wait_for(state="attached", timeout=1800)
        except Exception:
            await page.wait_for_timeout(150)
            continue

        try:
            count = await locator.count()
        except Exception:
            count = 0
        last_count = count
        if count <= 0:
            await page.wait_for_timeout(150)
            continue

        for idx in range(count):
            candidate = locator.nth(idx)
            try:
                if await candidate.is_visible():
                    return candidate, idx, count
            except Exception:
                continue

        await page.wait_for_timeout(150)

    if last_count > 0:
        return locator.first, 0, last_count

    raise RuntimeError(f"atc.login: no se encontro boton de certificado con selector: {selector}")


async def _click_certificate_button(page: "Page") -> None:
    await _accept_cookies_if_present(page)
    try:
        button, _, _ = await _resolve_cert_button(page, _CERT_BUTTON_SELECTOR, ATC_LOGIN_LONG_TIMEOUT_MS)
    except Exception:
        button = page.get_by_role("button", name=re.compile(r"certificat|certificado", re.IGNORECASE)).first
        if await button.count() <= 0:
            raise RuntimeError("atc.login: no se encontro boton de acceso con certificado.")

    try:
        await button.scroll_into_view_if_needed(timeout=1200)
    except Exception:
        pass

    for kwargs in ({"no_wait_after": True}, {"no_wait_after": True, "force": True}):
        try:
            await button.click(timeout=ATC_LOGIN_LONG_TIMEOUT_MS, **kwargs)
            await wait_after_action(page)
            return
        except Exception:
            continue

    clicked = await page.evaluate(
        """({ selector }) => {
            const nodes = Array.from(document.querySelectorAll(selector));
            if (!nodes.length) return false;
            const visible = nodes.find((el) => {
                const cs = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return cs && cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            });
            (visible || nodes[0]).click();
            return true;
        }""",
        {"selector": _CERT_BUTTON_SELECTOR},
    )
    if not clicked:
        raise RuntimeError("atc.login: no se encontro boton de acceso con certificado.")
    await wait_after_action(page)


async def _pick_auth_page(context: "BrowserContext", fallback: "Page") -> "Page":
    candidates = [page for page in context.pages if not page.is_closed()]
    if not candidates:
        return fallback

    for page in reversed(candidates):
        url = (page.url or "").lower()
        if "tramitsgenerics.aspx" in url:
            return page
        if any(marker in url for marker in _AUTH_URL_MARKERS):
            return page
    return candidates[-1]


async def _wait_for_form_after_auth(
    page: "Page",
    *,
    timeout_ms: int = ATC_LOGIN_AUTH_TIMEOUT_MS,
) -> "Page":
    deadline = time.monotonic() + (timeout_ms / 1000)
    context = page.context
    current = page
    last_url = current.url or ""

    while time.monotonic() < deadline:
        current = await _pick_auth_page(context, current)
        await _accept_cookies_if_present(current)
        url = (current.url or "").lower()
        if url:
            last_url = current.url

        if _is_post_auth_ready_url(url):
            try:
                await current.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            return current

        if _is_auth_url(url):
            if await _has_certificate_button(current):
                await _click_certificate_button(current)
                await current.wait_for_timeout(1000)
                continue
            try:
                await current.wait_for_load_state("domcontentloaded", timeout=6000)
            except Exception:
                pass
            await current.wait_for_timeout(750)
            continue

        try:
            await current.wait_for_load_state("domcontentloaded", timeout=4000)
        except Exception:
            pass
        await current.wait_for_timeout(500)

    raise RuntimeError(f"atc.login: no se alcanzo TramitsGenerics.aspx tras autenticacion. ultima_url={last_url}")


async def _login_rea_or_repos(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    await page.goto(config.url_impugnacions, wait_until="domcontentloaded", timeout=config.navigation_timeout)
    await page.wait_for_timeout(config.delay_ms)
    await _accept_cookies_if_present(page)

    current = page
    if datos.protocol == "rea":
        clicked = await _click_first_selector(
            page,
            [
                "a.distribuidora-item-link.atc[href*='/gestions/impugnacions/reclamacio/']",
                "div.distribuidora-item a.distribuidora-item-link.atc[href*='/reclamacio/']",
            ],
            timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS,
        )
        if not clicked:
            # CA: "ReclamaciÃ³ economicoadministrativa" / ES: "ReclamaciÃ³n econÃ³mico-administrativa" / EN: "Economic-administrative claim"
            await _click_first_link(page, [r"Reclamaci.*econ[oÃ³]mic|Economic.*admin"], timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS)

        # "Inicia el trÃ mit" usually opens in a new tab (target="_blank")
        context = page.context
        source_page = page
        for candidate in reversed([p for p in context.pages if not p.is_closed()]):
            if candidate is page:
                continue
            url = (candidate.url or "").lower()
            if "/gestions/impugnacions/reclamacio/" in url or "atc.gencat.cat" in url:
                source_page = candidate
                break
        try:
            await source_page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        await _accept_cookies_if_present(source_page)

        try:
            async with context.expect_page(timeout=20000) as pop:
                inicia_clicked = await _click_inicia_tramit_rea(source_page, timeout=20000)
                if not inicia_clicked:
                    raise RuntimeError("atc.login: no se encontro enlace 'Inicia el tràmit' para REA.")
            current = await pop.value
            await current.wait_for_load_state("domcontentloaded")
        except Exception:
            inicia_clicked = await _click_inicia_tramit_rea(source_page, timeout=20000)
            if not inicia_clicked:
                raise RuntimeError("atc.login: no se encontro enlace 'Inicia el tràmit' para REA.")
            current = source_page
    else:
        clicked = await _click_first_selector(
            page,
            [
                "a.distribuidora-item-link.atc[href*='/gestions/impugnacions/recurs/']",
                "div.distribuidora-item a.distribuidora-item-link.atc[href*='/recurs/']",
            ],
            timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS,
        )
        if not clicked:
            # CA: "Recurs de reposiciÃ³" / ES: "Recurso de reposiciÃ³n"
            await _click_first_link(page, [r"Recurs.*reposic|Recurso.*reposic"], timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS)
        if not _is_auth_url(page.url or "") and not _is_post_auth_ready_url(page.url or ""):
            presentar_clicked = await _click_presentar_reposicio(page, timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS)
            if not presentar_clicked and not await _reposicio_start_link_available(page):
                raise RuntimeError("atc.login: no se encontro boton/enlace 'Presentar recurs de reposicio'.")

        if not _is_auth_url(page.url or "") and not _is_post_auth_ready_url(page.url or ""):
            internet_ready = await _expand_reposicio_online_access(page, timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS)
            if not internet_ready and not await _reposicio_start_link_available(page):
                raise RuntimeError("atc.login: no se encontro acceso 'Per internet' ni enlace de inicio del tramite.")

            # Esperar a que el acordeon termine de renderizar antes de buscar el enlace de inicio.
            await page.wait_for_timeout(1500)

        # "Recurs de reposicio. Inicia el tramit" navega en la MISMA pestanya (no abre nueva).
        # Se intenta capturar nueva pestanya por compatibilidad, pero el timeout es corto (3s).
        context = page.context
        if _is_auth_url(page.url or "") or _is_post_auth_ready_url(page.url or ""):
            current = page
        else:
            inicia_clicked = False
            try:
                async with context.expect_page(timeout=3000) as pop:
                    inicia_clicked = await _click_inicia_tramit_reposicio(page, timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS)
                    if not inicia_clicked:
                        raise RuntimeError("atc.login: no se encontro enlace Inicia el tramit para reposicio.")
                current = await pop.value
                await current.wait_for_load_state("domcontentloaded")
            except Exception:
                # Navegacion en la misma pestanya (comportamiento habitual de ATC).
                if not inicia_clicked:
                    inicia_clicked = await _click_inicia_tramit_reposicio(page, timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS)
                if not inicia_clicked:
                    if _is_auth_url(page.url or "") or _is_post_auth_ready_url(page.url or ""):
                        current = page
                    else:
                        raise RuntimeError("atc.login: no se encontro enlace Inicia el tramit para reposicio.")
                else:
                    current = page

    await _accept_cookies_if_present(current)
    if datos.protocol != "rea" and not _is_auth_url(current.url or "") and not _is_post_auth_ready_url(current.url or ""):
        current = await _wait_for_reposicio_entry(current, timeout_ms=ATC_LOGIN_ENTRY_TIMEOUT_MS)
        await _accept_cookies_if_present(current)
    if await _has_certificate_button(current):
        await _click_certificate_button(current)

    current = await _wait_for_form_after_auth(current, timeout_ms=ATC_LOGIN_AUTH_TIMEOUT_MS)
    return current


async def _login_registro(page: "Page", config: "AtcConfig") -> "Page":
    await page.goto(config.url_registro_entry, wait_until="domcontentloaded", timeout=config.navigation_timeout)
    await page.wait_for_timeout(config.delay_ms)
    await _accept_cookies_if_present(page)

    context = page.context
    current = page
    target = page.locator("a[href*='TramitsGenerics.aspx']").first
    if await target.count():
        try:
            async with context.expect_page(timeout=20000) as pop:
                await target.click(timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS)
            current = await pop.value
            await current.wait_for_load_state("domcontentloaded")
        except Exception:
            await target.click(timeout=ATC_LOGIN_MEDIUM_TIMEOUT_MS)
            current = page
    else:
        await current.goto(config.url_registro_form, wait_until="domcontentloaded", timeout=config.navigation_timeout)

    await _accept_cookies_if_present(current)
    if await _has_certificate_button(current):
        await _click_certificate_button(current)

    current = await _wait_for_form_after_auth(current, timeout_ms=ATC_LOGIN_AUTH_TIMEOUT_MS)
    return current


async def run_login(page: "Page", config: "AtcConfig", datos: "AtcTarget") -> "Page":
    if datos.protocol == "registro_sin_csv":
        return await _login_registro(page, config)
    return await _login_rea_or_repos(page, config, datos)
