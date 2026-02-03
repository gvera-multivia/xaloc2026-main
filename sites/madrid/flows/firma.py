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
    Descarga el documento visualizado en el popup.

    Nota: algunos endpoints (servlets/Struts `.do`) devuelven HTTP 405 cuando se
    intentan descargar vía `fetch()` (XHR/JS) aunque la navegación normal
    funcione. Por eso evitamos `page.evaluate(fetch)` y usamos primero
    `page.request` (cookies compartidas) y, si falla, forzamos una navegación y
    capturamos la respuesta.
    
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
        timeout_ms = 60000

        def _looks_like_pdf(data: bytes, content_type: str | None) -> bool:
            if data.startswith(b"%PDF"):
                return True
            if content_type and "pdf" in content_type.lower():
                return True
            return False

        # Intento 1: APIRequestContext asociado a la página (comparte cookies/sesión)
        logger.info("Intento 1/2: descarga vía page.request.get(...)")
        resp = await popup_page.request.get(
            url,
            timeout=timeout_ms,
            headers={
                "Accept": "application/pdf,application/octet-stream,*/*",
                "Referer": popup_page.url,
            },
        )
        body = await resp.body()
        content_type = (resp.headers or {}).get("content-type")

        if resp.ok and _looks_like_pdf(body, content_type):
            destino.write_bytes(body)
            file_size = len(body)
            logger.info(f"✓ Documento descargado correctamente ({file_size} bytes)")
            if file_size < 2000:
                logger.warning("⚠️ El archivo es sospechosamente pequeño, revisa el contenido.")
            return destino

        logger.warning(
            "Descarga vía request no devolvió PDF (status=%s, content-type=%s, bytes=%s). Probando fallback...",
            getattr(resp, "status", None),
            content_type,
            len(body) if body is not None else None,
        )

        # Intento 2: forzar navegación y capturar la respuesta (equivalente a carga normal de documento)
        logger.info("Intento 2/2: recarga por navegación y captura de respuesta")
        base_url = url.split(";", 1)[0]
        async with popup_page.expect_response(
            lambda r: (r.url == url) or (r.url.startswith(base_url)),
            timeout=timeout_ms,
        ) as resp_info:
            await popup_page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        nav_resp = await resp_info.value
        nav_body = await nav_resp.body()
        nav_ct = (nav_resp.headers or {}).get("content-type")

        if nav_resp.ok and _looks_like_pdf(nav_body, nav_ct):
            destino.write_bytes(nav_body)
            file_size = len(nav_body)
            logger.info(f"✓ Documento descargado correctamente ({file_size} bytes)")
            if file_size < 2000:
                logger.warning("⚠️ El archivo es sospechosamente pequeño, revisa el contenido.")
            return destino

        raise RuntimeError(
            f"No se pudo descargar el PDF (request: {getattr(resp, 'status', None)}; "
            f"nav: {getattr(nav_resp, 'status', None)}; ct: {nav_ct!r})"
        )
        
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
