"""
Flujo de descarga del justificante de registro tras el envío del trámite.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import Page, TimeoutError

if TYPE_CHECKING:
    from core.client_documentation import ClientIdentity

from core.client_documentation import (
    client_identity_from_payload,
    get_ruta_cliente_documentacion,
)

logger = logging.getLogger(__name__)

JUSTIFICANTE_TIMEOUT_MS = 30000
IFRAME_LOAD_TIMEOUT_MS = 15000


async def _esperar_iframe_cargado(page: Page) -> None:
    """
    Espera a que el iframe del justificante esté presente y cargado.
    """
    logger.info("Esperando a que el iframe del justificante esté cargado...")
    
    iframe_locator = page.locator("iframe#iframeJustif")
    await iframe_locator.wait_for(state="attached", timeout=IFRAME_LOAD_TIMEOUT_MS)
    
    # Esperar a que el src del iframe esté presente
    await page.wait_for_function(
        """() => {
            const iframe = document.getElementById('iframeJustif');
            return iframe && iframe.src && iframe.src.length > 0;
        }""",
        timeout=IFRAME_LOAD_TIMEOUT_MS,
    )
    
    logger.info("Iframe del justificante detectado y cargado")


async def _obtener_url_justificante(page: Page) -> str:
    """
    Extrae la URL del justificante desde el atributo src del iframe.
    
    Returns:
        URL completa del justificante para descarga
    """
    logger.info("Extrayendo URL del justificante desde el iframe...")
    
    url = await page.evaluate(
        """() => {
            const iframe = document.getElementById('iframeJustif');
            if (!iframe || !iframe.src) {
                throw new Error('No se pudo encontrar el iframe o su src');
            }
            return iframe.src;
        }"""
    )
    
    if not url:
        raise ValueError("No se pudo extraer la URL del justificante desde el iframe")
    
    logger.info(f"URL del justificante extraída: {url}")
    return str(url)


async def _descargar_pdf_desde_url(page: Page, url: str, destino: Path) -> None:
    """
    Descarga el PDF del justificante navegando al iframe y guardándolo como PDF.
    
    Args:
        page: Página de Playwright
        url: URL del justificante
        destino: Ruta donde guardar el PDF temporalmente
    """
    logger.info(f"Descargando justificante desde: {url}")
    
    try:
        # Método principal: Navegar al iframe y usar print-to-PDF
        # Este método es más confiable que intentar una descarga directa
        logger.info("Navegando al iframe del justificante...")
        await page.goto(url, wait_until="networkidle", timeout=JUSTIFICANTE_TIMEOUT_MS)
        
        # Esperar a que el contenido del PDF se cargue
        await page.wait_for_timeout(2000)
        
        # Guardar la página como PDF usando el motor de impresión de Chromium
        logger.info("Guardando justificante como PDF...")
        await page.pdf(
            path=destino,
            format="A4",
            print_background=True,
            prefer_css_page_size=True
        )
        logger.info(f"✓ Justificante descargado correctamente en: {destino}")
        
    except Exception as e:
        logger.error(f"Error en descarga principal: {e}")
        
        # Método de respaldo: intentar con descarga directa
        logger.warning("Intentando método de descarga alternativo...")
        try:
            download_url = url.replace("ACTION=view", "ACTION=view&method=download")
            
            async with page.expect_download(timeout=JUSTIFICANTE_TIMEOUT_MS) as download_info:
                # Usar evaluate para forzar la descarga sin navegar
                await page.evaluate(f"window.location.href = '{download_url}'")
                download = await download_info.value
                
                # Guardar el archivo descargado
                await download.save_as(destino)
                logger.info(f"✓ Justificante descargado mediante método alternativo en: {destino}")
                
        except Exception as e2:
            logger.error(f"Error en método alternativo: {e2}")
            raise RuntimeError(f"No se pudo descargar el justificante: {e}") from e


def _construir_ruta_recursos_telematicos(payload: dict) -> Path:
    """
    Construye la ruta a la carpeta RECURSOS TELEMATICOS del cliente.
    
    Args:
        payload: Diccionario con datos del trámite (incluye mandatario)
    
    Returns:
        Path a la carpeta RECURSOS TELEMATICOS del cliente
    """
    logger.info("Construyendo ruta a carpeta RECURSOS TELEMATICOS...")
    
    # Obtener identidad del cliente desde el payload
    client = client_identity_from_payload(payload)
    
    # Obtener base_path desde variables de entorno o usar valor por defecto
    base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    
    # Obtener ruta base del cliente (apunta a DOCUMENTACION)
    ruta_cliente_base = get_ruta_cliente_documentacion(client, base_path=base_path)
    
    # Subir un nivel y entrar en RECURSOS TELEMATICOS
    ruta_recursos = ruta_cliente_base.parent / "RECURSOS TELEMATICOS"
    
    # Crear carpeta si no existe
    ruta_recursos.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Ruta RECURSOS TELEMATICOS: {ruta_recursos}")
    return ruta_recursos


def _renombrar_y_mover_justificante(
    temporal: Path, num_expediente: str, destino_dir: Path
) -> Path:
    """
    Renombra el justificante temporal y lo mueve a la carpeta de destino.
    
    Args:
        temporal: Ruta del archivo temporal descargado
        num_expediente: Número de expediente para el nombre del archivo
        destino_dir: Carpeta de destino donde mover el archivo
    
    Returns:
        Ruta final del justificante guardado
    """
    # Construir nombre final
    nombre_final = f"JUSTIFICANTE {num_expediente}.pdf"
    ruta_final = destino_dir / nombre_final
    
    logger.info(f"Renombrando justificante a: {nombre_final}")
    
    # Mover y renombrar
    if ruta_final.exists():
        logger.warning(f"El archivo {ruta_final} ya existe, será sobrescrito")
        ruta_final.unlink()
    
    temporal.rename(ruta_final)
    logger.info(f"Justificante guardado en: {ruta_final}")
    
    return ruta_final


async def descargar_y_guardar_justificante(page: Page, payload: dict) -> str:
    """
    Descarga el justificante de registro y lo guarda en la carpeta del cliente.
    
    Args:
        page: Página de Playwright (debe estar en la URL del justificante)
        payload: Diccionario con datos del trámite
    
    Returns:
        Ruta absoluta del justificante guardado
    
    Raises:
        ValueError: Si faltan datos necesarios en el payload
        RuntimeError: Si falla la descarga o guardado del justificante
    """
    logger.info("=== Iniciando descarga del justificante ===")
    
    # Verificar que estamos en la página correcta
    if "TramitaJustif" not in page.url:
        raise RuntimeError(
            f"No estamos en la página del justificante. URL actual: {page.url}"
        )
    
    # Extraer número de expediente del payload
    num_expediente = payload.get("expediente_num") or payload.get("denuncia_num")
    if not num_expediente:
        raise ValueError("Falta 'expediente_num' o 'denuncia_num' en el payload")
    
    num_expediente = str(num_expediente).strip()
    logger.info(f"Número de expediente: {num_expediente}")
    
    try:
        # 1. Esperar a que el iframe esté cargado
        await _esperar_iframe_cargado(page)
        
        # 2. Extraer URL del justificante
        url_justificante = await _obtener_url_justificante(page)
        
        # 3. Construir ruta de destino
        ruta_recursos = _construir_ruta_recursos_telematicos(payload)
        
        # 4. Descargar a archivo temporal
        temporal = Path("tmp") / f"justificante_temp_{num_expediente}.pdf"
        temporal.parent.mkdir(parents=True, exist_ok=True)
        
        await _descargar_pdf_desde_url(page, url_justificante, temporal)
        
        # 5. Renombrar y mover a carpeta final
        ruta_final = _renombrar_y_mover_justificante(
            temporal, num_expediente, ruta_recursos
        )
        
        logger.info(f"✓ Justificante descargado exitosamente: {ruta_final}")
        return str(ruta_final)
        
    except Exception as e:
        logger.error(f"Error descargando justificante: {e}")
        # Capturar screenshot para diagnóstico
        try:
            screenshot_path = Path("tmp") / f"error_justificante_{num_expediente}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            logger.error(f"Screenshot de error guardado en: {screenshot_path}")
        except Exception:
            pass
        raise RuntimeError(f"Fallo en descarga del justificante: {e}") from e


__all__ = ["descargar_y_guardar_justificante"]
