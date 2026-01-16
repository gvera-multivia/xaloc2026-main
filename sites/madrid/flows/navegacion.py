"""
Flujo de navegación para Madrid Ayuntamiento.
Implementa los 11 pasos documentados en explore-html/madrid-guide.md
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)


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
    
    # ========================================================================
    # PASO 1: Navegar a URL base y click "Tramitar en línea"
    # ========================================================================
    logger.info("PASO 1: Navegando a página base y clickando 'Tramitar en línea'")
    await page.goto(config.url_base, wait_until="domcontentloaded", timeout=config.navigation_timeout)
    logger.info(f"  → URL cargada: {page.url}")
    
    # Esperar y clickar el botón "Tramitar en línea"
    await page.wait_for_selector(config.boton_tramitar_selector, state="visible", timeout=config.default_timeout)
    await page.click(config.boton_tramitar_selector)
    logger.info(f"  → Click en botón 'Tramitar en línea' ({config.boton_tramitar_selector})")
    
    # Esperar a que aparezca el bloque #verTodas
    await page.wait_for_selector(config.bloque_tramitar_selector, state="visible", timeout=config.default_timeout)
    logger.info(f"  → Bloque de tramitación visible ({config.bloque_tramitar_selector})")
    
    # ========================================================================
    # PASO 2: Click "Registro Electrónico"
    # ========================================================================
    logger.info("PASO 2: Clickando 'Registro Electrónico'")
    await page.wait_for_selector(config.registro_electronico_selector, state="visible", timeout=config.default_timeout)
    
    # Click y esperar navegación a servpub.madrid.es
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.registro_electronico_selector)
    
    logger.info(f"  → Navegado a: {page.url}")
    
    # ========================================================================
    # PASO 3: Click primer "Continuar"
    # ========================================================================
    logger.info("PASO 3: Clickando primer botón 'Continuar'")
    await page.wait_for_selector(config.continuar_1_selector, state="visible", timeout=config.default_timeout)
    
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.continuar_1_selector)
    
    logger.info(f"  → Navegado a: {page.url}")
    
    # ========================================================================
    # PASO 4: Click "Iniciar tramitación"
    # ========================================================================
    logger.info("PASO 4: Clickando 'Iniciar tramitación'")
    await page.wait_for_selector(config.iniciar_tramitacion_selector, state="visible", timeout=config.default_timeout)
    
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
        await page.click(config.iniciar_tramitacion_selector)
    
    logger.info(f"  → Navegado a pantalla de login: {page.url}")
    
    # ========================================================================
    # PASO 5: Click "DNIe / Certificado"
    # ========================================================================
    logger.info("PASO 5: Seleccionando método de acceso 'DNIe / Certificado'")
    await page.wait_for_selector(config.certificado_login_selector, state="visible", timeout=config.default_timeout)
    
    # ========================================================================
    # PASO 6: Manejar popup de certificado Windows
    # ========================================================================
    logger.info("PASO 6: Preparando manejo de popup de certificado Windows")
    
    # Importar utilidad de manejo de popup
    from utils.windows_popup import auto_accept_certificate_popup
    
    # Lanzar thread para manejar el popup
    popup_thread = threading.Thread(
        target=auto_accept_certificate_popup,
        args=(2,),  # Esperar 2 segundos antes de presionar Enter
        daemon=True
    )
    popup_thread.start()
    logger.info("  → Thread de popup de certificado lanzado")
    
    # Click en el enlace de certificado (dispara el popup)
    await page.click(config.certificado_login_selector)
    logger.info("  → Click en 'DNIe / Certificado'")
    
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
    # PASO 8: Seleccionar "Tramitar nueva solicitud"
    # ========================================================================
    logger.info("PASO 8: Seleccionando 'Tramitar nueva solicitud'")
    await page.wait_for_selector(config.radio_nuevo_tramite_selector, state="visible", timeout=config.default_timeout)
    await page.click(config.radio_nuevo_tramite_selector)
    logger.info(f"  → Radio seleccionado ({config.radio_nuevo_tramite_selector})")
    
    # Esperar a que cargarOpciones() actualice el DOM
    # Esperamos a que aparezca el siguiente radio
    await page.wait_for_selector(config.radio_interesado_selector, state="visible", timeout=config.default_timeout)
    logger.info("  → DOM actualizado, opciones cargadas")
    
    # ========================================================================
    # PASO 9: Seleccionar "Persona o Entidad interesada" + Continuar
    # ========================================================================
    logger.info("PASO 9: Seleccionando 'Persona o Entidad interesada'")
    await page.click(config.radio_interesado_selector)
    logger.info(f"  → Radio seleccionado ({config.radio_interesado_selector})")
    
    # Click en Continuar (type='button', no 'submit')
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
    
    # Esperar a que exista un formulario (criterio genérico por ahora)
    await page.wait_for_selector(config.formulario_llegada_selector, state="attached", timeout=config.default_timeout)
    
    logger.info("  ✓ Formulario detectado")
    logger.info(f"  ✓ URL final: {page.url}")
    logger.info("=" * 80)
    logger.info("NAVEGACIÓN COMPLETADA EXITOSAMENTE")
    logger.info("=" * 80)
    
    return page
