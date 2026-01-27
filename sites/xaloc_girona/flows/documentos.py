"""
Flujo de subida de documentos (adjuntos) vía popup uploader.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Sequence, Union

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, TimeoutError

DELAY_MS = 500


def _normalizar_archivos(archivos: Union[None, Path, Sequence[Path]]) -> List[Path]:
    if archivos is None:
        return []
    if isinstance(archivos, Path):
        return [archivos]
    return [a for a in archivos if a is not None]


def _validar_extension(archivo: Path) -> None:
    ext = archivo.suffix.lower().lstrip(".")
    if ext not in {"jpg", "jpeg", "pdf"}:
        raise ValueError(f"Extensión no permitida: {archivo.name} (solo jpg, jpeg, pdf)")


async def _siguiente_input_vacio(popup: Page) -> Optional[int]:
    inputs = popup.locator("input[type='file']")
    count = await inputs.count()
    for i in range(count):
        try:
            vacio = await inputs.nth(i).evaluate("(el) => !el.files || el.files.length === 0")
            if vacio:
                return i
        except Exception:
            continue
    return None


async def _seleccionar_archivos(popup: Page, archivos: List[Path]) -> None:
    # 1. Esperar a que el popup cargue realmente
    await popup.wait_for_load_state("networkidle")
    
    # 2. Intentar encontrar el frame de subida (STA suele usar frames)
    # Buscamos en todos los frames disponibles si el input no está en el principal
    target = popup
    if len(popup.frames) > 1:
        for frame in popup.frames:
            if "upload" in frame.url.lower() or "adjuntar" in frame.url.lower():
                target = frame
                logging.info(f"Frame de subida detectado: {frame.url}")
                break

    # 3. Esperar al selector con un timeout generoso
    try:
        selector = "input[type='file']"
        await target.wait_for_selector(selector, state="attached", timeout=30000)
    except TimeoutError:
        logging.error("No se encontró el input de archivos. ¿El popup está en blanco?")
        # Debug: Captura de pantalla del popup para ver qué hay realmente
        await popup.screenshot(path="debug_popup_error.png")
        raise

    # 4. Subida de archivos
    for archivo in archivos:
        # Buscamos el primer input que esté vacío
        inputs = target.locator("input[type='file']")
        count = await inputs.count()
        
        input_index = None
        for i in range(count):
            vacio = await inputs.nth(i).evaluate("(el) => !el.files || el.files.length === 0")
            if vacio:
                input_index = i
                break
        
        if input_index is None:
            raise RuntimeError("No hay más huecos libres para subir archivos en este popup.")
            
        await inputs.nth(input_index).set_input_files(archivo)
        await popup.wait_for_timeout(DELAY_MS)

async def _click_link(popup: Page, patron: str) -> None:
    link = popup.get_by_role("link", name=re.compile(patron, re.IGNORECASE)).first
    await link.wait_for(state="visible", timeout=20000)
    await link.click()
    try:
        await popup.wait_for_timeout(DELAY_MS)
    except PlaywrightError:
        return


async def _wait_upload_ok(popup: Page) -> None:
    # En popup.html el estado se escribe en <div id="uploadResultado">... Document adjuntat</div>
    try:
        await popup.wait_for_function(
            """() => {
                const el = document.getElementById('uploadResultado');
                if (!el) return false;
                return /Document\\s+adjuntat/i.test(el.textContent || '');
            }""",
            timeout=60000,
        )
    except Exception:
        # Fallback suave: si no existe el div (variantes), no bloqueamos indefinidamente.
        await popup.wait_for_timeout(500)


async def _adjuntar_y_continuar(popup: Page, *, espera_cierre: bool = False) -> None:
    # En popup.html el CTA es un <a> con texto "Clicar per adjuntar"
    await _click_link(popup, r"^Clicar per adjuntar")
    await _wait_upload_ok(popup)

    # Tras adjuntar, aparece "Continuar"
    continuar = popup.get_by_role("link", name=re.compile(r"^Continuar$", re.IGNORECASE)).first
    await continuar.wait_for(state="visible", timeout=20000)

    if espera_cierre:
        try:
            async with popup.expect_event("close", timeout=15000):
                await continuar.click()
        except TimeoutError:
            try:
                await continuar.click()
            except PlaywrightError:
                return
    else:
        await continuar.click()
        try:
            await popup.wait_for_load_state("domcontentloaded")
        except PlaywrightError:
            return


async def subir_documento(page: Page, archivo: Union[None, Path, Sequence[Path]]) -> None:
    """
    Sube uno o varios documentos adjuntos al trámite.

    Para múltiples documentos: selecciona cada archivo en el siguiente "Tria el fitxer"
    (siguiente input <type=file> vacío), y solo al final pulsa "Clicar per adjuntar".
    """

    archivos = _normalizar_archivos(archivo)
    if not archivos:
        logging.info("Sin archivos para adjuntar, saltando...")
        return

    for a in archivos:
        if not a.exists():
            raise FileNotFoundError(str(a))
        _validar_extension(a)

    logging.info(f"Adjuntando {len(archivos)} documento(s)")
    
    # Verify page is still valid
    try:
        if page.is_closed():
            logging.error("ERROR: La página está cerrada antes de subir documentos!")
            return
    except Exception as e:
        logging.error(f"ERROR: No se puede verificar el estado de la página: {e}")
        return
    
    # Wait for page stability
    try:
        await page.wait_for_timeout(1000)
    except Exception as e:
        logging.error(f"ERROR: Página cerrada durante la espera inicial: {e}")
        # Try to get current URL for debugging
        try:
            logging.error(f"URL actual (si disponible): {page.url}")
        except:
            pass
        return

    docs_link = page.locator("a.docs").first
    if await docs_link.count() == 0:
         logging.warning("No se encuentra el enlace de adjuntar documentos (a.docs)")
         # Try to debug/dump
         try:
             content = await page.content()
             logging.debug(f"HTML Content snip: {content[:500]}")
         except Exception as e:
             logging.error(f"No se pudo obtener el contenido de la página: {e}")
         return

    popup: Optional[Page] = None
    try:
        async with page.expect_popup(timeout=7000) as popup_info:
            await docs_link.click()
        popup = await popup_info.value
    except TimeoutError:
        popup = None

    if popup is None:
        # Fallback: si no hay popup, intentamos en la misma página.
        await page.wait_for_timeout(DELAY_MS)
        await _seleccionar_archivos(page, archivos)
        await _adjuntar_y_continuar(page, espera_cierre=False)
    else:
        try:
            await popup.wait_for_load_state("domcontentloaded")
        except PlaywrightError:
            pass
        await _seleccionar_archivos(popup, archivos)
        await _adjuntar_y_continuar(popup, espera_cierre=True)
        try:
            if not popup.is_closed():
                await popup.close()
        except PlaywrightError:
            pass

    # Espera corta a que el STA reciba el resultado del uploader (evitamos 'networkidle', suele ser lento).
    try:
        await page.wait_for_timeout(DELAY_MS)
    except PlaywrightError:
        return
    logging.info("Documentos subidos")


__all__ = ["subir_documento"]
