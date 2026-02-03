"""
Flujo de firma y verificación de documento para Madrid Ayuntamiento.

Pasos:
1. Click en "Firma y registrar" (btRedireccion)
2. Esperar navegación a SIGNA_WBFIRMAR/solicitarFirma.do
3. Click en "Verificar documento"
4. Capturar popup con jsessionid
5. Descargar documento del popup
6. Cerrar popup y volver a ventana principal
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

logger = logging.getLogger(__name__)


def _extraer_jsessionid(url: str) -> str:
    """
    Extrae el jsessionid de una URL.
    
    Args:
        url: URL que contiene jsessionid (ej: visualizarDocumento.do;jsessionid=XnsSn5...)
        
    Returns:
        El jsessionid extraído
        
    Raises:
        ValueError: Si no se encuentra jsessionid en la URL
    """
    match = re.search(r'jsessionid=([^&;/?]+)', url)
    if match:
        return match.group(1)
    raise ValueError(f"No se pudo extraer jsessionid de la URL: {url}")


async def _esperar_popup_documento(page: Page, timeout_ms: int = 30000) -> Page:
    """
    Espera y captura el popup que se abre al verificar el documento.
    
    Args:
        page: Página principal
        timeout_ms: Timeout en milisegundos
        
    Returns:
        La página del popup capturada
    """
    context = page.context
    
    # Configurar listener para capturar nueva ventana
    async with context.expect_page(timeout=timeout_ms) as new_page_info:
        # El click se hace fuera de este bloque
        pass
    
    popup_page = await new_page_info.value
    await popup_page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    
    logger.info(f"Popup capturado con URL: {popup_page.url}")
    return popup_page


async def _descargar_documento_popup(popup_page: Page, destino: Path) -> Path:
    """
    Descarga el documento visualizado en el popup usando fetch interno.
    
    Este método usa fetch() dentro del contexto del navegador para:
    - Mantener las cookies de sesión activas
    - Descargar el PDF original sin necesidad de impresión virtual
    - Evitar problemas de renderizado vacío
    
    Args:
        popup_page: Página del popup con el documento
        destino: Ruta donde guardar el documento
        
    Returns:
        Path al archivo descargado
    """
    logger.info(f"Descargando documento desde popup a: {destino}")
    
    # Asegurar que el directorio existe
    destino.parent.mkdir(parents=True, exist_ok=True)
    
    # Obtener la URL actual del popup (que contiene el documento)
    url = popup_page.url
    logger.info(f"URL del documento: {url}")
    
    try:
        # Script JS para descargar el archivo como Base64 sin navegar
        # Se ejecuta en el contexto de la página actual, manteniendo la sesión
        js_download_script = """
        async (url) => {
            const response = await fetch(url);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const blob = await response.blob();
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onloadend = () => resolve(reader.result.split(',')[1]);
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            });
        }
        """
        
        # Ejecutar el fetch en el contexto de la página actual
        logger.info("Ejecutando fetch en contexto del navegador...")
        base64_data = await popup_page.evaluate(js_download_script, url)
        
        # Decodificar y guardar el PDF
        import base64
        pdf_bytes = base64.b64decode(base64_data)
        
        destino.write_bytes(pdf_bytes)
        
        file_size = len(pdf_bytes)
        logger.info(f"Documento descargado correctamente ({file_size} bytes)")
        
        # Validación de tamaño
        if file_size < 2000:
            logger.warning("⚠️ El archivo es sospechosamente pequeño, revisa el contenido.")
        
        return destino
        
    except Exception as e:
        logger.error(f"Error al descargar documento: {e}")
        raise


async def ejecutar_firma_madrid(
    page: Page, 
    config: "MadridConfig", 
    destino_descarga: Path
) -> Page:
    """
    Ejecuta el flujo de firma y verificación de documento.
    
    Pasos:
    1. Validar que estamos en la página correcta
    2. Click en "Firma y registrar"
    3. Esperar navegación a SIGNA_WBFIRMAR/solicitarFirma.do
    4. Click en "Verificar documento"
    5. Capturar popup y extraer jsessionid
    6. Descargar documento
    7. Cerrar popup y volver a ventana principal
    
    Args:
        page: Página de Playwright
        config: Configuración del sitio Madrid
        destino_descarga: Path donde guardar el documento descargado
        
    Returns:
        Page: Página principal (después de cerrar el popup)
    """
    logger.info("=" * 80)
    logger.info("INICIANDO FLUJO DE FIRMA Y VERIFICACIÓN")
    logger.info("=" * 80)
    
    # =========================================================================
    # PASO 1: Validar que estamos en la página correcta
    # =========================================================================
    logger.info("Validando presencia del botón 'Firma y registrar'...")
    
    try:
        await page.wait_for_selector(
            config.firma_registrar_selector,
            state="visible",
            timeout=config.default_timeout
        )
        logger.info("✓ Botón 'Firma y registrar' encontrado")
    except PlaywrightTimeoutError:
        raise RuntimeError(
            f"No se encontró el botón 'Firma y registrar' ({config.firma_registrar_selector})"
        )
    
    # =========================================================================
    # PASO 2: Click en "Firma y registrar"
    # =========================================================================
    logger.info("Haciendo click en 'Firma y registrar'...")
    
    # Esperar navegación con timeout generoso (puede tardar)
    try:
        async with page.expect_navigation(
            wait_until="domcontentloaded",
            timeout=config.firma_navigation_timeout
        ):
            await page.click(config.firma_registrar_selector)
        
        logger.info(f"✓ Navegación completada. URL actual: {page.url}")
    except PlaywrightTimeoutError:
        raise RuntimeError(
            "Timeout esperando navegación tras click en 'Firma y registrar'"
        )
    
    # =========================================================================
    # PASO 3: Validar URL de SIGNA_WBFIRMAR
    # =========================================================================
    logger.info("Validando URL de la página de firma...")
    
    if config.url_signa_firma_contains not in page.url:
        raise RuntimeError(
            f"URL inesperada tras 'Firma y registrar'. "
            f"Esperado: {config.url_signa_firma_contains}, "
            f"Actual: {page.url}"
        )
    
    logger.info(f"✓ URL validada: {page.url}")
    
    # Esperar a que la página esté completamente cargada
    await page.wait_for_load_state("networkidle", timeout=config.default_timeout)
    
    # =========================================================================
    # PASO 4: Click en "Verificar documento" y capturar popup
    # =========================================================================
    logger.info("Preparando para hacer click en 'Verificar documento'...")
    
    # Validar presencia del botón
    try:
        await page.wait_for_selector(
            config.verificar_documento_selector,
            state="visible",
            timeout=config.default_timeout
        )
        logger.info("✓ Botón 'Verificar documento' encontrado")
    except PlaywrightTimeoutError:
        raise RuntimeError(
            f"No se encontró el botón 'Verificar documento' ({config.verificar_documento_selector})"
        )
    
    # Configurar captura de popup ANTES del click
    logger.info("Configurando captura de popup...")
    context = page.context
    
    popup_page = None
    try:
        async with context.expect_page(timeout=config.popup_wait_timeout) as new_page_info:
            logger.info("Haciendo click en 'Verificar documento'...")
            await page.click(config.verificar_documento_selector)
        
        popup_page = await new_page_info.value
        await popup_page.wait_for_load_state("domcontentloaded", timeout=config.default_timeout)
        
        logger.info(f"✓ Popup capturado con URL: {popup_page.url}")
        
    except PlaywrightTimeoutError:
        raise RuntimeError(
            "Timeout esperando que se abra el popup de verificación. "
            "Verifica que no haya bloqueadores de popups activos."
        )
    
    # =========================================================================
    # PASO 5: Extraer jsessionid
    # =========================================================================
    logger.info("Extrayendo jsessionid de la URL del popup...")
    
    try:
        jsessionid = _extraer_jsessionid(popup_page.url)
        logger.info(f"✓ jsessionid extraído: {jsessionid[:20]}...")
    except ValueError as e:
        logger.error(f"Error extrayendo jsessionid: {e}")
        logger.error(f"URL del popup: {popup_page.url}")
        raise
    
    # Validar que la URL contiene el patrón esperado
    if config.url_visualizar_documento_pattern not in popup_page.url:
        logger.warning(
            f"URL del popup no contiene el patrón esperado "
            f"({config.url_visualizar_documento_pattern}). "
            f"URL actual: {popup_page.url}"
        )
    
    # =========================================================================
    # PASO 6: Descargar documento
    # =========================================================================
    logger.info("Descargando documento del popup...")
    
    try:
        await _descargar_documento_popup(popup_page, destino_descarga)
        logger.info(f"✓ Documento descargado en: {destino_descarga}")
    except Exception as e:
        logger.error(f"Error descargando documento: {e}")
        # Capturar screenshot del popup para debugging
        screenshot_path = destino_descarga.parent / f"error_popup_{destino_descarga.stem}.png"
        await popup_page.screenshot(path=screenshot_path, full_page=True)
        logger.error(f"Screenshot del popup guardado en: {screenshot_path}")
        raise
    
    # =========================================================================
    # PASO 7: Cerrar popup y volver a ventana principal
    # =========================================================================
    logger.info("Cerrando popup y volviendo a ventana principal...")
    
    await popup_page.close()
    logger.info("✓ Popup cerrado")
    
    # Asegurar que volvemos a la página principal
    await page.bring_to_front()
    logger.info(f"✓ Ventana principal activa. URL: {page.url}")
    
    logger.info("=" * 80)
    logger.info("FLUJO DE FIRMA Y VERIFICACIÓN COMPLETADO")
    logger.info("=" * 80)
    
    return page
