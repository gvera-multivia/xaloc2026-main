"""
Flujo de descarga del justificante de registro tras el envío del trámite.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError

from core.justificantes_storage import (
    build_receipt_filename,
    resolve_receipt_dir_from_payload,
    save_receipt_from_tmp,
)

logger = logging.getLogger(__name__)

JUSTIFICANTE_TIMEOUT_MS = 120000
IFRAME_LOAD_TIMEOUT_MS = 30000


async def _esperar_iframe_cargado(page: Page) -> None:
    """
    Espera a que el iframe del justificante esté presente y cargado.
    """
    logger.info("Esperando a que el iframe del justificante este cargado...")
    
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
    
    logger.info(f"URL del justificante extraida: {url}")
    return str(url)


async def _descargar_pdf_desde_url(page: Page, url: str, destino: Path) -> None:
    """
    Descarga el PDF ejecutando un fetch desde el navegador para mantener la sesión.
    
    Este método usa fetch() dentro del contexto del navegador, lo que permite:
    - Mantener las cookies de sesión activas
    - Descargar el PDF original sin necesidad de impresión virtual
    - Evitar problemas de navegación y timeouts
    
    Args:
        page: Página de Playwright
        url: URL del justificante
        destino: Ruta donde guardar el PDF temporalmente
    """
    logger.info(f"Descargando justificante via fetch interno desde: {url}")
    
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
        base64_data = await page.evaluate(js_download_script, url)
        
        # Decodificar y guardar el PDF
        import base64
        pdf_bytes = base64.b64decode(base64_data)
        
        with open(destino, "wb") as f:
            f.write(pdf_bytes)
        
        file_size = destino.stat().st_size
        logger.info(f"OK Archivo recuperado con exito ({file_size} bytes)")
        
        # Validación de tamaño
        if file_size < 2000:
            logger.warning("WARN El archivo es sospechosamente pequeno, revisa el contenido.")
        
    except Exception as e:
        logger.error(f"Error en la descarga por fetch: {e}")
        raise RuntimeError(f"No se pudo descargar el PDF por fetch: {e}") from e


def _construir_ruta_recursos_telematicos(payload: dict, fase_procedimiento: str | None = None) -> Path:
    """
    Construye la ruta a la subcarpeta específica dentro de RECURSOS TELEMATICOS.
    
    Args:
        payload: Diccionario con datos del trámite (incluye mandatario)
        fase_procedimiento: Valor de FaseProcedimiento para determinar la subcarpeta
    
    Returns:
        Path a la subcarpeta específica dentro de RECURSOS TELEMATICOS
    """
    logger.info("Construyendo ruta a carpeta RECURSOS TELEMATICOS...")
    
    ruta = resolve_receipt_dir_from_payload(
        payload=payload,
        fase_procedimiento=str(fase_procedimiento or "").strip() or None,
    )
    logger.info(f"Ruta RECURSOS TELEMATICOS: {ruta}")
    return ruta


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
    filename = build_receipt_filename(
        expediente=num_expediente,
        template="JUSTIFICANTE {expediente}.pdf",
    )

    try:
        ruta_final = save_receipt_from_tmp(
            tmp_path=temporal,
            destino_dir=destino_dir,
            filename=filename,
        )
    except Exception as e:
        logger.error(f"Error al copiar justificante: {e}")
        raise RuntimeError(f"No se pudo copiar el justificante al cliente: {e}") from e
    
    logger.info(f"OK Justificante guardado en: {ruta_final}")
    return ruta_final


async def descargar_y_guardar_justificante(page: Page, payload: dict) -> str:
    """
    Descarga el justificante de registro y lo guarda en la carpeta del cliente.
    
    Usa fetch() en el contexto del navegador para mantener la sesión activa
    y descargar el PDF original sin necesidad de impresión virtual.
    
    Args:
        page: Página de Playwright (debe estar en la URL del justificante)
        payload: Diccionario con datos del trámite
    
    Returns:
        Ruta absoluta del justificante guardado
    
    Raises:
        ValueError: Si faltan datos necesarios en el payload
        RuntimeError: Si falla la descarga o guardado del justificante
    """
    logger.info("=== Iniciando descarga del justificante (MODO FETCH) ===")
    
    # Verificar que estamos en la página correcta
    if "TramitaJustif" not in page.url:
        raise RuntimeError(
            f"No estamos en la página del justificante. URL actual: {page.url}"
        )
    
    # Extraer y LIMPIAR el número de expediente
    raw_expediente = payload.get("expediente_num") or payload.get("denuncia_num")
    if not raw_expediente:
        raise ValueError("Falta 'expediente_num' o 'denuncia_num' en el payload")
    
    # Reemplazar / y \ por guiones para que Windows no los interprete como carpetas
    num_expediente = str(raw_expediente).replace("/", "-").replace("\\", "-").strip()
    logger.info(f"Numero de expediente procesado: {num_expediente}")
    
    # Extraer FaseProcedimiento del payload para determinar la subcarpeta
    fase_procedimiento = payload.get("fase_procedimiento")
    if not fase_procedimiento:
        logger.warning("No se encontro 'fase_procedimiento' en el payload")
    else:
        logger.info(f"fase_procedimiento extraido del payload: '{fase_procedimiento}'")
    
    try:
        # 1. Esperar a que el iframe esté cargado
        await _esperar_iframe_cargado(page)
        
        # 2. Extraer URL del justificante
        url_justificante = await _obtener_url_justificante(page)
        
        # 3. Construir ruta de destino (con subcarpeta según motivo)
        ruta_recursos = _construir_ruta_recursos_telematicos(payload, fase_procedimiento)
        
        # 4. Descargar a archivo temporal (nombre limpio para evitar problemas)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        temporal = Path("tmp") / f"temp_justif_{num_expediente}_{ts}.pdf"
        temporal.parent.mkdir(parents=True, exist_ok=True)
        
        await _descargar_pdf_desde_url(page, url_justificante, temporal)
        
        # 5. Renombrar y mover a carpeta final
        ruta_final = _renombrar_y_mover_justificante(
            temporal, num_expediente, ruta_recursos
        )
        
        logger.info(f"OK Proceso completado: {ruta_final}")
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
