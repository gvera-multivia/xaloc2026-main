"""
Flujo de navegación para Madrid Ayuntamiento.
Implementa los 11 pasos documentados en explore-html/madrid-guide.md
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from typing import TYPE_CHECKING

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)

async def _seleccionar_radio_por_texto(page: Page, texto: str) -> None:
    """
    Selecciona un radio cuyo label contiene el texto indicado.
    Útil cuando los IDs internos varían entre sesiones.
    """
    label = page.locator("label", has_text=re.compile(texto, re.IGNORECASE))
    radio = label.locator("input[type='radio']")
    if await radio.count() > 0:
        await radio.first.check()
        return


async def _manejar_pantalla_servcla_inicial(page: Page, config: "MadridConfig") -> bool:
    """
    Maneja la pantalla intermedia de 'Acceso al formulario' en servcla:
    https://servcla.madrid.es/WFORS_WBWFORS/servlet?action=inicial&fromLogin=true

    Devuelve True si la pantalla se gestionó (y se navegó a la siguiente).
    """
    if config.url_servcla_inicial_contains not in page.url:
        return False

    logger.info("PASO 8: Pantalla 'Acceso al formulario' (servcla) detectada")
    logger.info(f"  ƒÅ' URL: {page.url}")

    await _seleccionar_radio_por_texto(page, "Tramitar una nueva solicitud")
    await _seleccionar_radio_por_texto(page, "Persona o entidad interesada")

    # Click en Continuar (type='button', no 'submit')
    try:
        await page.wait_for_selector(config.continuar_interesado_selector, state="visible", timeout=config.default_timeout)
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
            await page.click(config.continuar_interesado_selector)
    except PlaywrightTimeoutError:
        boton = page.locator("input[type='button'][value='Continuar'], input[type='submit'][value='Continuar']")
        await boton.first.wait_for(state="visible", timeout=config.default_timeout)
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
            await boton.first.click()

    logger.info(f"  ƒÅ' Navegado a: {page.url}")
    return True


async def _aceptar_cookies_si_aparece(page: Page) -> None:
    """
    Intenta aceptar el banner de cookies si aparece.
    Busca múltiples variantes de textos de botones de aceptación.
    """
    posibles = [
        r"Aceptar",
        r"Acceptar",
        r"Aceptar todo",
        r"Aceptar todas",
        r"Accept all",
        r"Accept",
        r"Acepto",
        r"Permitir todo",
        r"Permitir todas",
        r"OK",
    ]
    
    for patron in posibles:
        try:
            boton = page.get_by_role("button", name=re.compile(patron, re.IGNORECASE))
            if await boton.count() > 0:
                await boton.first.click(timeout=1500)
                logger.info(f"  → Cookies aceptadas (botón: {patron})")
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue
    
    # También intentar con enlaces (algunos sitios usan <a> en lugar de <button>)
    for patron in posibles:
        try:
            enlace = page.get_by_role("link", name=re.compile(patron, re.IGNORECASE))
            if await enlace.count() > 0:
                await enlace.first.click(timeout=1500)
                logger.info(f"  → Cookies aceptadas (enlace: {patron})")
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue
    
    logger.debug("  → No se detectó banner de cookies o ya estaba aceptado")


async def _esperar_dom_estable(page: Page, timeout_ms: int = 2000) -> None:
    """
    Espera a que el DOM esté estable.
    
    NOTA: No usamos 'networkidle' porque puede haber scripts que hacen
    peticiones constantes y nunca se alcanza el estado idle.
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PlaywrightTimeoutError:
        logger.warning("Timeout esperando domcontentloaded, continuando...")
    
    try:
        await page.wait_for_load_state("load", timeout=10000)
    except PlaywrightTimeoutError:
        logger.warning("Timeout esperando load completo, continuando...")
    
    # Espera adicional para scripts dinámicos
    await page.wait_for_timeout(timeout_ms)


async def _cerrar_pestanas_extra(page: Page) -> None:
    """
    Cierra todas las pestañas/popups excepto la página principal.
    Útil para eliminar pestañas abiertas por widgets sociales (Facebook, Twitter, etc.).
    """
    context = page.context
    pages = context.pages
    
    if len(pages) > 1:
        logger.info(f"  → Detectadas {len(pages)} pestañas, cerrando las extras...")
        for p in pages:
            if p != page:
                try:
                    url = p.url
                    await p.close()
                    logger.info(f"  → Pestaña cerrada: {url[:50]}...")
                except Exception as e:
                    logger.warning(f"  → Error al cerrar pestaña: {e}")


