"""
Flujo de autenticación para Ayunta Palma.
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.flows.common import robust_click

logger = logging.getLogger(__name__)


def _is_nueva_entrada_url(url: str) -> bool:
    return "/carpetaciudadana/nueva_entrada.aspx" in (url or "")


def _is_preguntar_entrada_url(url: str) -> bool:
    return "/carpetaciudadana/preguntar_entrada_anterior.aspx" in (url or "")


def _is_carpeta_ciudadana_url(url: str) -> bool:
    return "/carpetaciudadana/carpeta_ciudadana.aspx" in (url or "")


def _is_authenticated_portal_url(url: str) -> bool:
    return _is_nueva_entrada_url(url) or _is_preguntar_entrada_url(url) or _is_carpeta_ciudadana_url(url)


def _is_post_login_url(url: str) -> bool:
    return _is_nueva_entrada_url(url) or _is_preguntar_entrada_url(url)


async def _abrir_nueva_instancia(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors

    # Si ya estamos dentro del flujo de interesado, no hacer nada.
    persona_tipo_usuario = page.locator(selectors.persona_tipo_usuario)
    try:
        await persona_tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass

    input_submit = page.locator(selectors.input_nueva_instancia).first
    boton_visible = page.locator(selectors.btn_nueva_instancia_visible).first
    boton_visible_alt = page.locator(selectors.btn_nueva_instancia).first

    async def _persona_visible(timeout_ms: int = 1500) -> bool:
        try:
            await persona_tipo_usuario.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    async def _force_hidden_submit() -> bool:
        try:
            return bool(
                await page.evaluate(
                    """() => {
                        const hidden = document.querySelector('#ctl00_ctl00_cphM_cph_btnUltimoBorradorCancelar, input[id$="btnUltimoBorradorCancelar"]');
                        const cont = hidden ? hidden.closest('.btn-bar-horizontal-centrada-inner') : null;
                        const visibleBtn = cont ? cont.querySelector('button.btn-icono') : document.querySelector('button.redirect-url.stop-click-propagation.btn-icono');
                        let fired = false;
                        if (visibleBtn) {
                            try { visibleBtn.click(); fired = true; } catch {}
                        }
                        if (hidden) {
                            try { hidden.disabled = false; } catch {}
                            try { hidden.style.display = 'block'; } catch {}
                            try { hidden.click(); fired = true; } catch {}
                        }
                        try {
                            if (window.jQuery && hidden) {
                                window.jQuery(hidden).trigger('click');
                                fired = true;
                            }
                        } catch {}
                        try {
                            if (typeof window.__doPostBack === 'function') {
                                window.__doPostBack('ctl00$ctl00$cphM$cph$btnUltimoBorradorCancelar', '');
                                fired = true;
                            }
                        } catch {}
                        return fired;
                    }"""
                )
            )
        except Exception:
            return False

    # Secuencia agresiva: URL directa + clickable-url + submit hidden/postback.
    for intento in range(1, 7):
        if await _persona_visible(timeout_ms=1200):
            return

        clickable_url = None
        try:
            if await input_submit.count() > 0:
                clickable_url = await input_submit.get_attribute("data-clickable-url")
        except Exception:
            clickable_url = None

        urls = [u for u in [clickable_url, config.url_nueva_instancia_directa, config.url_base] if u]
        for u in urls:
            try:
                await page.goto(u, wait_until="domcontentloaded")
                await page.wait_for_timeout(900)
                if await _persona_visible(timeout_ms=1200):
                    return
            except Exception:
                continue

        try:
            await robust_click(
                page,
                description="Nueva instancia",
                primary=boton_visible,
                secondary=boton_visible_alt,
                fallback_selector=selectors.input_nueva_instancia,
                same_screen_check=lambda: asyncio.sleep(0, result=True),
                max_attempts=1,
                retry_wait_ms=900,
            )
        except Exception:
            pass

        fired = await _force_hidden_submit()
        logger.info("[AP-DIAG] Nueva instancia hard intento %s/6 fired=%s url=%s", intento, fired, page.url)
        await page.wait_for_timeout(1200)
        if await _persona_visible(timeout_ms=1800):
            return

    # Si hemos acabado en carpeta ciudadana, forzar la entrada de nuevo
    # al flujo de "nueva entrada" usando la URL base autenticada.
    if _is_carpeta_ciudadana_url(page.url):
        await page.goto(config.url_base, wait_until="domcontentloaded")
        await page.wait_for_timeout(config.delay_ms)

    try:
        await persona_tipo_usuario.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        if _is_post_login_url(page.url):
            await page.goto(config.url_nueva_instancia_directa, wait_until="domcontentloaded")
            await page.wait_for_timeout(config.delay_ms)
            await persona_tipo_usuario.wait_for(state="visible", timeout=12000)
        else:
            raise
    await page.wait_for_timeout(config.delay_ms)


async def ejecutar_login(page: Page, config: AyuntaPalmaConfig) -> Page:
    """
    Accede al portal de Palma y pulsa la opción de certificado dentro del iframe.
    """
    # En sesiones persistentes puede estar ya autenticado aunque la URL no sea concluyente.
    try:
        await page.locator(config.selectors.persona_tipo_usuario).first.wait_for(state="visible", timeout=1200)
        return page
    except Exception:
        pass

    if page.url.startswith(config.url_base) or _is_authenticated_portal_url(page.url):
        # Evitar recargar si ya estamos en la misma URL (perfil persistente)
        await page.wait_for_timeout(config.delay_ms)
        await _abrir_nueva_instancia(page, config)
        return page

    await page.goto(config.url_base, wait_until="networkidle")
    await page.wait_for_timeout(config.delay_ms)
    if _is_authenticated_portal_url(page.url):
        await _abrir_nueva_instancia(page, config)
        return page

    frame = page.frame_locator(config.selectors.login_frame)
    opcion_titulo = frame.locator(config.selectors.login_option_cert_titulo).first
    opcion_fila = frame.locator(config.selectors.login_option_rows).first
    try:
        if await opcion_titulo.count() > 0:
            await opcion_titulo.wait_for(state="visible", timeout=10000)
        else:
            await opcion_fila.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        # Si durante la espera ya hemos navegado a nueva_entrada, seguimos flujo.
        if _is_authenticated_portal_url(page.url):
            await _abrir_nueva_instancia(page, config)
            return page
        raise
    async def _sigue_en_login() -> bool:
        await asyncio.sleep(0)
        return not _is_authenticated_portal_url(page.url)

    await robust_click(
        page,
        description="Login certificado (fila #optSsl)",
        primary=opcion_titulo if await opcion_titulo.count() > 0 else opcion_fila,
        same_screen_check=_sigue_en_login,
        max_attempts=3,
        retry_wait_ms=5000,
    )
    # Esperar transición de estado tras cert (puede tardar varios segundos o pasar por carpeta).
    for _ in range(20):
        if _is_authenticated_portal_url(page.url):
            break
        try:
            if await page.locator(config.selectors.input_nueva_instancia).first.count() > 0:
                break
        except Exception:
            pass
        await page.wait_for_timeout(500)
    await page.wait_for_timeout(config.delay_ms)
    await _abrir_nueva_instancia(page, config)
    return page
