"""
Flujo de rellenado del formulario de Madrid.
Implementa las secciones documentadas en explore-html/llenar formulario-madrid.md
"""

from __future__ import annotations

import logging
import random
import re
import time
import unicodedata
from typing import TYPE_CHECKING

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig
    from sites.madrid.data_models import MadridFormData

from sites.madrid.data_models import TipoExpediente, NaturalezaEscrito, TipoDocumento

logger = logging.getLogger(__name__)

# Delays entre inputs
# Madrid es lenta: meter "calma" extra tras cada interacción.
DELAY_ENTRE_CAMPOS_MIN = 1500  # 1.5s (0.5s base + ~1s extra)
DELAY_ENTRE_CAMPOS_MAX = 1500  # 1.5s
DELAY_DESPUES_SELECT = 1500    # 1.5s

ACTION_TIMEOUT_MS = 5000


class MadridFormularioAccessDenied(RuntimeError):
    """Bloqueo Akamai detectado durante una transicion necesaria del formulario."""


async def _delay_humano(page: Page, min_ms: int = DELAY_ENTRE_CAMPOS_MIN, max_ms: int = DELAY_ENTRE_CAMPOS_MAX) -> None:
    """Añade un pequeño delay aleatorio para simular comportamiento humano."""
    delay = random.randint(min_ms, max_ms)
    await page.wait_for_timeout(delay)


async def _rellenar_input(page: Page, selector: str, valor: str, nombre_campo: str = "") -> bool:
    """
    Rellena un input de texto si el valor no está vacío.
    Incluye un pequeño delay para parecer más humano.
    
    Returns:
        True si se rellenó, False si estaba vacío o no se encontró
    """
    if not valor:
        return False
    
    try:
        elemento = page.locator(selector)
        if await elemento.count() > 0:
            # Verificar si está habilitado
            is_disabled = await elemento.first.is_disabled()
            if is_disabled:
                logger.debug(f"  -> Campo {nombre_campo or selector} deshabilitado, saltando")
                return False
            
            await elemento.first.fill(valor, timeout=ACTION_TIMEOUT_MS)
            logger.debug(f"  -> {nombre_campo or selector}: {valor}")
            
            # Pequeño delay después de rellenar
            await _delay_humano(page)
            return True
    except Exception as e:
        logger.warning(f"  -> Error rellenando {nombre_campo or selector}: {e}")
    
    return False


async def _rellenar_y_validar_text_area(page: Page, selector: str, valor: str, nombre_campo: str = "") -> bool:
    """
    Rellena un textarea y valida que el contenido sea el esperado.
    Si no coincide, reintenta con un método más lento (type).
    """
    if not valor:
        return False
    
    try:
        elemento = page.locator(selector).first
        if await elemento.count() == 0:
            return False
        
        # Asegurar visibilidad
        await elemento.scroll_into_view_if_needed()
        await elemento.wait_for(state="visible", timeout=2000)

        # Limpiar y rellenar inicial
        await elemento.click()
        await elemento.fill(valor)
        
        # Delay para que el DOM se asiente antes de validar
        await page.wait_for_timeout(300)
        
        # Validar
        valor_actual = await elemento.input_value()
        if valor_actual.strip() == valor.strip():
            logger.debug(f"  OK {nombre_campo or selector} validado correctamente")
            await _delay_humano(page)
            return True
        
        # Reintento si no coincide: limpiar y usar type
        logger.warning(f"  WARN {nombre_campo or selector} no coincide. Reintentando con 'type'...")
        await elemento.click()
        await elemento.press("Control+A")
        await elemento.press("Backspace")
        await elemento.type(valor, delay=20)
        
        await page.wait_for_timeout(500)
        valor_actual = await elemento.input_value()
        
        if valor_actual.strip() == valor.strip():
            logger.info(f"  OK {nombre_campo or selector} validado tras reintento")
            await _delay_humano(page)
            return True
        else:
            logger.error(f"  X Error: {nombre_campo or selector} no pudo ser validado (Actual: {len(valor_actual)}, Esperado: {len(valor)})")
            return False

    except Exception as e:
        logger.warning(f"  -> Error rellenando/validando {nombre_campo or selector}: {e}")
        return False