def _configurar_bloqueo_popups(page: Page) -> None:
    """
    Configura un handler para cerrar automáticamente cualquier popup
    que se abra durante la navegación (redes sociales, anuncios, etc.).
    """
    context = page.context
    
    def on_page_opened(new_page):
        """Handler que cierra popups no deseados automáticamente."""
        async def cerrar_popup():
            try:
                url = new_page.url
                # Lista de dominios a bloquear
                dominios_bloqueados = [
                    "facebook.com",
                    "twitter.com",
                    "x.com",
                    "instagram.com",
                    "linkedin.com",
                    "youtube.com",
                    "whatsapp.com",
                    "telegram.org",
                    "pinterest.com",
                    "tiktok.com",
                ]
                
                # Verificar si es un popup de redes sociales
                for dominio in dominios_bloqueados:
                    if dominio in url:
                        logger.info(f"  → Bloqueando popup de {dominio}: {url[:50]}...")
                        await new_page.close()
                        return
                
                # Si es about:blank, esperar un momento y verificar de nuevo
                if url == "about:blank":
                    await new_page.wait_for_timeout(1000)
                    url = new_page.url
                    for dominio in dominios_bloqueados:
                        if dominio in url:
                            logger.info(f"  → Bloqueando popup de {dominio}: {url[:50]}...")
                            await new_page.close()
                            return
                
                logger.warning(f"  → Popup inesperado abierto: {url[:80]}")
            except Exception as e:
                logger.debug(f"  → Error procesando popup: {e}")
        
        # Ejecutar el cierre de forma asíncrona
        asyncio.create_task(cerrar_popup())
    
    # Registrar el handler
    context.on("page", on_page_opened)
    logger.debug("  → Handler de bloqueo de popups configurado")


