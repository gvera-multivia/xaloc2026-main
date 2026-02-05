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

# Delays entre inputs (demo)
DELAY_ENTRE_CAMPOS_MIN = 500  # 0.5s
DELAY_ENTRE_CAMPOS_MAX = 500  # 0.5s
DELAY_DESPUES_SELECT = 500    # 0.5s


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
                logger.debug(f"  → Campo {nombre_campo or selector} deshabilitado, saltando")
                return False
            
            await elemento.first.fill(valor, timeout=1000)
            logger.debug(f"  → {nombre_campo or selector}: {valor}")
            
            # Pequeño delay después de rellenar
            await _delay_humano(page)
            return True
    except Exception as e:
        logger.warning(f"  → Error rellenando {nombre_campo or selector}: {e}")
    
    return False


def _normalizar_texto_autocomplete(texto: str) -> str:
    if texto is None:
        return ""

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
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


async def _seleccionar_por_teclado_hasta_objetivo(
    page: Page,
    *,
    objetivo: str,
    max_pasos: int,
    timeout_ms: int,
) -> bool:
    """
    Usa ArrowDown/Enter y el aria-live region para garantizar que se selecciona
    exactamente la sugerencia objetivo.
    """

    objetivo_norm = _normalizar_texto_autocomplete(objetivo)
    if not objetivo_norm:
        return False

    deadline = time.monotonic() + (timeout_ms / 1000.0)

    try:
        await page.keyboard.press("ArrowDown")
    except Exception:
        return False

    for _ in range(max(1, max_pasos)):
        await page.wait_for_timeout(120)

        actual = await _leer_sugerencia_actual_aria_live(page)
        if actual and _normalizar_texto_autocomplete(actual) == objetivo_norm:
            try:
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(120)
                return True
            except Exception:
                return False

        if time.monotonic() > deadline:
            break

        try:
            await page.keyboard.press("ArrowDown")
        except Exception:
            break

    return False


async def _seleccionar_por_indice_autocomplete(page: Page, indice: int) -> bool:
    """
    Selecciona el item del autocomplete por posición usando teclado.

    jQuery UI: ArrowDown abre el menú y selecciona el primer item; para llegar al item N
    se hace ArrowDown N veces adicionales y luego Enter.
    """

    if indice < 0:
        return False

    try:
        await page.keyboard.press("ArrowDown")
    except Exception:
        return False

    for _ in range(indice):
        await page.wait_for_timeout(120)
        try:
            await page.keyboard.press("ArrowDown")
        except Exception:
            return False

    await page.wait_for_timeout(120)
    try:
        await page.keyboard.press("Enter")
        return True
    except Exception:
        return False


