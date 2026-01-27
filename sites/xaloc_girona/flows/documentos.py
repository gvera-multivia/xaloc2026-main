"""
Flujo de subida de documentos (adjuntos) vía popup uploader.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Sequence, Union

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame
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


async def _resolver_contexto_uploader(popup: Page) -> Page | Frame:
    """
    En STA el uploader puede estar en la página principal del popup o en un iframe.
    Elegimos el contexto que realmente contiene los inputs de archivo y (si existe) los CTAs.
    """
    candidates: list[Page | Frame] = [popup]
    for fr in popup.frames:
        if fr == popup.main_frame:
            continue
        candidates.append(fr)

    best: Page | Frame | None = None
    best_score = -1
    for ctx in candidates:
        try:
            inputs_count = await ctx.locator("input[type='file']").count()
        except Exception:
            continue

        score = inputs_count

        try:
            if await ctx.locator("a", has_text=re.compile(r"^Clicar per adjuntar", re.IGNORECASE)).count() > 0:
                score += 10
            if await ctx.locator("#continuar a", has_text=re.compile(r"^Continuar$", re.IGNORECASE)).count() > 0:
                score += 5
        except Exception:
            pass

        try:
            url = (ctx.url or "").lower()
            if "upload" in url or "adjuntar" in url:
                score += 3
        except Exception:
            pass

        if score > best_score:
            best = ctx
            best_score = score

    if best is None:
        return popup

    try:
        logging.info(f"Contexto uploader seleccionado: {best.url}")
    except Exception:
        pass
    return best


async def _seleccionar_archivos(popup: Page, archivos: List[Path]) -> Page | Frame:
    # 1. Esperar a que el popup cargue realmente
    # Usamos 'domcontentloaded' para asegurar que la URL ha empezado a cargar
    await popup.wait_for_load_state("domcontentloaded", timeout=15000)
    
    # 2. LOCALIZAR CONTEXTO REAL DEL UPLOADER (page o iframe)
    target = await _resolver_contexto_uploader(popup)

    # 3. Esperar al selector de archivos (aumentamos a 30s)
    selector = "input[type='file']"
    try:
        await target.wait_for_selector(selector, state="attached", timeout=30000)
    except TimeoutError:
        logging.error("No se encontró el input[type='file'] en el popup/frame.")
        await popup.screenshot(path="error_popup_vacio.png")
        raise

    # 4. Subida de archivos - IMPORTANTE: El botón "Clicar per adjuntar" solo se puede
    #    usar UNA VEZ después de seleccionar TODOS los archivos
    #    
    #    Flujo correcto:
    #    1. Seleccionar archivo 1
    #    2. Seleccionar archivo 2
    #    3. Seleccionar archivo N
    #    4. UNA SOLA VEZ: Hacer clic en "Clicar per adjuntar"
    #    5. Esperar confirmación
    
    logging.info(f"Seleccionando {len(archivos)} archivo(s)...")
    
    for idx, archivo in enumerate(archivos, 1):
        logging.info(f"Seleccionando archivo {idx}/{len(archivos)}: {archivo.name}")
        
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
        
        # Seleccionar el archivo
        logging.info(f"Archivo seleccionado en input[{input_index}]")
        await inputs.nth(input_index).set_input_files(archivo)
        # Confirmar que el input retuvo el archivo (evita falsos positivos en logs)
        try:
            files_len = await inputs.nth(input_index).evaluate("(el) => (el.files ? el.files.length : 0)")
            if int(files_len or 0) <= 0:
                raise RuntimeError(f"El input[{input_index}] no retuvo el archivo tras set_input_files()")
        except Exception as e:
            logging.error(f"Selección no confirmada en input[{input_index}]: {e}")
            raise
        # Espera corta entre selecciones de archivos
        await popup.wait_for_timeout(500)
    
    logging.info(f"Todos los archivos seleccionados ({len(archivos)}). Ahora haciendo clic en 'Clicar per adjuntar'...")
    
    # CRÍTICO: Hacer clic en "Clicar per adjuntar" UNA SOLA VEZ después de seleccionar TODOS
    await popup.wait_for_timeout(1000)  # Espera para que el popup procese todas las selecciones
    await _click_link(target, r"^Clicar per adjuntar")
    logging.info("Click en 'Clicar per adjuntar' ejecutado")
    
    # Espera larga para que el JavaScript del popup procese la subida de TODOS los archivos
    await popup.wait_for_timeout(2000)
    
    # Esperar confirmación de que los archivos se subieron correctamente
    logging.info("Esperando confirmación de subida...")
    await _wait_upload_ok(target)
    logging.info(f"Todos los archivos ({len(archivos)}) subidos correctamente")
    return target

async def _click_link(ctx: Page | Frame, patron: str) -> None:
    link = ctx.locator("a", has_text=re.compile(patron, re.IGNORECASE)).first
    await link.wait_for(state="visible", timeout=20000)
    await link.click()
    try:
        page = ctx if isinstance(ctx, Page) else ctx.page
        await page.wait_for_timeout(DELAY_MS)
    except PlaywrightError:
        return


async def _wait_upload_ok(ctx: Page | Frame) -> None:
    # En popup.html el estado se escribe en <div id="uploadResultado">... Document adjuntat</div>
    page = ctx if isinstance(ctx, Page) else ctx.page

    # Si no existe el indicador, no podemos validar por texto: damos un margen y seguimos.
    try:
        await ctx.wait_for_selector("#uploadResultado", state="attached", timeout=5000)
    except TimeoutError:
        await page.wait_for_timeout(1000)
        return

    # Si existe, entonces SÍ exigimos ver el OK para evitar "falsos verdes".
    await ctx.wait_for_function(
        """() => {
            const el = document.getElementById('uploadResultado');
            if (!el) return false;
            return /Document\\s+adjuntat/i.test(el.textContent || '');
        }""",
        timeout=60000,
    )


async def _adjuntar_y_continuar(popup: Page, *, ctx: Page | Frame, espera_cierre: bool = False) -> None:
    # Los archivos ya se adjuntaron en _seleccionar_archivos
    # Aquí solo necesitamos hacer clic en "Continuar" para cerrar el popup
    
    # CRÍTICO: Esperar a que el popup procese completamente los archivos subidos
    # El popup usa Ajax para subir archivos de forma asíncrona, así que debemos
    # esperar a que aparezca el mensaje "Document adjuntat" antes de continuar
    logging.info("Esperando a que el popup procese completamente los archivos...")
    try:
        await ctx.wait_for_function(
            """() => {
                const resultado = document.getElementById('uploadResultado');
                if (!resultado) return false;
                return resultado.textContent.includes('Document adjuntat');
            }""",
            timeout=30000
        )
        logging.info("Archivos procesados correctamente por el popup")
    except Exception as e:
        logging.warning(f"No se pudo confirmar el mensaje de subida: {e}")
    
    # CRÍTICO: NO esperar mucho tiempo aquí porque el popup se cierra automáticamente
    # Hacer clic en "Continuar" INMEDIATAMENTE para guardar los documentos
    logging.info("Buscando botón 'Continuar' inmediatamente...")
    
    # DIAGNÓSTICO: Verificar que los archivos estén correctamente en los inputs
    try:
        file_values = await ctx.evaluate("""() => {
            const inputs = document.querySelectorAll('input[type="file"]');
            const values = [];
            inputs.forEach((input, i) => {
                values.push({
                    index: i,
                    value: input.value,
                    files: input.files ? input.files.length : 0
                });
            });
            return values;
        }""")
        logging.info(f"Estado de inputs de archivo: {file_values}")
        
        # Verificar que al menos un input tenga archivos
        has_files = any(f['files'] > 0 for f in file_values)
        if not has_files:
            logging.error("¡CRÍTICO! Los inputs de archivo están vacíos antes de hacer clic en Continuar")
            logging.error("Esto explica por qué los documentos no se guardan")
    except Exception as e:
        logging.warning(f"No se pudo verificar el estado de los inputs: {e}")
    
    try:
        continuar = ctx.locator("#continuar a").first
        if await continuar.count() == 0:
            continuar = ctx.locator("a", has_text=re.compile(r"^Continuar$", re.IGNORECASE)).first

        # Fallback si el botón no está en el contexto elegido (p.ej. iframe)
        if await continuar.count() == 0:
            continuar = popup.locator("#continuar a").first
            if await continuar.count() == 0:
                continuar = popup.locator("a", has_text=re.compile(r"^Continuar$", re.IGNORECASE)).first

        await continuar.wait_for(state="visible", timeout=5000)
        logging.info("Botón 'Continuar' visible")
        
        # Pequeña espera para que el botón esté listo
        await popup.wait_for_timeout(500)

        if espera_cierre:
            logging.info("Haciendo clic FÍSICO en el botón 'Continuar'...")
            try:
                async with popup.expect_event("close", timeout=15000):
                    # CRÍTICO: Hacer clic FÍSICO en el botón para que el onclick se dispare
                    # y la comunicación con opener funcione correctamente
                    await continuar.click(force=True)
                    logging.info("Clic en 'Continuar' ejecutado")
                logging.info("Popup cerrado correctamente")
            except TimeoutError:
                logging.warning("Timeout esperando cierre del popup, intentando de nuevo...")
                try:
                    await continuar.click(force=True)
                    await popup.wait_for_timeout(1000)
                except PlaywrightError:
                    return
        else:
            logging.info("Haciendo clic FÍSICO en el botón 'Continuar'...")
            await continuar.click(force=True)
            try:
                await popup.wait_for_load_state("domcontentloaded")
            except PlaywrightError:
                pass
    except Exception as e:
        logging.error(f"Error al hacer clic en Continuar: {e}")
        # Si el popup ya se cerró, no hay problema
        if "closed" in str(e).lower():
            logging.warning("El popup se cerró automáticamente antes de hacer clic en Continuar")
        else:
            raise
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

    # DIAGNÓSTICO: Buscar el enlace de adjuntar documentos
    logging.info("Buscando enlace 'Adjuntar i signar'...")
    
    link_count = await page.locator("a.docs").count()
    logging.info(f"Enlaces encontrados con selector 'a.docs': {link_count}")
    
    if link_count == 0:
         logging.error("CRÍTICO: No se encuentra ningún enlace de adjuntar documentos")
         try:
             content = await page.content()
             with open("debug_page_content.html", "w", encoding="utf-8") as f:
                 f.write(content)
             logging.info("Contenido HTML guardado en debug_page_content.html")
         except Exception as e:
             logging.error(f"No se pudo obtener el contenido de la página: {e}")
         return

    # NOTA: El botón está oculto por CSS, así que no intentamos scroll ni verificar visibilidad
    # Vamos directamente al click con JavaScript que es lo que funciona
    logging.info("Intentando hacer click en 'Adjuntar i signar'...")
    popup: Optional[Page] = None
    
    # INTENTO 1: Click Playwright (force=True) para mantener gesto de usuario (window.opener)
    logging.info("Usando click Playwright(force=True) (botón oculto por CSS)...")
    try:
        async with page.expect_popup(timeout=10000) as popup_info_click:
            await page.locator("a.docs").first.click(force=True)
            logging.info("Click Playwright ejecutado.")
        popup = await popup_info_click.value
        logging.info(f"Popup detectado vía click: {popup.url if popup else 'None'}")
    except TimeoutError:
        logging.warning("Timeout: El popup no se abrió tras click Playwright; probando click JavaScript...")
        try:
            async with page.expect_popup(timeout=10000) as popup_info_js:
                await page.evaluate("document.querySelector('a.docs').click()")
                logging.info("Click JavaScript ejecutado.")
            popup = await popup_info_js.value
            logging.info(f"Popup detectado vía JS: {popup.url if popup else 'None'}")
        except TimeoutError:
            logging.error("Timeout: El popup no se abrió tras click JavaScript.")
            popup = None
    except Exception as e:
        logging.error(f"Error abriendo popup: {e}")
        popup = None


    if popup is None:
        logging.error("CRÍTICO: No se pudo abrir la ventana de adjuntos después de todos los intentos.")
        raise RuntimeError("No se pudo abrir la ventana de adjuntos.")
    
    # Si llegamos aquí, el popup se abrió correctamente
    logging.info("Popup detectado correctamente, procediendo con subida...")
    try:
        await popup.wait_for_load_state("domcontentloaded")
    except PlaywrightError:
        pass

    # Diagnóstico crítico: sin opener, el popup puede cerrar sin "devolver" los docs al formulario principal
    try:
        has_opener = await popup.evaluate("() => !!window.opener && !window.opener.closed")
        logging.info(f"Popup tiene window.opener: {has_opener}")
        if not has_opener:
            logging.warning("El popup no tiene window.opener; 'Continuar' puede cerrar sin adjuntar documentos.")
    except Exception as e:
        logging.warning(f"No se pudo comprobar window.opener en popup: {e}")

    ctx = await _seleccionar_archivos(popup, archivos)
    await _adjuntar_y_continuar(popup, ctx=ctx, espera_cierre=True)
    
    # IMPORTANTE: NO cerramos el popup manualmente aquí
    # El botón "Continuar" ya lo cerró y guardó los documentos en el formulario principal
    # Si lo cerramos manualmente, se pierden los documentos adjuntados
    logging.info("Popup cerrado por el botón 'Continuar'")


    # CRÍTICO: Espera larga después de cerrar el popup para que la página principal
    # tenga tiempo de procesar que los documentos se adjuntaron correctamente.
    # Si continuamos demasiado rápido, la página no registra los documentos.
    logging.info("Esperando a que la página principal procese los documentos adjuntados...")
    try:
        await page.wait_for_timeout(3000)  # 3 segundos para que STA procese
    except PlaywrightError:
        return
    
    # Screenshot para verificar que los documentos se adjuntaron correctamente
    try:
        await page.screenshot(path="debug_after_upload.png")
        logging.info("Screenshot guardado: debug_after_upload.png")
    except Exception as e:
        logging.warning(f"No se pudo guardar screenshot: {e}")
    
    logging.info("Documentos subidos y procesados por la página principal")


__all__ = ["subir_documento"]