async def ejecutar_navegacion_madrid(page: Page, config: MadridConfig) -> Page:
    """
    Ejecuta la navegación completa desde la página base hasta el formulario.
    
    Pasos implementados (según madrid-guide.md):
    1. Click "Tramitar en línea"
    2. Click "Registro Electrónico"
    3. Click primer "Continuar"
    4. Click "Iniciar tramitación"
    5. Click "DNIe / Certificado"
    6. Manejar popup de certificado Windows
    7. Click "Continuar" post-autenticación
    8. Seleccionar "Tramitar nueva solicitud"
    9. Seleccionar "Persona o Entidad interesada" + Continuar
    10. Condicional: Click "Nuevo trámite" si existe
    11. Verificar llegada al formulario
    
    Args:
        page: Página de Playwright
        config: Configuración del sitio Madrid
        
    Returns:
        Page: Página de Playwright en el formulario final
    """
    
    # Delay entre pasos de navegación (para evitar errores SSL)
    DELAY_ENTRE_PASOS = 1500  # 1.5 segundos
    
    # ========================================================================
    # CONFIGURACIÓN INICIAL: Bloqueo de popups de redes sociales
    # ========================================================================
    # Configurar handler para cerrar automáticamente popups de Facebook, etc.
    _configurar_bloqueo_popups(page)
    logger.info("  → Bloqueo de popups de redes sociales activado")
    
    # Cerrar cualquier pestaña extra que pueda haber quedado de ejecuciones anteriores
    await _cerrar_pestanas_extra(page)
    
    # ========================================================================
    # PASO 1: Navegar a URL base y click "Tramitar en línea"
    # ========================================================================
    logger.info("PASO 1: Navegando a página base y clickando 'Tramitar en línea'")
    await page.goto(config.url_base, wait_until="domcontentloaded", timeout=config.navigation_timeout)
    logger.info(f"  → URL cargada: {page.url}")
    
    # Esperar estabilización del DOM (más tiempo)
    await _esperar_dom_estable(page, timeout_ms=3000)
    
    # Aceptar cookies si aparecen
    await _aceptar_cookies_si_aparece(page)
    
    # Delay adicional para parecer más humano
    await page.wait_for_timeout(DELAY_ENTRE_PASOS)
    
    # Esperar y clickar el botón "Tramitar en línea"
    await page.wait_for_selector(config.boton_tramitar_selector, state="visible", timeout=config.default_timeout)
    await page.click(config.boton_tramitar_selector)
    logger.info(f"  → Click en botón 'Tramitar en línea' ({config.boton_tramitar_selector})")
    
    # Esperar a que aparezca el bloque #verTodas
    await page.wait_for_selector(config.bloque_tramitar_selector, state="visible", timeout=config.default_timeout)
    logger.info(f"  → Bloque de tramitación visible ({config.bloque_tramitar_selector})")
    
    # Delay antes del siguiente paso
    await page.wait_for_timeout(DELAY_ENTRE_PASOS)
    
    # ========================================================================
    # PASO 2: Click "Registro Electrónico"
    # ========================================================================
    logger.info("PASO 2: Clickando 'Registro Electrónico'")
    await page.wait_for_selector(config.registro_electronico_selector, state="visible", timeout=config.default_timeout)
    
    # Click y esperar navegación a servpub.madrid.es
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.registro_electronico_selector)
    
    logger.info(f"  → Navegado a: {page.url}")
    
    # Esperar estabilización después de cambio de dominio
    await _esperar_dom_estable(page, timeout_ms=2000)
    
    # Aceptar cookies en nuevo dominio si aparecen
    await _aceptar_cookies_si_aparece(page)
    
    # Delay antes del siguiente paso
    await page.wait_for_timeout(DELAY_ENTRE_PASOS)
    
    # ========================================================================
    # PASO 3: Click primer "Continuar"
    # ========================================================================
    logger.info("PASO 3: Clickando primer botón 'Continuar'")
    await page.wait_for_selector(config.continuar_1_selector, state="visible", timeout=config.default_timeout)
    
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.continuar_1_selector)
    
    logger.info(f"  → Navegado a: {page.url}")
    
    # Esperar estabilización
    await _esperar_dom_estable(page, timeout_ms=2000)
    
    # Delay antes del siguiente paso
    await page.wait_for_timeout(DELAY_ENTRE_PASOS)
    
    # ========================================================================
    # PASO 4: Click "Iniciar tramitación"
    # ========================================================================
    logger.info("PASO 4: Clickando 'Iniciar tramitación'")
    await page.wait_for_selector(config.iniciar_tramitacion_selector, state="visible", timeout=config.default_timeout)
    
    # Delay antes de la acción que llevará a la pasarela de certificados
    await page.wait_for_timeout(DELAY_ENTRE_PASOS)
    
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.iniciar_tramitacion_selector)
    
    logger.info(f"  → Navegado a pantalla de login: {page.url}")
    
    # Esperar estabilización después de llegar a la pasarela
    await _esperar_dom_estable(page, timeout_ms=3000)
    
    # Aceptar cookies en dominio de login si aparecen
    await _aceptar_cookies_si_aparece(page)
    
    # Delay extra antes del paso de certificado (crítico para evitar SSL errors)
    await page.wait_for_timeout(2000)  # 2 segundos extra
    
    # ========================================================================
    # PASO 5: Click "DNIe / Certificado"
    # ========================================================================
    logger.info("PASO 5: Seleccionando método de acceso 'DNIe / Certificado'")
    await page.wait_for_selector(config.certificado_login_selector, state="visible", timeout=config.default_timeout)
    
    # Delay antes de hacer click en certificado
    await page.wait_for_timeout(DELAY_ENTRE_PASOS)
    
    # ========================================================================
    # PASO 6: Manejar popup de certificado Windows
    # ========================================================================
    logger.info("PASO 6: Preparando manejo de popup de certificado Windows")
    
    # Importar utilidad de manejo de popup (nombre correcto)
    from utils.windows_popup import esperar_y_aceptar_certificado
    
    # Función wrapper para el thread - más delay inicial
    def _resolver_popup_windows() -> None:
        esperar_y_aceptar_certificado(delay_inicial=3.0, timeout=20.0)
    
    # Lanzar thread para manejar el popup
    popup_thread = threading.Thread(
        target=_resolver_popup_windows,
        daemon=True
    )
    popup_thread.start()
    logger.info("  → Thread de popup de certificado lanzado (delay 5s)")
    
    # Click en el enlace de certificado (dispara el popup)
    await page.click(config.certificado_login_selector)
    logger.info("  → Click en 'DNIe / Certificado'")
    
    # Esperar a que el thread termine (con timeout)
    popup_thread.join(timeout=10)
    
    # Esperar a que la autenticación complete
    # Estrategia: esperar a que cambie la URL o aparezca el siguiente botón
    try:
        await page.wait_for_selector(
            config.continuar_post_auth_selector,
            state="visible",
            timeout=config.navigation_timeout
        )
        logger.info("  → Autenticación completada exitosamente")
    except PlaywrightTimeoutError:
        logger.error("  ✗ Timeout esperando autenticación con certificado")
        raise
    
    # ========================================================================
    # PASO 7: Click "Continuar" post-autenticación
    # ========================================================================
    logger.info("PASO 7: Clickando 'Continuar' tras autenticación")
    
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.continuar_post_auth_selector)
    
    logger.info(f"  → Navegado a: {page.url}")
    
    # ========================================================================
    # PASO 8-9: Acceso al formulario (pantalla intermedia servcla o flujo antiguo)
    # ========================================================================
    if config.url_servcla_formulario_contains in page.url:
        logger.info("PASO 8-9: Ya estamos en el formulario (action=opcion), saltando selección de acceso")
    else:
    # Si estamos en la pantalla action=inicial, gestionarla por texto (más robusto).
        handled = await _manejar_pantalla_servcla_inicial(page, config)
        if not handled:
            # Fallback a la ruta antigua basada en IDs (por si cambia el flujo en el futuro)
            logger.info("PASO 8: Seleccionando 'Tramitar nueva solicitud'")
            await page.wait_for_selector(config.radio_nuevo_tramite_selector, state="visible", timeout=config.default_timeout)
            await page.click(config.radio_nuevo_tramite_selector)
            logger.info(f"  → Radio seleccionado ({config.radio_nuevo_tramite_selector})")
            
            # Esperar a que cargarOpciones() actualice el DOM
            await page.wait_for_selector(config.radio_interesado_selector, state="visible", timeout=config.default_timeout)
            logger.info("  → DOM actualizado, opciones cargadas")
            
            logger.info("PASO 9: Seleccionando 'Persona o Entidad interesada'")
            await page.click(config.radio_interesado_selector)
            logger.info(f"  → Radio seleccionado ({config.radio_interesado_selector})")
            
            await page.wait_for_selector(config.continuar_interesado_selector, state="visible", timeout=config.default_timeout)
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
                await page.click(config.continuar_interesado_selector)
            
            logger.info(f"  → Navegado a: {page.url}")
    
    # ========================================================================
    # PASO 10: Condicional - Manejar "Nuevo trámite" si existe
    # ========================================================================
    logger.info("PASO 10: Verificando si existe trámite a medias...")
    
    try:
        # Intentar encontrar el botón "Nuevo trámite" (timeout corto)
        await page.wait_for_selector(
            config.boton_nuevo_tramite_condicional,
            state="visible",
            timeout=5000  # Solo 5 segundos
        )
        
        logger.info("  → Detectado trámite a medias, clickando 'Nuevo trámite'")
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
            await page.click(config.boton_nuevo_tramite_condicional)
        
        logger.info(f"  → Navegado a nuevo trámite: {page.url}")
        
    except PlaywrightTimeoutError:
        logger.info("  → No hay trámite a medias, continuando normalmente")
    
    # ========================================================================
    # PASO 11: Verificar llegada al formulario
    # ========================================================================
    logger.info("PASO 11: Verificando llegada al formulario")
    
    if config.url_servcla_formulario_contains not in page.url:
        logger.info(f"  → Aviso: URL no contiene action=opcion todavía: {page.url}")
    
    # Esperar a que exista un formulario (criterio genérico por ahora)
    await page.wait_for_selector(config.formulario_llegada_selector, state="attached", timeout=config.default_timeout)
    
    logger.info("  ✓ Formulario detectado")
    logger.info(f"  ✓ URL final: {page.url}")
    logger.info("=" * 80)
    logger.info("NAVEGACIÓN COMPLETADA EXITOSAMENTE")
    logger.info("=" * 80)
    
    return page
