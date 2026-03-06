"""
Login REDSARA — basado en URL-state, sin texto, sin dependencia de idioma.

Flujo de autenticación:
  /es/        (home sin token)  → _goto /es/login
  /es/login                     → click dnt-vertical-card dnt-button
  pasarela.clave.gob.es/Proxy2/ → click button.idp-button[onclick*='AFIRMA']
  [El contexto del navegador inyecta el certificado automáticamente]
  SAML callbacks (reg-api, signOk…)
  /es/        (home con token)  → _goto /es/nuevo-registro
  /es/nuevo-registro            → verificar app-create-registry-step1
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.redsara.config import RedsaraConfig

logger = logging.getLogger(__name__)

# ── Hosts y rutas ─────────────────────────────────────────────────────────────
_HOST_REG     = "reg.redsara.es"
_HOST_API     = "reg-api.redsara.es"
_HOST_CLAVE   = "pasarela.clave.gob.es"
_PATH_IDP     = "/Proxy2/ServiceProvider"
_TRANSIENT    = ("/signOk", "/signKo", "/loginKo", "/login/callback")

# ── Selectores estructurales (sin texto, sin idioma) ─────────────────────────
# /login:   dnt-vertical-card dnt-button    — único visible en /es/login
# modal:    dnt-modal[title-text] dnt-button — modal "Inicio de sesión" (fallback)
# AFIRMA:   button.idp-button[onclick*='AFIRMA'] — código IdP, no texto traducido
#           El browser context inyecta el certificado TLS automáticamente al hacer click.
_SEL_LOGIN_BTN  = "dnt-vertical-card dnt-button"
_SEL_MODAL_BTN  = "dnt-modal[title-text] dnt-button"
_SEL_AFIRMA     = "button.idp-button[onclick*='AFIRMA'], button.idp-button[data-idp='AFIRMA']"


# ── Clasificadores de URL ─────────────────────────────────────────────────────

def _is_login(u: str) -> bool:
    return _HOST_REG in u and "/login" in u

def _is_clave_idp(u: str) -> bool:
    return _HOST_CLAVE in u and _PATH_IDP in u

def _is_clave(u: str) -> bool:
    return _HOST_CLAVE in u

def _is_nuevo(u: str) -> bool:
    return "nuevo-registro" in u.lower()

def _is_transient(u: str) -> bool:
    return (_HOST_REG in u and any(p in u for p in _TRANSIENT)) or _HOST_API in u

def _is_reg_home(u: str) -> bool:
    """reg.redsara.es en cualquier ruta que no sea /login ni transitoria."""
    return _HOST_REG in u and not _is_login(u) and not _is_transient(u)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _goto_robust(page: Page, url: str, *, ms: int, retries: int = 3) -> None:
    """page.goto tolerante a ERR_ABORTED transitorios (típico del callback SAML)."""
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=ms)
            return
        except Exception as exc:
            last_exc = exc
            if "ERR_ABORTED" in str(exc) and attempt < retries:
                await page.wait_for_timeout(1_200 * attempt)
                continue
            raise
    if last_exc:
        raise last_exc


async def _has_token(page: Page) -> bool:
    """Comprobación RÁPIDA (sin timeout) de si access_token está en localStorage."""
    try:
        return bool(await page.evaluate("() => !!window.localStorage.getItem('access_token')"))
    except Exception:
        return False


async def _wait_token(page: Page, ms: int) -> bool:
    """Espera hasta ms ms a que access_token aparezca (tras callback SAML)."""
    try:
        await page.wait_for_function(
            "() => !!window.localStorage.getItem('access_token')",
            timeout=ms,
        )
        return True
    except PlaywrightTimeoutError:
        logger.warning("access_token no apareció en %dms", ms)
        return False


async def _click_robust(page: Page, selector: str, description: str, timeout_ms: int) -> bool:
    """
    Click en el primer elemento que coincide con selector.
    Intento 1: Playwright locator.click() (click real a nivel de navegador).
    Intento 2: JS dispatchEvent shadow-piercing (fallback para web components).
    """
    locator = page.locator(selector).first
    try:
        await locator.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logger.debug("%s — no visible en %dms [%s]", description, timeout_ms, selector)
        return False

    await locator.scroll_into_view_if_needed()
    await page.wait_for_timeout(150)

    # Intento 1: click nativo
    try:
        await locator.click(timeout=5_000)
        logger.debug("%s — click nativo OK", description)
        return True
    except Exception as exc:
        logger.debug("%s — click nativo falló (%s); probando JS pierce", description, exc)

    # Intento 2: JS pierce al inner button/a del shadow root
    # querySelector no admite listas con coma; usamos sólo el primer selector.
    sel_simple = selector.split(",")[0].strip()
    clicked: bool = await page.evaluate(
        """(sel) => {
            const host = document.querySelector(sel);
            if (!host) return false;
            const shadow = host.shadowRoot;
            const inner  = shadow && (shadow.querySelector('button') || shadow.querySelector('a'));
            (inner || host).dispatchEvent(
                new MouseEvent('click', { bubbles: true, composed: true, cancelable: true })
            );
            return true;
        }""",
        sel_simple,
    )
    if clicked:
        logger.debug("%s — JS pierce OK [%s]", description, sel_simple)
    return clicked


# ── Flujo principal ───────────────────────────────────────────────────────────

async def ejecutar_login_redsara(page: Page, config: RedsaraConfig) -> Page:
    """
    Login REDSARA basado en URL-state y token de localStorage.

    El certificado TLS se inyecta automáticamente por el contexto del navegador
    (configurado en base_automation.py). Este flujo sólo gestiona la secuencia
    de navegación y clics hasta llegar a /nuevo-registro.
    """
    nav_ms  = config.flow_timeouts.navigation_timeout_ms
    auth_ms = config.flow_timeouts.auth_wait_ms

    logger.info("Iniciando login REDSARA → %s", config.url_base)
    await _goto_robust(page, config.url_base, ms=nav_ms)

    for step in range(25):
        url = page.url or ""
        logger.info("[login %02d] %s", step, url)

        # ── DESTINO ALCANZADO ─────────────────────────────────────────────────
        if _is_nuevo(url):
            break

        # ── SAML callbacks y URLs transitorias ────────────────────────────────
        # reg-api.redsara.es, /signOk, /signKo, /loginKo, /login/callback
        # Angular y reg-api se encargan del redirect; sólo esperamos.
        if _is_transient(url):
            logger.debug("URL transitoria — esperando redirect automático")
            try:
                await page.wait_for_url(
                    lambda u: not _is_transient(str(u)), timeout=nav_ms
                )
            except PlaywrightTimeoutError:
                pass
            await page.wait_for_timeout(300)
            continue

        # ── /es/login ─────────────────────────────────────────────────────────
        if _is_login(url):
            logger.info("/login — click en dnt-vertical-card dnt-button")
            ok = await _click_robust(page, _SEL_LOGIN_BTN, "login button", 10_000)
            if not ok:
                # A veces el modal aparece aquí también
                ok = await _click_robust(page, _SEL_MODAL_BTN, "modal button (/login)", 3_000)
            if not ok:
                logger.warning("Botón de login no encontrado en /login; reintentando en 2s")
                await page.wait_for_timeout(2_000)
                continue
            try:
                await page.wait_for_url(lambda u: not _is_login(str(u)), timeout=nav_ms)
            except PlaywrightTimeoutError:
                pass
            await page.wait_for_timeout(300)
            continue

        # ── Pasarela Cl@ve — selección de IdP ────────────────────────────────
        # Click en AFIRMA: el browser context inyecta el certificado TLS automáticamente.
        if _is_clave_idp(url):
            logger.info("Cl@ve gateway — click AFIRMA (button.idp-button[onclick*='AFIRMA'])")
            ok = await _click_robust(page, _SEL_AFIRMA, "AFIRMA button", 10_000)
            if not ok:
                logger.warning("Botón AFIRMA no encontrado; reintentando en 2s")
                await page.wait_for_timeout(2_000)
                continue
            # El certificado se inyecta sólo; esperamos la salida de pasarela.
            logger.info("AFIRMA pulsado — esperando salida de pasarela (cert injection automática)")
            try:
                await page.wait_for_url(lambda u: not _is_clave(str(u)), timeout=auth_ms)
            except PlaywrightTimeoutError:
                pass
            await page.wait_for_timeout(500)
            continue

        # ── Pasarela Cl@ve — error u otra ruta ───────────────────────────────
        if _is_clave(url):
            logger.warning("Cl@ve en URL inesperada (%s) — reiniciando", url)
            await _goto_robust(page, config.url_base, ms=nav_ms)
            await page.wait_for_timeout(500)
            continue

        # ── reg.redsara.es — cualquier ruta autenticada o home ───────────────
        # Cubre: /es/, /es/mis-registros, /es/mi-perfil, etc.
        if _is_reg_home(url):
            if await _has_token(page):
                # ✅ Sesión activa: navegar directamente a nuevo-registro.
                # Con token en localStorage, goto() funciona sin que el route guard redirija.
                logger.info("Token en localStorage — goto /nuevo-registro")
                await _goto_robust(page, config.url_nuevo_registro, ms=nav_ms)
            else:
                # ❌ Sin token: no autenticado.
                # _goto /login le fuerza a pasar por la pantalla de login
                # (dnt-vertical-card dnt-button) desde donde empieza el flujo Cl@ve/AFIRMA.
                logger.info("Sin token en home — goto /login para iniciar autenticación")
                await _goto_robust(page, config.url_base + "login", ms=nav_ms)
            await page.wait_for_timeout(300)
            continue

        # ── URL completamente desconocida ─────────────────────────────────────
        logger.warning("URL no reconocida en step %d: %s", step, url)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        await page.wait_for_timeout(1_000)

    else:
        raise RuntimeError(
            f"Login REDSARA no completado en 25 pasos. URL final: {page.url}"
        )

    # ── Verificación final: step 1 visible ────────────────────────────────────
    await page.wait_for_url(
        re.compile(r".*/nuevo-registro.*", re.IGNORECASE), timeout=nav_ms
    )
    await page.locator(config.selectors.step1_heading).first.wait_for(
        state="visible", timeout=auth_ms,
    )
    logger.info("Login REDSARA completado ✓  URL: %s", page.url)
    return page