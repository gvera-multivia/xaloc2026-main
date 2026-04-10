"""
Flujo de autenticacion para Ayunta Palma.
"""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig


def _is_nueva_entrada_url(url: str) -> bool:
    return "/carpetaciudadana/nueva_entrada.aspx" in (url or "")


def _is_preguntar_entrada_url(url: str) -> bool:
    return "/carpetaciudadana/preguntar_entrada_anterior.aspx" in (url or "")


def _is_post_login_url(url: str) -> bool:
    return _is_nueva_entrada_url(url) or _is_preguntar_entrada_url(url)


def _resolve_nueva_instancia_url(page: Page, clickable_url: str | None) -> str | None:
    if clickable_url and "recuperar=false" in clickable_url.lower():
        return clickable_url

    parsed = urlparse(page.url or "")
    if not _is_preguntar_entrada_url(parsed.path):
        return None

    id_tramite = parse_qs(parsed.query).get("idtramite", [None])[0]
    if not id_tramite:
        return None

    return (
        "https://palma.sedipualba.es/carpetaciudadana/nueva_entrada.aspx"
        f"?idtramite={id_tramite}&recuperar=false"
    )


async def _wait_for_post_login_surface(page: Page, config: AyuntaPalmaConfig, timeout_ms: int = 15000) -> None:
    selectors = config.selectors
    persona_tipo_usuario = page.locator(selectors.persona_tipo_usuario).first
    input_submit = page.locator(selectors.input_nueva_instancia).first

    async def _surface_ready() -> bool:
        if _is_post_login_url(page.url):
            return True
        try:
            if await persona_tipo_usuario.count() > 0 and await persona_tipo_usuario.is_visible():
                return True
        except Exception:
            pass
        try:
            if await input_submit.count() > 0:
                return True
        except Exception:
            pass
        return False

    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    while asyncio.get_running_loop().time() < deadline:
        if await _surface_ready():
            return
        await page.wait_for_timeout(250)


async def _click_hidden_submit(page: Page, selector: str) -> bool:
    try:
        clicked = await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                try { el.click(); return true; } catch (e) {}
                try {
                    const evt = new MouseEvent("click", { bubbles: true, cancelable: true, view: window });
                    el.dispatchEvent(evt);
                    return true;
                } catch (e) {}
                return false;
            }""",
            selector,
        )
        return bool(clicked)
    except Exception:
        return False


async def _abrir_nueva_instancia(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    await _wait_for_post_login_surface(page, config, timeout_ms=max(6000, config.timeouts.transicion))

    # Si ya estamos dentro del flujo de interesado, no hacer nada.
    persona_tipo_usuario = page.locator(selectors.persona_tipo_usuario).first
    try:
        await persona_tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass

    input_submit = page.locator(selectors.input_nueva_instancia).first
    if await input_submit.count() == 0:
        return

    clickable_url = await input_submit.get_attribute("data-clickable-url")
    nueva_instancia_url = _resolve_nueva_instancia_url(page, clickable_url)

    # 1) Prioridad absoluta: URL directa a nueva entrada en blanco.
    if nueva_instancia_url:
        await page.goto(nueva_instancia_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(config.delay_ms)
        if _is_nueva_entrada_url(page.url):
            return

    # 2) Fallback visual sobre el boton decorativo del mismo contenedor.
    boton_visible = page.locator(selectors.btn_nueva_instancia_visible).first
    if await boton_visible.count() > 0 and await boton_visible.is_visible():
        await boton_visible.click(force=True)
        await page.wait_for_timeout(config.delay_ms)
        if _is_nueva_entrada_url(page.url):
            return

    # 3) Fallback DOM: disparar el submit oculto real.
    if await input_submit.is_visible():
        await input_submit.click(force=True)
        await page.wait_for_timeout(config.delay_ms)
        if _is_nueva_entrada_url(page.url):
            return

    clicked_hidden = await _click_hidden_submit(page, selectors.input_nueva_instancia)
    if clicked_hidden:
        await page.wait_for_timeout(config.delay_ms)
        if _is_nueva_entrada_url(page.url):
            return

    # 4) Ultimo recurso: si seguimos en la pantalla intermedia, reintentar por URL.
    if _is_preguntar_entrada_url(page.url) and nueva_instancia_url:
        await page.goto(nueva_instancia_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(config.delay_ms)


async def ejecutar_login(page: Page, config: AyuntaPalmaConfig) -> Page:
    """
    Accede al portal de Palma y pulsa la opcion de certificado dentro del iframe.
    """
    if _is_post_login_url(page.url):
        await page.wait_for_timeout(config.delay_ms)
        await _abrir_nueva_instancia(page, config)
        return page

    if page.url.startswith(config.url_base):
        # Palma emite tokens/iframes de login que conviene refrescar cuando se
        # reutiliza el mismo perfil o pestana. Cargar la misma URL de nuevo
        # evita tokens viejos y estados intermedios que terminan en 403.
        await page.goto(config.url_base, wait_until="domcontentloaded")
        await page.wait_for_timeout(config.delay_ms)
        if _is_post_login_url(page.url):
            await _abrir_nueva_instancia(page, config)
            return page

    await page.goto(config.url_base, wait_until="domcontentloaded")
    await page.wait_for_timeout(config.delay_ms)
    if _is_post_login_url(page.url):
        await _abrir_nueva_instancia(page, config)
        return page

    frame = page.frame_locator(config.selectors.login_frame)
    opciones = [
        frame.locator(config.selectors.login_option_clave_certificado).first,
        frame.locator(config.selectors.login_option_rows).first,
    ]
    opcion = None
    for candidate in opciones:
        try:
            await candidate.wait_for(state="visible", timeout=10000)
            opcion = candidate
            break
        except PlaywrightTimeoutError:
            continue

    if opcion is None:
        if _is_post_login_url(page.url):
            await _abrir_nueva_instancia(page, config)
            return page
        raise PlaywrightTimeoutError("No se encontro una opcion de certificado visible en Palma.")

    await opcion.click()
    await _wait_for_post_login_surface(page, config, timeout_ms=config.timeouts.transicion)
    await page.wait_for_timeout(config.delay_ms)
    await _abrir_nueva_instancia(page, config)
    return page