async def _seleccionar_sugerencia_jquery_ui(
    page: Page,
    valor_introducido: str,
    nombre_campo: str = "",
    sugerencia_objetivo: str | None = None,
    tipo_via_preferida: str | None = None,
    timeout_ms: int = 2500,
) -> bool:
    """
    Selecciona una sugerencia de jQuery UI Autocomplete (si aparece).

    Nota: El HTML del desplegable no está en el formulario; se inyecta como:
    `ul.ui-autocomplete li.ui-menu-item`.
    """

    # El UL suele existir aunque esté oculto (display:none). No esperes "visible" aquí.
    menu = page.locator("ul.ui-autocomplete")
    try:
        await menu.first.wait_for(state="attached", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        return False

    items = page.locator("ul.ui-autocomplete li.ui-menu-item")

    await _esperar_items_autocomplete(page, timeout_ms=timeout_ms)

    # Si vamos a seleccionar una sugerencia concreta, abrimos el menú antes de clickar.
    if sugerencia_objetivo:
        try:
            await page.keyboard.press("ArrowDown")
        except Exception:
            pass

        try:
            await items.first.wait_for(state="visible", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass

    try:
        textos = [t.strip() for t in await items.all_text_contents() if t and t.strip()]
    except Exception:
        textos = []

    if sugerencia_objetivo:
        objetivo_norm = _normalizar_texto_autocomplete(sugerencia_objetivo)
        if textos:
            for idx, texto in enumerate(textos):
                if _normalizar_texto_autocomplete(texto) == objetivo_norm:
                    if await _seleccionar_por_indice_autocomplete(page, idx):
                        return True
                    break

        # Fallback: intentar por aria-live (menos determinista).
        pasos = (len(textos) + 2) if textos else 15
        if await _seleccionar_por_teclado_hasta_objetivo(
            page,
            objetivo=sugerencia_objetivo,
            max_pasos=pasos,
            timeout_ms=timeout_ms,
        ):
            return True

    if sugerencia_objetivo and textos:
        objetivo_norm = _normalizar_texto_autocomplete(sugerencia_objetivo)
        for idx, texto in enumerate(textos):
            if _normalizar_texto_autocomplete(texto) == objetivo_norm:
                try:
                    target = items.nth(idx)
                    wrapper = target.locator(":scope >> *").first
                    if await wrapper.count() > 0:
                        await wrapper.click(timeout=1000)
                    else:
                        await target.click(timeout=1000)

                    try:
                        await menu.first.wait_for(state="hidden", timeout=1500)
                    except PlaywrightTimeoutError:
                        pass
                    await _delay_humano(page, 150, 300)
                    return True
                except Exception as e:
                    logger.debug(f"  → No se pudo clickar sugerencia objetivo en {nombre_campo or 'autocomplete'}: {e}")
                    break

    if not textos:
        try:
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
            return True
        except Exception:
            return False

    objetivo = _normalizar_texto_autocomplete(valor_introducido)
    tipo_norm = _normalizar_texto_autocomplete(tipo_via_preferida or "")

    mejor_idx = 0
    mejor_score = -10_000
    objetivo_tokens = [t for t in objetivo.split(" ") if t]

    for idx, texto in enumerate(textos):
        tnorm = _normalizar_texto_autocomplete(texto)
        score = 0

        if objetivo and objetivo in tnorm:
            score += 20

        if objetivo_tokens:
            score += sum(2 for tok in objetivo_tokens if tok in tnorm)

        # Preferir el tipo de vía si viene en la sugerencia: "CHAMBERI  [PLAZA]"
        if tipo_norm:
            if f"[{tipo_norm}]" in tnorm:
                score += 10
            elif tipo_norm in tnorm:
                score += 2

        # Preferir sugerencias más "limpias" (más cortas) si hay empate
        score -= int(len(tnorm) / 20)

        if score > mejor_score:
            mejor_score = score
            mejor_idx = idx

    try:
        await items.nth(mejor_idx).click(timeout=1000)
        await _delay_humano(page, 150, 300)
        return True
    except Exception as e:
        logger.debug(f"  → No se pudo clickar sugerencia en {nombre_campo or 'autocomplete'}: {e}")

    try:
        await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter")
        return True
    except Exception:
        return False


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
            logger.debug(f"  → Campo {nombre_campo or selector} deshabilitado, saltando")
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

        # Forzar blur para disparar validaciones server-side en algunos formularios
        if seleccionado or not sugerencia_objetivo:
            try:
                await elemento.first.press("Tab")
            except Exception:
                pass

        await _delay_humano(page, 300, 500)

        if validar_sin_error:
            await _validar_campo_sin_error(page, selector, nombre_campo=nombre_campo)

        return True
    except Exception as e:
        logger.warning(f"  → Error rellenando (autocomplete) {nombre_campo or selector}: {e}")
        return False


def _texto_busqueda_nombre_via(nombre_via: str, tipo_via: str | None) -> str:
    """
    Texto para teclear en el input y abrir sugerencias.
    Retorna el texto normalizado completo.
    """
    return _normalizar_texto_autocomplete(nombre_via)


async def _rellenar_nombre_via_validado(
    page: Page,
    config: "MadridConfig",
    selector: str,
    valor_humano: str,
    *,
    tipo_via: str | None,
    nombre_campo: str,
    strict: bool,
) -> bool:
    """
    Rellena NOMBREVIA tecleando y seleccionando desde el autocomplete UI.
    """

    if not valor_humano:
        return False

    validar_sin_error = strict

    valor_tecleo = _texto_busqueda_nombre_via(valor_humano, tipo_via) or valor_humano

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
                logger.debug(f"  → Select {nombre_campo or selector} deshabilitado, saltando")
                return False
            
            # Intentar primero por label
            try:
                await elemento.first.select_option(label=valor, timeout=1000)
                logger.debug(f"  → {nombre_campo or selector}: {valor} (por label)")
                await _delay_humano(page, DELAY_DESPUES_SELECT, DELAY_DESPUES_SELECT + 200)
                return True
            except:
                # Si falla, intentar por value
                try:
                    await elemento.first.select_option(value=valor, timeout=1000)
                    logger.debug(f"  → {nombre_campo or selector}: {valor} (por value)")
                    await _delay_humano(page, DELAY_DESPUES_SELECT, DELAY_DESPUES_SELECT + 200)
                    return True
                except:
                    # Si ambos fallan, intentar por index si es numérico
                    if valor.isdigit():
                        await elemento.first.select_option(index=int(valor), timeout=1000)
                        logger.debug(f"  → {nombre_campo or selector}: opción {valor} (por index)")
                        await _delay_humano(page, DELAY_DESPUES_SELECT, DELAY_DESPUES_SELECT + 200)
                        return True
                    raise
    except Exception as e:
        logger.warning(f"  → Error seleccionando {nombre_campo or selector}: {e}")
    
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
                logger.debug(f"  → Checkbox {nombre_campo or selector} deshabilitado, saltando")
                return False
            
            is_checked = await elemento.first.is_checked()
            if marcar and not is_checked:
                await elemento.first.check(timeout=1000)
                logger.debug(f"  → {nombre_campo or selector}: marcado")
                await _delay_humano(page)
            elif not marcar and is_checked:
                await elemento.first.uncheck(timeout=1000)
                logger.debug(f"  → {nombre_campo or selector}: desmarcado")
                await _delay_humano(page)
            return True
    except Exception as e:
        logger.warning(f"  → Error con checkbox {nombre_campo or selector}: {e}")
    
    return False


async def _click_radio(page: Page, selector: str, nombre_campo: str = "") -> bool:
    """
    Hace click en un radio button.
    Incluye delay para parecer más humano.
    """
    try:
        elemento = page.locator(selector)
        if await elemento.count() > 0:
            await elemento.first.click(timeout=1000)
            logger.debug(f"  → Radio {nombre_campo or selector}: seleccionado")
            await _delay_humano(page)
            return True
    except Exception as e:
        logger.warning(f"  → Error con radio {nombre_campo or selector}: {e}")
    
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
    logger.info("SECCIÓN 1: Datos del expediente")
    
    exp = datos.expediente
    
    if exp.tipo == TipoExpediente.OPCION1:
        # Seleccionar opción 1 (NNN/EEEEEEEEE.D)
        await _click_radio(page, config.expediente_tipo_1_selector, "Tipo expediente opción 1")
        await _esperar_actualizacion_dom(page, 1000)
        
        # Rellenar campos
        await _rellenar_input(page, config.expediente_1_nnn_selector, exp.nnn, "NNN")
        await _rellenar_input(page, config.expediente_1_exp_selector, exp.eeeeeeeee, "EEEEEEEEE")
        await _rellenar_input(page, config.expediente_1_d_selector, exp.d, "D")
        logger.info(f"  → Expediente formato 1: {exp.nnn}/{exp.eeeeeeeee}.{exp.d}")
        
    else:
        # Seleccionar opción 2 (LLL/AAAA/EEEEEEEEE)
        await _click_radio(page, config.expediente_tipo_2_selector, "Tipo expediente opción 2")
        await _esperar_actualizacion_dom(page, 1000)
        
        # Rellenar campos
        await _rellenar_input(page, config.expediente_2_lll_selector, exp.lll, "LLL")
        await _rellenar_input(page, config.expediente_2_aaaa_selector, exp.aaaa, "AAAA")
        await _rellenar_input(page, config.expediente_2_exp_selector, exp.exp_num, "EEEEEEEEE")
        logger.info(f"  → Expediente formato 2: {exp.lll}/{exp.aaaa}/{exp.exp_num}")
    
    # =========================================================================
    # SECCIÓN 2: Matrícula del vehículo
    # =========================================================================
    logger.info("SECCIÓN 2: Matrícula del vehículo")
    
    await _rellenar_input(page, config.matricula_selector, datos.matricula, "Matrícula")
    logger.info(f"  → Matrícula: {datos.matricula}")
    
    # =========================================================================
    # SECCIÓN 3: Datos del interesado
    # =========================================================================
    logger.info("SECCIÓN 3: Datos del interesado")
    
    inter = datos.interesado
    
    # Teléfono (editable)
    await _rellenar_input(page, config.interesado_telefono_selector, inter.telefono, "Teléfono interesado")
    
    # Checkboxes de confirmación
    await _marcar_checkbox(page, config.interesado_check_email_selector, inter.confirmar_email, "Email interesado")
    await _marcar_checkbox(page, config.interesado_check_sms_selector, inter.confirmar_sms, "SMS interesado")
    
    logger.info(f"  → Teléfono: {inter.telefono or '(no modificado)'}")
    logger.info(f"  → Confirmar email: {inter.confirmar_email}, SMS: {inter.confirmar_sms}")
    
    # =========================================================================
    # SECCIÓN 4: Datos del representante
    # =========================================================================
    logger.info("SECCIÓN 4: Datos del representante")
    
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
    
    logger.info(f"  → Dirección: {rep_dir.nombre_via or '(vacío)'}, {rep_dir.municipio or '(vacío)'}")
    logger.info(f"  → Contacto: {rep_con.email or '(vacío)'}")
    
    # =========================================================================
    # SECCIÓN 5: Datos de notificación
    # =========================================================================
    logger.info("SECCIÓN 5: Datos de notificación")
    
    notif = datos.notificacion
    
    # Opción de copiar datos
    if notif.copiar_desde == "interesado":
        logger.info("  → Copiando datos del interesado...")
        await page.click(config.notificacion_copiar_interesado_selector)
        await _esperar_actualizacion_dom(page, 1000)
    elif notif.copiar_desde == "representante":
        logger.info("  → Copiando datos del representante...")
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
        f"  → Notif dirección input: tipo_via='{notif_dir.tipo_via or ''}', nombre_via='{notif_dir.nombre_via or ''}', "
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
    
    logger.info(f"  → Tipo doc: {tipo_doc_valor}, Núm: {notif_id.numero_documento or '(vacío)'}")
    logger.info(f"  → Email: {notif_con.email or '(vacío)'}")
    
    # =========================================================================
    # SECCIÓN 6: Naturaleza del escrito
    # =========================================================================
    logger.info("SECCIÓN 6: Naturaleza del escrito")
    
    if datos.naturaleza == NaturalezaEscrito.ALEGACION:
        await _click_radio(page, config.naturaleza_alegacion_selector, "Alegación")
        logger.info("  → Naturaleza: Alegación")
    elif datos.naturaleza == NaturalezaEscrito.RECURSO:
        await _click_radio(page, config.naturaleza_recurso_selector, "Recurso")
        logger.info("  → Naturaleza: Recurso")
    else:
        await _click_radio(page, config.naturaleza_identificacion_selector, "Identificación conductor")
        logger.info("  → Naturaleza: Identificación del conductor/a")
    
    # Esperar actualización del DOM (hay refresh_method)
    await _esperar_actualizacion_dom(page, 1000)
    
    # =========================================================================
    # SECCIÓN 7: Expone y Solicita
    # =========================================================================
    logger.info("SECCIÓN 7: Expone y Solicita")
    
    await _rellenar_input(page, config.expone_selector, datos.expone, "Expone")
    await _rellenar_input(page, config.solicita_selector, datos.solicita, "Solicita")
    
    logger.info(f"  → Expone: {datos.expone[:50] + '...' if len(datos.expone) > 50 else datos.expone}")
    logger.info(f"  → Solicita: {datos.solicita[:50] + '...' if len(datos.solicita) > 50 else datos.solicita}")
    
    # =========================================================================
    # SECCIÓN 8: Continuar
    # =========================================================================
    logger.info("SECCIÓN 8: Pulsando Continuar")
    
    # Esperar a que el botón esté visible
    await page.wait_for_selector(config.continuar_formulario_selector, state="visible", timeout=config.default_timeout)
    
    # Click y esperar navegación
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.continuar_formulario_selector)
    
    logger.info(f"  → Navegado a pantalla de adjuntos: {page.url}")
    
    # =========================================================================
    # SECCIÓN 9: Manejar popup de SweetAlert (si aparece)
    # =========================================================================
    # El portal puede mostrar un popup de "No se reconoce la dirección"
    # Necesitamos aceptarlo para continuar
    try:
        swal_button = page.get_by_role("button", name="Aceptar dirección y continuar")
        await swal_button.wait_for(state="visible", timeout=3000)
        logger.info("SECCIÓN 9: Popup de dirección no reconocida detectado")
        await swal_button.click()
        logger.info("  → Popup aceptado: 'Aceptar dirección y continuar'")
        # Esperar un poco después del click
        await page.wait_for_timeout(500)
    except Exception:
        # No hay popup, continuar normalmente
        logger.debug("  → No se detectó popup de dirección (OK)")
    
    logger.info("=" * 80)
    logger.info("FORMULARIO COMPLETADO EXITOSAMENTE")
    logger.info("=" * 80)
    
    return page
