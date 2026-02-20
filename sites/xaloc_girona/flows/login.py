"""
Flujo de autenticación VÀLid para Xaloc.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import time

from playwright.async_api import Page

from sites.xaloc_girona.config import XalocConfig


def _matches_post_login(url: str, pattern: str) -> bool:
    return fnmatch.fnmatch((url or "").lower(), (pattern or "").lower())


def _cert_debug_enabled() -> bool:
    return (os.getenv("XALOC_CERT_DEBUG") or "0").strip().lower() in {"1", "true", "yes", "on"}


def _interesting_url(url: str) -> bool:
    u = (url or "").lower()
    return any(
        key in u
        for key in (
            "valid.aoc.cat",
            "xalocgirona.cat",
            "seu.xalocgirona.cat",
            "oauth2/auth",
            "tramitanocertform",
        )
    )


async def _attach_cert_debug_observers(page: Page) -> None:
    if not _cert_debug_enabled():
        return
    try:
        if getattr(page, "_xaloc_cert_debug_attached", False):
            return
        setattr(page, "_xaloc_cert_debug_attached", True)
    except Exception:
        return

    def _on_console(msg) -> None:  # type: ignore[no-untyped-def]
        try:
            text = getattr(msg, "text", "") or ""
            mtype = getattr(msg, "type", "") or ""
            if _interesting_url(page.url) or "cert" in text.lower() or "ssl" in text.lower():
                logging.info("[CERT-DBG][console] type=%s text=%s", mtype, text[:400])
        except Exception:
            pass

    def _on_dialog(dialog) -> None:  # type: ignore[no-untyped-def]
        try:
            logging.info("[CERT-DBG][dialog] type=%s message=%s", dialog.type, (dialog.message or "")[:400])
        except Exception:
            pass

    def _on_nav(frame) -> None:  # type: ignore[no-untyped-def]
        try:
            if frame == page.main_frame:
                logging.info("[CERT-DBG][nav] main_frame url=%s", page.url)
        except Exception:
            pass

    def _on_req(req) -> None:  # type: ignore[no-untyped-def]
        try:
            url = req.url or ""
            if _interesting_url(url):
                logging.info("[CERT-DBG][request] %s %s", req.method, url)
        except Exception:
            pass

    def _on_res(res) -> None:  # type: ignore[no-untyped-def]
        try:
            url = res.url or ""
            if _interesting_url(url):
                logging.info("[CERT-DBG][response] %s %s", res.status, url)
        except Exception:
            pass

    def _on_req_failed(req) -> None:  # type: ignore[no-untyped-def]
        try:
            url = req.url or ""
            if _interesting_url(url):
                failure = req.failure
                failure_text = ""
                try:
                    failure_text = failure.error_text if failure else ""
                except Exception:
                    failure_text = str(failure)
                logging.warning("[CERT-DBG][requestfailed] %s %s err=%s", req.method, url, failure_text)
        except Exception:
            pass

    page.on("console", _on_console)
    page.on("dialog", _on_dialog)
    page.on("framenavigated", _on_nav)
    page.on("request", _on_req)
    page.on("response", _on_res)
    page.on("requestfailed", _on_req_failed)
    page.context.on(
        "page",
        lambda p: logging.info("[CERT-DBG][context.page] nueva_pestana url=%s", getattr(p, "url", "(sin url)")),
    )
    logging.info("[CERT-DBG] Observadores de diagnostico de certificado instalados.")


async def _log_cert_runtime_state(valid_page: Page) -> None:
    if not _cert_debug_enabled():
        return
    try:
        pages = valid_page.context.pages
        urls = []
        for p in pages:
            try:
                urls.append(p.url)
            except Exception:
                urls.append("(url no disponible)")
        logging.info("[CERT-DBG][state] paginas_contexto=%d urls=%s", len(urls), " | ".join(urls))
    except Exception:
        pass

    try:
        has_focus, visibility = await valid_page.evaluate(
            "() => [document.hasFocus(), document.visibilityState]"
        )
        logging.info(
            "[CERT-DBG][state] valid_page url=%s has_focus=%s visibility=%s",
            valid_page.url,
            has_focus,
            visibility,
        )
    except Exception:
        pass


async def _is_sta_ready(page: Page, url_pattern: str) -> bool:
    try:
        if not _matches_post_login(page.url, url_pattern):
            return False
        await page.wait_for_selector("form#formulario", state="attached", timeout=1200)
        return True
    except Exception:
        return False


async def _aceptar_cookies_si_aparece(page: Page, config: XalocConfig) -> None:
    posibles = config.selectors.cookie_buttons
    for patron in posibles:
        boton = page.get_by_role("button", name=re.compile(patron, re.IGNORECASE))
        try:
            if await boton.count() > 0:
                await boton.first.click(timeout=config.flow_timeouts.cookie_click)
                await page.wait_for_timeout(config.flow_timeouts.short_delay)
                return
        except Exception:
            continue


async def ejecutar_login(page: Page, config: XalocConfig) -> Page:
    # 1. Comprobar si ya estamos en el formulario (por reutilización de pestaña)
    # url_post_login suele ser algo como "http://.../sta/sta/sta"
    actual_url = page.url
    if await _is_sta_ready(page, config.url_post_login):
        logging.info("Pestana ya esta en el formulario STA. Saltando login.")
        return page

    logging.info(f"Navegando a {config.url_base}")
    await page.goto(config.url_base, wait_until="networkidle")
    await page.wait_for_timeout(config.delay_ms)

    # 2. Tras el goto, puede que hayamos redirigido directamente al formulario si hay sesión activa
    if await _is_sta_ready(page, config.url_post_login):
        logging.info("Redireccion directa detectada (sesion activa). Saltando login.")
        return page

    await _aceptar_cookies_si_aparece(page, config)

    logging.info("Localizando enlace 'Tramitacio en linia'...")
    enlace = page.get_by_role(
        "link",
        name=re.compile(config.selectors.tramite_link_regex, re.IGNORECASE),
    ).first
    await enlace.wait_for(state="visible", timeout=config.flow_timeouts.link_appear)

    logging.info("Pulsando enlace y esperando nueva pestana de VALid...")
    async with page.expect_popup() as popup_info:
        await enlace.click()
        await page.wait_for_timeout(config.delay_ms)

    valid_page = await popup_info.value
    await valid_page.wait_for_load_state("domcontentloaded")
    logging.info(f"Pestana detectada: {valid_page.url}")
    await _attach_cert_debug_observers(valid_page)

    logging.info("Esperando el boton de certificado...")
    boton_cert = valid_page.locator(config.selectors.cert_button).first
    await boton_cert.wait_for(state="visible", timeout=config.flow_timeouts.cert_button_appear)

    logging.info("Pulsando boton de certificado...")
    try:
        await boton_cert.click(timeout=config.timeouts.login, no_wait_after=True)
    except Exception:
        # Fallback when overlays intercept click in some environments.
        await boton_cert.click(timeout=config.timeouts.login, no_wait_after=True, force=True)
    await valid_page.wait_for_timeout(config.delay_ms)

    logging.info("Esperando retorno al formulario STA...")
    if _cert_debug_enabled():
        logging.info(
            "[CERT-DBG] Modo diagnostico activo. En Chromium headless no se puede observar una ventana nativa de seleccion de certificado."
        )
    timeout_ms = int(config.timeouts.login)
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    next_debug_tick = time.monotonic()
    while time.monotonic() < deadline:
        if _cert_debug_enabled() and time.monotonic() >= next_debug_tick:
            await _log_cert_runtime_state(valid_page)
            next_debug_tick = time.monotonic() + 5.0
        # Puede redirigir en la propia pestaña VALid...
        try:
            if await _is_sta_ready(valid_page, config.url_post_login):
                logging.info("Login completado con exito - Formulario STA cargado (pestana VALid)")
                return valid_page
        except Exception:
            pass

        # ...o en otra pestaña del mismo contexto.
        try:
            for p in valid_page.context.pages:
                if await _is_sta_ready(p, config.url_post_login):
                    logging.info("Login completado con exito - Formulario STA cargado (pestana del contexto)")
                    return p
        except Exception:
            pass

        await valid_page.wait_for_timeout(500)

    current_url = ""
    try:
        current_url = valid_page.url
    except Exception:
        current_url = "(url no disponible)"
    if _cert_debug_enabled():
        try:
            await valid_page.screenshot(path="screenshots/xaloc_cert_timeout.png", full_page=True)
            logging.info("[CERT-DBG] Screenshot timeout guardado en screenshots/xaloc_cert_timeout.png")
        except Exception:
            pass
    raise RuntimeError(
        "Timeout esperando retorno al formulario STA tras login con certificado. "
        f"URL actual: {current_url}. "
        "Posible seleccion de certificado pendiente/no disponible o bloqueo del proveedor de identidad."
    )


__all__ = ["ejecutar_login"]
