"""
Flujo de rellenado del formulario de Madrid.
Implementa las secciones documentadas en explore-html/llenar formulario-madrid.md
"""

from __future__ import annotations

import logging
import random
import re
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
    
    # Teléfono (editable) - NO RELLENAR para evitar duplicados
    # await _rellenar_input(page, config.interesado_telefono_selector, inter.telefono, "Teléfono interesado")
    
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
    await _rellenar_input(page, config.representante_nombre_via_selector, rep_dir.nombre_via, "Nombre vía rep.")
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
    await _rellenar_input(page, config.representante_movil_selector, rep_con.movil, "Móvil rep.")
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
    
    # Según tipo de documento, rellenar nombre/apellidos o razón social
    if notif_id.tipo_documento == TipoDocumento.NIF:
        # Persona jurídica -> razón social
        await _rellenar_input(page, config.notificacion_razon_social_selector, notif_id.razon_social, "Razón social notif.")
    else:
        # Persona física -> nombre y apellidos
        await _rellenar_input(page, config.notificacion_nombre_selector, notif_id.nombre, "Nombre notif.")
        await _rellenar_input(page, config.notificacion_apellido1_selector, notif_id.apellido1, "Apellido1 notif.")
        await _rellenar_input(page, config.notificacion_apellido2_selector, notif_id.apellido2, "Apellido2 notif.")
    
    # Dirección de notificación
    notif_dir = notif.direccion
    
    await _seleccionar_opcion(page, config.notificacion_pais_selector, notif_dir.pais, "País notif.")
    await _seleccionar_opcion(page, config.notificacion_provincia_selector, notif_dir.provincia, "Provincia notif.")
    await _rellenar_input(page, config.notificacion_municipio_selector, notif_dir.municipio, "Municipio notif.")
    await _seleccionar_opcion(page, config.notificacion_tipo_via_selector, notif_dir.tipo_via, "Tipo vía notif.")
    await _rellenar_input(page, config.notificacion_nombre_via_selector, notif_dir.nombre_via, "Nombre vía notif.")
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
    logger.info("=" * 80)
    logger.info("FORMULARIO COMPLETADO EXITOSAMENTE")
    logger.info("=" * 80)
    
    return page
