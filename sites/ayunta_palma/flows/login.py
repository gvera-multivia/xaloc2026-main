"""
Flujo de autenticación para Ayunta Palma.
"""

from __future__ import annotations

import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.flows.common import robust_click


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

    # En Palma el input oculto contiene la URL real de navegación.
    # Priorizamos esta ruta para evitar clics ambiguos en botones duplicados.
    try:
        if await input_submit.count() > 0:
            clickable_url = await input_submit.get_attribute("data-clickable-url")
            if clickable_url:
                await page.goto(clickable_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(config.delay_ms)
    except Exception:
        pass

    async def _misma_pantalla() -> bool:
        # Si ya hemos salido de login hacia cualquier pantalla autenticada,
        # no insistir con reintentos de click.
        if _is_authenticated_portal_url(page.url):
            return False
        try:
            await persona_tipo_usuario.wait_for(state="visible", timeout=900)
            return False
        except PlaywrightTimeoutError:
            return True

    click_error: Exception | None = None
    try:
        await robust_click(
            page,
            description="Nueva instancia",
            primary=boton_visible,
            secondary=boton_visible_alt,
            fallback_selector=selectors.input_nueva_instancia,
            same_screen_check=_misma_pantalla,
            max_attempts=3,
            retry_wait_ms=5000,
        )
    except PlaywrightTimeoutError as e:
        click_error = e

    if click_error:
        clickable_url = None
        try:
            clickable_url = await input_submit.get_attribute("data-clickable-url")
        except Exception:
            clickable_url = None
        if clickable_url:
            await page.goto(clickable_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(config.delay_ms)
        elif _is_carpeta_ciudadana_url(page.url):
            # Fallback: ya autenticado pero atrapado en la carpeta.
            await page.goto(config.url_base, wait_until="domcontentloaded")
            await page.wait_for_timeout(config.delay_ms)
        else:
            raise click_error

    # Fallback adicional: disparar el submit oculto por click/postback.
    if not _is_post_login_url(page.url):
        try:
            fired = bool(
                await page.evaluate(
                    """() => {
                        const hidden = document.getElementById('ctl00_ctl00_cphM_cph_btnUltimoBorradorCancelar');
                        if (hidden) {
                            hidden.click();
                            return true;
                        }
                        if (typeof window.__doPostBack === 'function') {
                            window.__doPostBack('ctl00$ctl00$cphM$cph$btnUltimoBorradorCancelar', '');
                            return true;
                        }
                        return false;
                    }"""
                )
            )
            if fired:
                await page.wait_for_timeout(config.delay_ms)
        except Exception:
            pass

    # Si hemos acabado en carpeta ciudadana, forzar la entrada de nuevo
    # al flujo de "nueva entrada" usando la URL base autenticada.
    if _is_carpeta_ciudadana_url(page.url):
        await page.goto(config.url_base, wait_until="domcontentloaded")
        await page.wait_for_timeout(config.delay_ms)

    try:
        await persona_tipo_usuario.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        if _is_post_login_url(page.url):
            await page.goto(config.url_base, wait_until="domcontentloaded")
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
    await page.wait_for_timeout(config.delay_ms)
    await _abrir_nueva_instancia(page, config)
    return page
