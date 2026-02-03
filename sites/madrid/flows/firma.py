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
    funcione. Además, algunos servidores bloquean reintentos (403/405) cuando se
    intenta "re-descargar" el mismo recurso. Por eso este método intenta
    aprovechar el propio flujo de red del navegador (sin lanzar peticiones extra)
    y, solo si es posible, capturar una descarga nativa.
    
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

        # Intento 1: descarga nativa (si el popup ofrece un enlace/botón descargable).
        # Ojo: el visor PDF del navegador suele NO exponer el botón de descarga en el DOM.
        download_trigger = popup_page.locator(
            "a[download], a:has-text('Descargar'), button:has-text('Descargar'), a[href*='descargar'], a[href$='.pdf']"
        )
        try:
            if await download_trigger.first.is_visible(timeout=500):
                logger.info("Intento 1/2: captura de download nativo (expect_download + save_as)")
                async with popup_page.expect_download(timeout=timeout_ms) as dl_info:
                    await download_trigger.first.click()
                download = await dl_info.value
                await download.save_as(destino)
                data = destino.read_bytes()
                if not _looks_like_pdf(data, None) and len(data) < 1000:
                    raise RuntimeError("Descarga nativa demasiado pequeña / no parece PDF")
                logger.info(f"✓ Documento descargado (download) ({len(data)} bytes)")
                if len(data) < 2000:
                    logger.warning("⚠️ El archivo es sospechosamente pequeño, revisa el contenido.")
                return destino
        except Exception as e:
            logger.info(f"Descarga nativa no disponible o falló: {e}")

        # Intento 2: sin peticiones extra. Capturar respuestas ya cargadas en el popup.
        logger.info("Intento 2/2: inspección de respuestas del popup (sin reintentos HTTP)")
        captured: list = []

        def _on_response(resp) -> None:
            try:
                resp_url = (resp.url or "")
                ct = (resp.headers or {}).get("content-type", "").lower()
                if ("documento" in resp_url.lower()) or ("pdf" in ct) or ("octet-stream" in ct):
                    captured.append(resp)
            except Exception:
                pass

        popup_page.on("response", _on_response)
        try:
            try:
                await popup_page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                # Si no llega a networkidle (p.ej. streams), esperar un poco para dejar terminar la carga.
                await popup_page.wait_for_timeout(2000)
        finally:
            popup_page.remove_listener("response", _on_response)

        # Priorizar respuestas que apunten al endpoint esperado.
        prefer = [r for r in captured if "visualizarDocumento.do" in (r.url or "")]
        rest = [r for r in captured if r not in prefer]

        for resp in prefer + rest:
            ct = (resp.headers or {}).get("content-type")
            try:
                data = await resp.body()
            except Exception:
                continue
            if not data:
                continue
            if _looks_like_pdf(data, ct):
                destino.write_bytes(data)
                logger.info(f"✓ Documento capturado del popup ({len(data)} bytes)")
                if len(data) < 2000:
                    logger.warning("⚠️ El archivo es sospechosamente pequeño, revisa el contenido.")
                return destino

        raise RuntimeError(
            "No se pudo extraer un PDF del popup sin reintentar la descarga (posible bloqueo 403/405)."
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
    pdf_bytes_capturados: bytes | None = None
    try:
        captured_responses: list = []

        def _looks_like_pdf(data: bytes, content_type: str | None) -> bool:
            if data.startswith(b"%PDF"):
                return True
            if content_type and "pdf" in content_type.lower():
                return True
            return False

        def _on_ctx_response(resp) -> None:
            try:
                resp_url = (resp.url or "")
                if "servcla.madrid.es" not in resp_url:
                    return
                ct = (resp.headers or {}).get("content-type", "").lower()
                if ("documento" in resp_url.lower()) or ("pdf" in ct) or ("octet-stream" in ct):
                    captured_responses.append(resp)
            except Exception:
                pass

        # Capturar respuestas del navegador durante el click/apertura del popup.
        # Esto evita hacer peticiones extra (que suelen devolver 403/405).
        context.on("response", _on_ctx_response)
        try:
            async with context.expect_page(timeout=config.popup_wait_timeout) as new_page_info:
                logger.info("Haciendo click en 'Verificar documento'...")
                await page.click(config.verificar_documento_selector)
        
            popup_page = await new_page_info.value
            await popup_page.wait_for_load_state("domcontentloaded", timeout=config.default_timeout)
            try:
                await popup_page.wait_for_load_state("networkidle", timeout=config.default_timeout)
            except Exception:
                await popup_page.wait_for_timeout(1500)
        finally:
            context.remove_listener("response", _on_ctx_response)
        
        logger.info(f"✓ Popup capturado con URL: {popup_page.url}")

        # Intentar extraer el PDF desde las respuestas capturadas (sin reintentar descargas).
        prefer = [
            r for r in captured_responses
            if config.url_visualizar_documento_pattern in (r.url or "")
        ]
        rest = [r for r in captured_responses if r not in prefer]

        for resp in prefer + rest:
            try:
                pdf_body = await resp.body()
            except Exception:
                continue
            if not pdf_body:
                continue
            pdf_ct = (resp.headers or {}).get("content-type")
            if _looks_like_pdf(pdf_body, pdf_ct):
                destino_descarga.parent.mkdir(parents=True, exist_ok=True)
                destino_descarga.write_bytes(pdf_body)
                pdf_bytes_capturados = pdf_body
                logger.info(f"✓ PDF capturado del tráfico de red ({len(pdf_body)} bytes)")
                break

        if pdf_bytes_capturados is None:
            logger.warning("No se pudo capturar el PDF del tráfico de red; se usará método alternativo.")
        
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
        if pdf_bytes_capturados is not None:
            if len(pdf_bytes_capturados) < 2000:
                logger.warning("⚠️ El archivo es sospechosamente pequeño, revisa el contenido.")
            logger.info(f"✓ Documento descargado en: {destino_descarga}")
        else:
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
