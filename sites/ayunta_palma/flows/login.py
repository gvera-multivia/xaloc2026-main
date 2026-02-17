"""
Flujo de autenticacion para Ayunta Palma.
"""

from __future__ import annotations

import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig

logger = logging.getLogger(__name__)


def _is_authenticated_portal_url(url: str) -> bool:
    u = (url or "").lower()
    return (
        "/carpetaciudadana/nueva_entrada.aspx" in u
        or "/carpetaciudadana/preguntar_entrada_anterior.aspx" in u
        or "/carpetaciudadana/carpeta_ciudadana.aspx" in u
    )


async def _is_interesado_stage_ready(page: Page, config: AyuntaPalmaConfig) -> bool:
    selectors = config.selectors
    try:
        persona = page.locator(selectors.persona_tipo_usuario).first
        if await persona.count() > 0 and await persona.is_visible():
            return True
    except Exception:
        pass
    try:
        nuevo = page.locator(selectors.input_nuevo_interesado).first
        if await nuevo.count() > 0:
            return True
    except Exception:
        pass
    return False


async def _abrir_nueva_instancia(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    persona_tipo_usuario = page.locator(selectors.persona_tipo_usuario).first

    try:
        if await _is_interesado_stage_ready(page, config):
            return
        await persona_tipo_usuario.wait_for(state="visible", timeout=2000)
        return
    except PlaywrightTimeoutError:
        pass
    except Exception:
        pass

    try:
        await page.wait_for_selector(selectors.velo, state="hidden", timeout=6000)
    except Exception:
        pass

    await page.wait_for_timeout(5000)
    trigger = await page.evaluate(
        """() => {
            const normalize = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").trim();
            const candidates = Array.from(document.querySelectorAll("input[type='submit']"));
            const target = candidates.find((el) => {
                const id = (el.id || "").toLowerCase();
                const name = (el.name || "").toLowerCase();
                const value = normalize(el.value || "");
                const isCancelar = id.includes("btnultimoborradorcancelar") || name.includes("btnultimoborradorcancelar");
                const byValue =
                    value.includes("nueva instancia en blanco") ||
                    value.includes("nova instancia en blanc") ||
                    value.includes("nova instancia en blanc");
                return isCancelar || byValue;
            });
            if (!target) return { clicked: false, url: null, mode: "none" };

            const url = target.getAttribute("data-clickable-url");
            const wrapper = target.closest(".btn-bar-horizontal-centrada-inner");
            const visibleButton = wrapper ? wrapper.querySelector("button.btn-icono.btn-bl1, button.btn-icono[data-icono='plus.svg']") : null;
            if (visibleButton) {
                try {
                    visibleButton.click();
                    return { clicked: true, url, mode: "button" };
                } catch {}
            }
            try {
                target.click();
                return { clicked: true, url, mode: "hidden-input" };
            } catch {}
            try {
                if (typeof window.__doPostBack === "function") {
                    window.__doPostBack("ctl00$ctl00$cphM$cph$btnUltimoBorradorCancelar", "");
                    return { clicked: true, url, mode: "postback" };
                }
            } catch {}
            return { clicked: false, url, mode: "none" };
        }"""
    )
    logger.info(
        "[AP-DIAG] Nueva instancia trigger: clicked=%s mode=%s clickable_url=%s current_url=%s",
        trigger.get("clicked") if isinstance(trigger, dict) else None,
        trigger.get("mode") if isinstance(trigger, dict) else None,
        trigger.get("url") if isinstance(trigger, dict) else None,
        page.url,
    )

    if not trigger.get("clicked"):
        boton_visible = page.locator(selectors.btn_nueva_instancia_visible).first
        boton_alt = page.locator(selectors.btn_nueva_instancia).first
        hidden_selector = selectors.input_nueva_instancia
        if await boton_visible.count() > 0:
            await boton_visible.wait_for(state="visible", timeout=10000)
            try:
                await boton_visible.click(timeout=5000)
            except Exception:
                await boton_visible.click(force=True, timeout=5000)
        elif await boton_alt.count() > 0:
            await boton_alt.wait_for(state="visible", timeout=10000)
            try:
                await boton_alt.click(timeout=5000)
            except Exception:
                await boton_alt.click(force=True, timeout=5000)
        else:
            await page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (el) el.click();
                }""",
                hidden_selector,
            )

    clickable_url = trigger.get("url") if isinstance(trigger, dict) else None
    if clickable_url:
        try:
            await persona_tipo_usuario.wait_for(state="visible", timeout=6000)
        except PlaywrightTimeoutError:
            logger.info("[AP-DIAG] Nueva instancia: fallback goto clickable_url=%s", clickable_url)
            await page.goto(clickable_url, wait_until="domcontentloaded")

    await page.wait_for_timeout(config.delay_ms)
    try:
        if await _is_interesado_stage_ready(page, config):
            return
        await persona_tipo_usuario.wait_for(state="visible", timeout=8000)
    except PlaywrightTimeoutError:
        # Fallback fuerte: abrir directamente la URL de nueva instancia en blanco.
        logger.warning(
            "[AP-DIAG] Nueva instancia: selector persona no visible tras click. "
            "Forzando URL directa: %s (current_url=%s)",
            config.url_nueva_instancia_directa,
            page.url,
        )
        await page.goto(config.url_nueva_instancia_directa, wait_until="domcontentloaded")
        await page.wait_for_timeout(config.delay_ms)
        if not await _is_interesado_stage_ready(page, config):
            await persona_tipo_usuario.wait_for(state="visible", timeout=20000)
    await page.wait_for_timeout(config.delay_ms)


async def ejecutar_login(page: Page, config: AyuntaPalmaConfig) -> Page:
    """
    Accede al portal de Palma y pulsa la opcion de certificado dentro del iframe.
    """
    try:
        await page.locator(config.selectors.persona_tipo_usuario).first.wait_for(state="visible", timeout=1200)
        return page
    except Exception:
        pass

    # En sesiones persistentes ya podemos estar autenticados, pero sin modal de certificado.
    if _is_authenticated_portal_url(page.url):
        await page.wait_for_timeout(config.delay_ms)
        await _abrir_nueva_instancia(page, config)
        return page

    if not page.url.startswith(config.url_base):
        await page.goto(config.url_base, wait_until="domcontentloaded")
    await page.wait_for_timeout(config.delay_ms)

    # Tras goto también puede quedar autenticado sin mostrar #ventanaModal.
    if _is_authenticated_portal_url(page.url):
        await _abrir_nueva_instancia(page, config)
        return page

    # Si existe boton de nueva instancia, saltar login de certificado.
    try:
        if await page.locator(config.selectors.input_nueva_instancia).first.count() > 0:
            await _abrir_nueva_instancia(page, config)
            return page
    except Exception:
        pass

    frame = page.frame_locator(config.selectors.login_frame)
    opcion_titulo = frame.locator(config.selectors.login_option_cert_titulo).first
    opcion_fila = frame.locator(config.selectors.login_option_rows).first

    if await opcion_titulo.count() > 0:
        await opcion_titulo.wait_for(state="visible", timeout=20000)
        await page.wait_for_timeout(5000)
        try:
            await opcion_titulo.click(timeout=5000)
        except Exception:
            await opcion_titulo.click(force=True, timeout=5000)
    else:
        try:
            await opcion_fila.wait_for(state="visible", timeout=12000)
        except PlaywrightTimeoutError:
            # Fallback: si no aparece el iframe de login, reintentamos flujo autenticado.
            if _is_authenticated_portal_url(page.url):
                await _abrir_nueva_instancia(page, config)
                return page
            await page.goto(config.url_base, wait_until="domcontentloaded")
            await page.wait_for_timeout(config.delay_ms)
            if _is_authenticated_portal_url(page.url):
                await _abrir_nueva_instancia(page, config)
                return page
            raise
        await page.wait_for_timeout(5000)
        try:
            await opcion_fila.click(timeout=5000)
        except Exception:
            await opcion_fila.click(force=True, timeout=5000)

    await page.wait_for_timeout(config.delay_ms)
    await _abrir_nueva_instancia(page, config)
    return page