def _normalizar_texto_autocomplete(texto: str) -> str:
    if texto is None:
        return ""

    # Normalizamos a NFD para separar los acentos de las letras.
    # Pero queremos mantener la Ñ/ñ. En NFD, la Ñ se convierte en N + ~ (combinada).
    texto = unicodedata.normalize("NFD", texto)
    
    # Eliminamos marcadores de acentuación EXCEPTO para la Ñ si es posible,
    # o más fácil: reconstruimos el texto saltando solo Mn que no sigan a N/n 
    # (aunque técnicamente queremos todas las tildes fuera excepto la de la Ñ).
    # Una forma más sencilla y segura para este caso:
    resultado = []
    for i, ch in enumerate(texto):
        if unicodedata.category(ch) != "Mn":
            resultado.append(ch)
        else:
            # Si es una tilde combinada (U+0303), y el carácter anterior era N o n, lo mantenemos
            # para que al normalizar de vuelta a NFC se convierta en Ñ/ñ.
            if ch == "\u0303" and i > 0 and texto[i-1].upper() == "N":
                resultado.append(ch)
    
    texto = "".join(resultado)
    # Volvemos a NFC para recomponer la Ñ
    texto = unicodedata.normalize("NFC", texto)
    
    texto = texto.upper()
    # Permitimos la Ñ en el regex
    texto = re.sub(r"[^A-Z0-9Ñ ]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _extraer_ultima_sugerencia_aria_live(texto_aria: str) -> str | None:
    """
    jQuery UI Autocomplete anuncia sugerencias por un aria-live region (role=status)
    con mensajes del tipo:
      - "2 results are available, use up and down arrow keys to navigate."
      - "No search results."
      - "ABARDERO  [CALLE]"

    Devuelve la última "sugerencia" anunciada (no los mensajes informativos).
    """

    if not texto_aria:
        return None

    lineas = [ln.strip() for ln in texto_aria.splitlines() if ln.strip()]
    if not lineas:
        return None

    for ln in reversed(lineas):
        low = ln.lower()
        if "results are available" in low:
            continue
        if "result is available" in low:
            continue
        if "no search results" in low:
            continue
        if "use up and down arrow keys" in low:
            continue
        return ln

    return None


async def _leer_sugerencia_actual_aria_live(page: Page) -> str | None:
    loc = page.locator("span.ui-helper-hidden-accessible[role='status']")
    try:
        if await loc.count() == 0:
            return None
        # `text_content` incluye nodos con display:none; `inner_text` no.
        texto = await loc.first.text_content(timeout=500)
    except Exception:
        return None

    return _extraer_ultima_sugerencia_aria_live(texto or "")


async def _esperar_autocomplete_listo(page: Page, selector: str, timeout_ms: int = 5000) -> None:
    """
    Espera a que el input termine de cargar sugerencias.

    En WFORS se observa la clase `ui-autocomplete-loading` mientras hace la llamada a BDC.
    """

    loc = page.locator(selector).first
    deadline = time.monotonic() + (timeout_ms / 1000.0)

    while True:
        try:
            class_attr = (await loc.get_attribute("class")) or ""
        except Exception:
            class_attr = ""

        if "ui-autocomplete-loading" not in class_attr:
            return

        if time.monotonic() > deadline:
            return

        await page.wait_for_timeout(100)


async def _esperar_items_autocomplete(page: Page, timeout_ms: int = 5000) -> None:
    items = page.locator("ul.ui-autocomplete li.ui-menu-item")
    deadline = time.monotonic() + (timeout_ms / 1000.0)

    while True:
        try:
            if await items.count() > 0:
                return
        except Exception:
            pass

        if time.monotonic() > deadline:
            return

        await page.wait_for_timeout(100)


async def _detectar_access_denied_formulario(page: Page) -> bool:
    """Detecta la pagina de bloqueo de Akamai sin exponer datos sensibles."""

    try:
        url = page.url.lower()
        if "errors.edgesuite.net" in url or "access denied" in url:
            return True
    except Exception:
        pass

    try:
        texto = (await page.locator("body").inner_text(timeout=1000)).lower()
        return "access denied" in texto or "you don't have permission to access" in texto
    except Exception:
        return False


def _score_sugerencia_autocomplete(
    texto: str,
    valor_introducido: str,
    tipo_via_preferida: str | None = None,
) -> int:
    objetivo = _normalizar_texto_autocomplete(valor_introducido)
    tipo_norm = _normalizar_texto_autocomplete(tipo_via_preferida or "")
    tnorm = _normalizar_texto_autocomplete(texto)

    score = 0
    if objetivo and objetivo in tnorm:
        score += 20

    objetivo_tokens = [t for t in objetivo.split(" ") if t]
    if objetivo_tokens:
        score += sum(2 for tok in objetivo_tokens if tok in tnorm)

    if tipo_norm:
        if f"[{tipo_norm}]" in tnorm:
            score += 10
        elif tipo_norm in tnorm:
            score += 2

    return score - int(len(tnorm) / 20)


async def _click_sugerencia_autocomplete(items, indice: int) -> None:
    target = items.nth(indice)
    wrapper = target.locator(":scope >> *").first
    if await wrapper.count() > 0:
        await wrapper.click(timeout=1500)
    else:
        await target.click(timeout=1500)


async def _seleccionar_sugerencia_jquery_ui_click_only(
    page: Page,
    valor_introducido: str,
    nombre_campo: str = "",
    sugerencia_objetivo: str | None = None,
    tipo_via_preferida: str | None = None,
    timeout_ms: int = 2500,
) -> bool:
    menu = page.locator("ul.ui-autocomplete")
    try:
        await menu.first.wait_for(state="attached", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logger.warning(f"  -> Autocomplete {nombre_campo or valor_introducido}: no aparecio menu")
        return False

    items = page.locator("ul.ui-autocomplete:visible li.ui-menu-item:visible")
    try:
        await items.first.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logger.warning(f"  -> Autocomplete {nombre_campo or valor_introducido}: sin sugerencias visibles")
        return False

    try:
        textos = [t.strip() for t in await items.all_text_contents() if t and t.strip()]
    except Exception:
        textos = []

    if not textos:
        logger.warning(f"  -> Autocomplete {nombre_campo or valor_introducido}: sugerencias vacias")
        return False

    indice = -1
    if sugerencia_objetivo:
        objetivo_norm = _normalizar_texto_autocomplete(sugerencia_objetivo)
        for idx, texto in enumerate(textos):
            if _normalizar_texto_autocomplete(texto) == objetivo_norm:
                indice = idx
                break

        if indice < 0:
            logger.warning(
                f"  -> Autocomplete {nombre_campo or valor_introducido}: "
                f"no se encontro sugerencia objetivo={sugerencia_objetivo!r} opciones={textos[:5]!r}"
            )
            return False
    else:
        indice = max(
            range(len(textos)),
            key=lambda idx: _score_sugerencia_autocomplete(textos[idx], valor_introducido, tipo_via_preferida),
        )

    try:
        await _click_sugerencia_autocomplete(items, indice)
        try:
            await menu.first.wait_for(state="hidden", timeout=1500)
        except PlaywrightTimeoutError:
            pass
        await _delay_humano(page, 150, 300)
        return True
    except Exception as e:
        logger.warning(f"  -> No se pudo clickar sugerencia en {nombre_campo or 'autocomplete'}: {e}")
        return False


async def _seleccionar_sugerencia_jquery_ui(
    page: Page,
    valor_introducido: str,
    nombre_campo: str = "",
    sugerencia_objetivo: str | None = None,
    tipo_via_preferida: str | None = None,
    timeout_ms: int = 2500,
) -> bool:
    return await _seleccionar_sugerencia_jquery_ui_click_only(
        page,
        valor_introducido,
        nombre_campo=nombre_campo,
        sugerencia_objetivo=sugerencia_objetivo,
        tipo_via_preferida=tipo_via_preferida,
        timeout_ms=timeout_ms,
    )

async def _validar_campo_sin_error(
    page: Page,
    selector: str,
    nombre_campo: str = "",
    timeout_ms: int = 3500,
) -> None:
    """
    Valida que el campo no muestre error (p.ej. 'La calle introducida no es correcta').

    En los HTML de WFORS suele aparecer un `span.textoError` dentro del `label.wrapper`.
    """

    input_loc = page.locator(selector).first
    label_loc = input_loc.locator("xpath=ancestor::label[1]")
    error_loc = label_loc.locator("span.textoError")

    # Esperar una ventana breve para que el backend pinte el error si aplica.
    try:
        await error_loc.first.wait_for(state="visible", timeout=timeout_ms)
        msg = (await error_loc.first.inner_text()).strip()
    except PlaywrightTimeoutError:
        msg = ""

    # Si no se ve span.textoError, aún puede quedar la clase "error" en el input.
    class_attr = (await input_loc.get_attribute("class")) or ""
    tiene_error_class = " error " in f" {class_attr} "

    if msg or tiene_error_class:
        raise ValueError(f"Validación fallida en {nombre_campo or selector}: {msg or 'campo marcado con error'}")


async def _rellenar_input_con_autocomplete(
    page: Page,
    selector: str,
    valor: str,
    nombre_campo: str = "",
    validar_sin_error: bool = True,
    sugerencia_objetivo: str | None = None,
    tipo_via_preferida: str | None = None,
) -> bool:
    """
    Rellena un input y, si aparece, selecciona una sugerencia del autocomplete.

    Esto es clave para campos como NOMBREVIA donde el sistema valida contra BBDD.
    """

    if not valor:
        return False

    try:
        elemento = page.locator(selector)
        if await elemento.count() == 0:
            return False

        if await elemento.first.is_disabled():
            logger.debug(f"  -> Campo {nombre_campo or selector} deshabilitado, saltando")
            return False

        await elemento.first.click(timeout=2000)
        await elemento.first.press("Control+A")
        # Es importante "teclear" (no solo fill) para disparar keyup/keydown + debounce (bindWithDelay).
        await elemento.first.type(valor, delay=80)

        # Esperar a que el widget termine la llamada (ui-autocomplete-loading) y se rellenen items.
        await _esperar_autocomplete_listo(page, selector, timeout_ms=5000)
        await _esperar_items_autocomplete(page, timeout_ms=5000)

        seleccionado = await _seleccionar_sugerencia_jquery_ui(
            page,
            valor,
            nombre_campo=nombre_campo,
            sugerencia_objetivo=sugerencia_objetivo,
            tipo_via_preferida=tipo_via_preferida,
        )

        if sugerencia_objetivo and validar_sin_error and not seleccionado:
            raise ValueError(f"{nombre_campo}: no apareció/autoseleccionó el desplegable de sugerencias")

        if await _detectar_access_denied_formulario(page):
            raise RuntimeError(f"Madrid autocomplete {nombre_campo or selector}: Access Denied tras seleccionar sugerencia")

        await _delay_humano(page, 300, 500)

        if await _detectar_access_denied_formulario(page):
            raise RuntimeError(f"Madrid autocomplete {nombre_campo or selector}: Access Denied tras estabilizar campo")

        if validar_sin_error:
            await _validar_campo_sin_error(page, selector, nombre_campo=nombre_campo)

        return seleccionado
    except RuntimeError as e:
        logger.error(f"  -> Error critico rellenando (autocomplete) {nombre_campo or selector}: {e}")
        raise
    except Exception as e:
        logger.warning(f"  -> Error rellenando (autocomplete) {nombre_campo or selector}: {e}")
        return False


def _texto_busqueda_nombre_via(nombre_via: str, tipo_via: str | None, quitar_preposiciones: bool = False) -> str:
    """
    Texto para teclear en el input y abrir sugerencias.
    Si quitar_preposiciones es True, elimina partículas comunes al inicio 
    (DE, DEL, LA, EL, LOS, LAS) para facilitar el match del autocomplete.
    """
    res = _normalizar_texto_autocomplete(nombre_via)
    if quitar_preposiciones and res:
        # Lista de preposiciones/artículos a omitir en la búsqueda
        particulas = ["DE ", "DEL ", "LA ", "EL ", "LOS ", "LAS "]
        for p in particulas:
            if res.startswith(p):
                res = res[len(p):].strip()
                break
    return res


async def _rellenar_nombre_via_validado(
    page: Page,
    config: "MadridConfig",
    selector: str,
    valor_humano: str,
    *,
    tipo_via: str | None,
    nombre_campo: str,
    strict: bool,
    quitar_preposiciones: bool = False,
) -> bool:
    """
    Rellena NOMBREVIA tecleando y seleccionando desde el autocomplete UI.
    """

    if not valor_humano:
        return False

    validar_sin_error = strict

    valor_tecleo = _texto_busqueda_nombre_via(valor_humano, tipo_via, quitar_preposiciones) or valor_humano

    logger.debug(f"[UI] {nombre_campo}: raw='{valor_humano}' tipo_via='{tipo_via or ''}' tecleo='{valor_tecleo}'")

    ok = await _rellenar_input_con_autocomplete(
        page,
        selector,
        valor_tecleo,
        nombre_campo,
        validar_sin_error=validar_sin_error,
        tipo_via_preferida=tipo_via,
    )

    return ok


async def _seleccionar_opcion(page: Page, selector: str, valor: str, nombre_campo: str = "") -> bool:
    """
    Selecciona una opción en un select si el valor no está vacío.
    Intenta primero por label, luego por value.
    Incluye delay para parecer más humano.
    """
    if not valor:
        return False
    
    try:
        elemento = page.locator(selector)
        if await elemento.count() > 0:
            is_disabled = await elemento.first.is_disabled()
            if is_disabled:
                logger.debug(f"  -> Select {nombre_campo or selector} deshabilitado, saltando")
                return False

            try:
                estado = await elemento.first.evaluate(
                    """el => {
                        const opt = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
                        return { value: el.value || "", label: opt ? (opt.textContent || "") : "" };
                    }"""
                )
                valor_actual = str(estado.get("value") or "").strip()
                label_actual = str(estado.get("label") or "").strip()
                valor_esperado = str(valor or "").strip()
                if (
                    valor_actual == valor_esperado
                    or _normalizar_texto_autocomplete(label_actual) == _normalizar_texto_autocomplete(valor_esperado)
                ):
                    logger.debug(f"  -> {nombre_campo or selector}: ya seleccionado, no se fuerza change")
                    return True
            except Exception:
                pass
            
            # Intentar primero por label
            try:
                await elemento.first.select_option(label=valor, timeout=ACTION_TIMEOUT_MS)
                logger.debug(f"  -> {nombre_campo or selector}: {valor} (por label)")
                await _delay_humano(page, DELAY_DESPUES_SELECT, DELAY_DESPUES_SELECT + 200)
                return True
            except:
                # Si falla, intentar por value
                try:
                    await elemento.first.select_option(value=valor, timeout=ACTION_TIMEOUT_MS)
                    logger.debug(f"  -> {nombre_campo or selector}: {valor} (por value)")
                    await _delay_humano(page, DELAY_DESPUES_SELECT, DELAY_DESPUES_SELECT + 200)
                    return True
                except:
                    # Si ambos fallan, intentar por index si es numérico
                    if valor.isdigit():
                        await elemento.first.select_option(index=int(valor), timeout=ACTION_TIMEOUT_MS)
                        logger.debug(f"  -> {nombre_campo or selector}: opcion {valor} (por index)")
                        await _delay_humano(page, DELAY_DESPUES_SELECT, DELAY_DESPUES_SELECT + 200)
                        return True
                    raise
    except Exception as e:
        logger.warning(f"  -> Error seleccionando {nombre_campo or selector}: {e}")
    
    return False


async def _marcar_checkbox(page: Page, selector: str, marcar: bool, nombre_campo: str = "") -> bool:
    """
    Marca o desmarca un checkbox.
    Incluye delay para parecer más humano.
    """
    try:
        elemento = page.locator(selector)
        if await elemento.count() > 0:
            is_disabled = await elemento.first.is_disabled()
            if is_disabled:
                logger.debug(f"  -> Checkbox {nombre_campo or selector} deshabilitado, saltando")
                return False
            
            is_checked = await elemento.first.is_checked()
            if marcar and not is_checked:
                await elemento.first.check(timeout=ACTION_TIMEOUT_MS)
                logger.debug(f"  -> {nombre_campo or selector}: marcado")
                await _delay_humano(page)
            elif not marcar and is_checked:
                await elemento.first.uncheck(timeout=ACTION_TIMEOUT_MS)
                logger.debug(f"  -> {nombre_campo or selector}: desmarcado")
                await _delay_humano(page)
            return True
    except Exception as e:
        logger.warning(f"  -> Error con checkbox {nombre_campo or selector}: {e}")
    
    return False


async def _click_radio(page: Page, selector: str, nombre_campo: str = "") -> bool:
    """
    Hace click en un radio button.
    Incluye delay para parecer más humano.
    """
    try:
        elemento = page.locator(selector)
        if await elemento.count() > 0:
            await elemento.first.click(timeout=ACTION_TIMEOUT_MS)
            logger.debug(f"  -> Radio {nombre_campo or selector}: seleccionado")
            await _delay_humano(page)
            return True
    except Exception as e:
        logger.warning(f"  -> Error con radio {nombre_campo or selector}: {e}")
    
    return False


async def _esperar_actualizacion_dom(page: Page, timeout_ms: int = 1000) -> None:
    """
    Espera a que el DOM se actualice después de un cambio que dispara refresh.
    """
    await page.wait_for_timeout(timeout_ms)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=3000)
    except PlaywrightTimeoutError:
        pass


async def _resumir_boton_submit_final(page: Page, selector: str) -> dict:
    boton = page.locator(selector).first
    try:
        return await boton.evaluate(
            """el => ({
                tag: el.tagName,
                id: el.id || "",
                name: el.getAttribute("name") || "",
                type: el.getAttribute("type") || "",
                value: el.getAttribute("value") || "",
                disabled: !!el.disabled,
                onclick: el.getAttribute("onclick") || "",
                form_id: el.form ? (el.form.id || "") : "",
                form_action: el.form ? (el.form.action || "") : "",
                form_method: el.form ? (el.form.method || "") : "",
            })"""
        )
    except Exception as exc:
        return {"error": repr(exc)}


async def _esperar_formulario_estable_antes_submit(page: Page, config: "MadridConfig") -> None:
    if await _detectar_access_denied_formulario(page):
        raise MadridFormularioAccessDenied("Madrid formulario: Access Denied antes de pulsar Continuar")

    await page.wait_for_selector(config.continuar_formulario_selector, state="visible", timeout=config.default_timeout)
    boton = page.locator(config.continuar_formulario_selector).first
    await boton.scroll_into_view_if_needed()

    try:
        await page.locator(".ui-autocomplete-loading").first.wait_for(state="hidden", timeout=2500)
    except PlaywrightTimeoutError:
        pass

    try:
        await page.locator("ul.ui-autocomplete:visible").first.wait_for(state="hidden", timeout=1500)
    except PlaywrightTimeoutError:
        pass

    if await boton.is_disabled():
        raise RuntimeError("Madrid formulario: boton Continuar visible pero deshabilitado antes del submit final")

    page_state = await page.evaluate(
        """() => {
            const form = document.querySelector("form");
            return {
                href: document.location.href,
                form_action: form ? form.action : "",
                form_method: form ? form.method : "",
                visible_autocomplete: !!document.querySelector("ul.ui-autocomplete:not([style*='display: none'])"),
                loading_autocomplete: !!document.querySelector(".ui-autocomplete-loading"),
            };
        }"""
    )
    logger.info(
        "Madrid formulario pre-submit estable href=%s action=%s method=%s autocomplete_visible=%s loading=%s",
        page_state.get("href"),
        page_state.get("form_action"),
        page_state.get("form_method"),
        page_state.get("visible_autocomplete"),
        page_state.get("loading_autocomplete"),
    )

    if "WFORS_WBWFORS/servlet" not in str(page_state.get("form_action") or ""):
        raise RuntimeError(f"Madrid formulario: action inesperado antes de Continuar: {page_state.get('form_action')}")


async def _click_continuar_formulario_una_vez(page: Page, config: "MadridConfig", *, intento: int) -> Page:
    selector = config.continuar_formulario_selector
    boton = page.locator(selector).first
    resumen = await _resumir_boton_submit_final(page, selector)
    logger.info("Madrid formulario Continuar intento=%s boton=%s url=%s", intento, resumen, page.url)

    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
            await boton.click(timeout=ACTION_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        logger.warning("Madrid formulario Continuar intento=%s sin navegacion completa dentro del timeout", intento)

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PlaywrightTimeoutError:
        pass

    await page.wait_for_timeout(1500)
    if await _detectar_access_denied_formulario(page):
        raise MadridFormularioAccessDenied(f"Madrid formulario: Access Denied tras Continuar intento={intento}")

    logger.info("Madrid formulario Continuar intento=%s completado url=%s", intento, page.url)
    return page


async def _continuar_formulario_controlado(page: Page, config: "MadridConfig") -> Page:
    await _esperar_formulario_estable_antes_submit(page, config)
    return await _click_continuar_formulario_una_vez(page, config, intento=1)

async def ejecutar_formulario_madrid(
    page: Page, 
    config: MadridConfig, 
    datos: MadridFormData
) -> Page:
    """
    Rellena el formulario de multas de circulación de Madrid.
    
    Secciones implementadas:
    1. Datos del expediente (referencia + formato)
    2. Matrícula del vehículo
    3. Datos del interesado
    4. Datos del representante
    5. Datos de notificación
    6. Naturaleza del escrito
    7. Expone y Solicita
    8. Click en Continuar
    
    Args:
        page: Página de Playwright (ya en el formulario)
        config: Configuración con selectores
        datos: Datos a rellenar
        
    Returns:
        Page: Página después de pulsar Continuar
    """
    
    # Seguridad: no empezar a rellenar si no estamos realmente en la pantalla del formulario
    if getattr(config, "url_servcla_formulario_contains", None) and config.url_servcla_formulario_contains not in page.url:
        logger.warning(f"No parece la URL del formulario (action=opcion). URL actual: {page.url}")
        try:
            await page.wait_for_url(
                re.compile(r".*WFORS_WBWFORS/servlet\\?action=opcion.*", re.IGNORECASE),
                timeout=config.navigation_timeout,
            )
        except PlaywrightTimeoutError:
            pass

    await page.wait_for_selector(config.expediente_tipo_1_selector, state="attached", timeout=config.default_timeout)

    logger.info("=" * 80)
    logger.info("FASE 2: RELLENANDO FORMULARIO DE MULTAS")
    logger.info("=" * 80)
    
    # =========================================================================
    # SECCIÓN 1: Datos del expediente
    # =========================================================================
    logger.info("SECCION 1: Datos del expediente")
    
    exp = datos.expediente
    
    if exp.tipo == TipoExpediente.OPCION1:
        # Seleccionar opción 1 (NNN/EEEEEEEEE.D)
        await _click_radio(page, config.expediente_tipo_1_selector, "Tipo expediente opción 1")
        await _esperar_actualizacion_dom(page, 1000)
        
        # Rellenar campos
        await _rellenar_input(page, config.expediente_1_nnn_selector, exp.nnn, "NNN")
        await _rellenar_input(page, config.expediente_1_exp_selector, exp.eeeeeeeee, "EEEEEEEEE")
        await _rellenar_input(page, config.expediente_1_d_selector, exp.d, "D")
        logger.info(f"  -> Expediente formato 1: {exp.nnn}/{exp.eeeeeeeee}.{exp.d}")
        
    else:
        # Seleccionar opción 2 (LLL/AAAA/EEEEEEEEE)
        await _click_radio(page, config.expediente_tipo_2_selector, "Tipo expediente opción 2")
        await _esperar_actualizacion_dom(page, 1000)
        
        # Rellenar campos
        await _rellenar_input(page, config.expediente_2_lll_selector, exp.lll, "LLL")
        await _rellenar_input(page, config.expediente_2_aaaa_selector, exp.aaaa, "AAAA")
        await _rellenar_input(page, config.expediente_2_exp_selector, exp.exp_num, "EEEEEEEEE")
        logger.info(f"  -> Expediente formato 2: {exp.lll}/{exp.aaaa}/{exp.exp_num}")
    
    # =========================================================================
    # SECCIÓN 2: Matrícula del vehículo
    # =========================================================================
    logger.info("SECCION 2: Matricula del vehiculo")
    
    await _rellenar_input(page, config.matricula_selector, datos.matricula, "Matrícula")
    logger.info(f"  -> Matricula: {datos.matricula}")
    
    # =========================================================================
    # SECCIÓN 3: Datos del interesado
    # =========================================================================
    logger.info("SECCION 3: Datos del interesado")
    
    inter = datos.interesado
    
    # Teléfono (editable)
    await _rellenar_input(page, config.interesado_telefono_selector, inter.telefono, "Teléfono interesado")
    
    # Checkboxes de confirmación
    await _marcar_checkbox(page, config.interesado_check_email_selector, inter.confirmar_email, "Email interesado")
    await _marcar_checkbox(page, config.interesado_check_sms_selector, inter.confirmar_sms, "SMS interesado")
    
    logger.info(f"  -> Telefono: {inter.telefono or '(no modificado)'}")
    logger.info(f"  -> Confirmar email: {inter.confirmar_email}, SMS: {inter.confirmar_sms}")
    
    # =========================================================================
    # SECCIÓN 4: Datos del representante
    # =========================================================================
    logger.info("SECCION 4: Datos del representante")
    
    rep = datos.representante
    rep_dir = rep.direccion
    rep_con = rep.contacto
    
    # Dirección (solo campos editables)
    await _rellenar_input(page, config.representante_municipio_selector, rep_dir.municipio, "Municipio rep.")
    await _seleccionar_opcion(page, config.representante_tipo_via_selector, rep_dir.tipo_via, "Tipo vía rep.")
    await _rellenar_nombre_via_validado(
        page,
        config,
        config.representante_nombre_via_selector,
        rep_dir.nombre_via,
        tipo_via=rep_dir.tipo_via,
        nombre_campo="Nombre vía rep.",
        strict=False,
        quitar_preposiciones=False, # Representante usa texto completo
    )
    await _seleccionar_opcion(page, config.representante_tipo_num_selector, rep_dir.tipo_numeracion, "Tipo num. rep.")
    await _rellenar_input(page, config.representante_numero_selector, rep_dir.numero, "Número rep.")
    await _rellenar_input(page, config.representante_portal_selector, rep_dir.portal, "Portal rep.")
    await _rellenar_input(page, config.representante_escalera_selector, rep_dir.escalera, "Escalera rep.")
    await _rellenar_input(page, config.representante_planta_selector, rep_dir.planta, "Planta rep.")
    await _rellenar_input(page, config.representante_puerta_selector, rep_dir.puerta, "Puerta rep.")
    await _rellenar_input(page, config.representante_codpostal_selector, rep_dir.codigo_postal, "C.P. rep.")
    await _seleccionar_opcion(page, config.representante_provincia_selector, rep_dir.provincia, "Provincia rep.")
    await _seleccionar_opcion(page, config.representante_pais_selector, rep_dir.pais, "País rep.")
    
    # Contacto
    await _rellenar_input(page, config.representante_email_selector, rep_con.email, "Email rep.")
    
    # Teléfono rep.
    await _rellenar_input(page, config.representante_telefono_selector, rep_con.telefono, "Teléfono rep.")
    
    # Checkbox de confirmación (evita escribir en checkboxes homónimos fuera de _id21:3)
    await _marcar_checkbox(
        page,
        config.representante_check_email_selector,
        bool(rep_con.email),
        "Confirmar email rep.",
    )
    
    logger.info(f"  -> Direccion: {rep_dir.nombre_via or '(vacio)'}, {rep_dir.municipio or '(vacio)'}")
    logger.info(f"  -> Contacto: {rep_con.email or '(vacio)'}")
    
    # =========================================================================
    # SECCIÓN 5: Datos de notificación
    # =========================================================================
    logger.info("SECCION 5: Datos de notificacion")
    
    notif = datos.notificacion
    
    # Opción de copiar datos
    if notif.copiar_desde == "interesado":
        logger.info("  -> Copiando datos del interesado...")
        await page.click(config.notificacion_copiar_interesado_selector)
        await _esperar_actualizacion_dom(page, 1000)
    elif notif.copiar_desde == "representante":
        logger.info("  -> Copiando datos del representante...")
        await page.click(config.notificacion_copiar_representante_selector)
        await _esperar_actualizacion_dom(page, 1000)
    
    # Identificación
    notif_id = notif.identificacion
    
    # Seleccionar tipo de documento (dispara refresh)
    tipo_doc_valor = notif_id.tipo_documento.value
    await _seleccionar_opcion(page, config.notificacion_tipo_doc_selector, tipo_doc_valor, "Tipo doc. notif.")
    await _esperar_actualizacion_dom(page, 1000)  # El PDF indica que hay refresh al cambiar tipo
    
    await _rellenar_input(page, config.notificacion_num_doc_selector, notif_id.numero_documento, "Núm. doc. notif.")
    
    # Según si hay razón social, rellenar nombre/apellidos o razón social
    # (La razón social indica persona jurídica, si no hay es persona física)
    if notif_id.razon_social:
        # Persona jurídica -> razón social
        await _rellenar_input(page, config.notificacion_razon_social_selector, notif_id.razon_social, "Razón social notif.")
    else:
        # Persona física -> nombre y apellidos
        await _rellenar_input(page, config.notificacion_nombre_selector, notif_id.nombre, "Nombre notif.")
        await _rellenar_input(page, config.notificacion_apellido1_selector, notif_id.apellido1, "Apellido1 notif.")
        await _rellenar_input(page, config.notificacion_apellido2_selector, notif_id.apellido2, "Apellido2 notif.")
    
    # Dirección de notificación
    notif_dir = notif.direccion

    logger.info(
        f"  -> Notif dirección input: tipo_via='{notif_dir.tipo_via or ''}', nombre_via='{notif_dir.nombre_via or ''}', "
        f"num='{notif_dir.numero or ''}', cp='{notif_dir.codigo_postal or ''}', muni='{notif_dir.municipio or ''}'"
    )
    
    await _seleccionar_opcion(page, config.notificacion_pais_selector, notif_dir.pais, "País notif.")
    await _seleccionar_opcion(page, config.notificacion_provincia_selector, notif_dir.provincia, "Provincia notif.")
    await _rellenar_input(page, config.notificacion_municipio_selector, notif_dir.municipio, "Municipio notif.")
    await _seleccionar_opcion(page, config.notificacion_tipo_via_selector, notif_dir.tipo_via, "Tipo vía notif.")
    await _rellenar_nombre_via_validado(
        page,
        config,
        config.notificacion_nombre_via_selector,
        notif_dir.nombre_via,
        tipo_via=notif_dir.tipo_via,
        nombre_campo="Nombre vía notif.",
        strict=getattr(config, "strict_direccion", True),
        quitar_preposiciones=True, # Notificado usa eliminación de preposiciones
    )
    await _seleccionar_opcion(page, config.notificacion_tipo_num_selector, notif_dir.tipo_numeracion, "Tipo num. notif.")
    await _rellenar_input(page, config.notificacion_numero_selector, notif_dir.numero, "Número notif.")
    await _rellenar_input(page, config.notificacion_portal_selector, notif_dir.portal, "Portal notif.")
    await _rellenar_input(page, config.notificacion_escalera_selector, notif_dir.escalera, "Escalera notif.")
    await _rellenar_input(page, config.notificacion_planta_selector, notif_dir.planta, "Planta notif.")
    await _rellenar_input(page, config.notificacion_puerta_selector, notif_dir.puerta, "Puerta notif.")
    await _rellenar_input(page, config.notificacion_codpostal_selector, notif_dir.codigo_postal, "C.P. notif.")
    
    # Contacto de notificación
    notif_con = notif.contacto
    
    await _rellenar_input(page, config.notificacion_email_selector, notif_con.email, "Email notif.")
    await _rellenar_input(page, config.notificacion_movil_selector, notif_con.movil, "Móvil notif.")
    await _rellenar_input(page, config.notificacion_telefono_selector, notif_con.telefono, "Teléfono notif.")
    
    logger.info(f"  -> Tipo doc: {tipo_doc_valor}, Num: {notif_id.numero_documento or '(vacio)'}")
    logger.info(f"  -> Email: {notif_con.email or '(vacio)'}")
    
    # =========================================================================
    # SECCIÓN 6: Naturaleza del escrito
    # =========================================================================
    logger.info("SECCION 6: Naturaleza del escrito")
    
    if datos.naturaleza == NaturalezaEscrito.ALEGACION:
        await _click_radio(page, config.naturaleza_alegacion_selector, "Alegación")
        logger.info("  -> Naturaleza: Alegacion")
    elif datos.naturaleza == NaturalezaEscrito.RECURSO:
        await _click_radio(page, config.naturaleza_recurso_selector, "Recurso")
        logger.info("  -> Naturaleza: Recurso")
    else:
        await _click_radio(page, config.naturaleza_identificacion_selector, "Identificación conductor")
        logger.info("  -> Naturaleza: Identificacion del conductor/a")
    
    # Esperar actualización del DOM (hay refresh_method)
    await _esperar_actualizacion_dom(page, 1000)
    
    # =========================================================================
    # SECCIÓN 7: Expone y Solicita
    # =========================================================================
    logger.info("SECCION 7: Expone y Solicita")
    
    await _rellenar_y_validar_text_area(page, config.expone_selector, datos.expone, "Expone")
    await _rellenar_y_validar_text_area(page, config.solicita_selector, datos.solicita, "Solicita")
    
    logger.info(f"  -> Expone: {datos.expone[:50] + '...' if len(datos.expone) > 50 else datos.expone}")
    logger.info(f"  -> Solicita: {datos.solicita[:50] + '...' if len(datos.solicita) > 50 else datos.solicita}")
    
    # =========================================================================
    # SECCIÓN 8: Continuar
    # =========================================================================
    logger.info("SECCION 8: Pulsando Continuar")
    
    page = await _continuar_formulario_controlado(page, config)
    
    logger.info(f"  -> Navegado a pantalla de adjuntos: {page.url}")
    
    # =========================================================================
    # SECCIÓN 9: Manejar popup de SweetAlert (si aparece)
    # =========================================================================
    # El portal puede mostrar un popup de "No se reconoce la dirección"
    # Necesitamos aceptarlo para continuar
    try:
        swal_button = page.get_by_role("button", name="Aceptar dirección y continuar")
        await swal_button.wait_for(state="visible", timeout=3000)
        logger.info("SECCION 9: Popup de direccion no reconocida detectado")
        await swal_button.click()
        logger.info("  -> Popup aceptado: 'Aceptar direccion y continuar'")
        # Esperar un poco después del click
        await page.wait_for_timeout(500)
    except Exception:
        # No hay popup, continuar normalmente
        logger.debug("  -> No se detecto popup de direccion (OK)")
    
    logger.info("=" * 80)
    logger.info("FORMULARIO COMPLETADO EXITOSAMENTE")
    logger.info("=" * 80)
    
    return page
