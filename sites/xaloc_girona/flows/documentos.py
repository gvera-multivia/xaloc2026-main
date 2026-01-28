"""
Flujo de subida de documentos (adjuntos) vía popup uploader.
"""

from __future__ import annotations

import logging
import re
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import List, Optional, Sequence, Union

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame
from playwright.async_api import Page, TimeoutError

DELAY_MS = 500
POPUP_TIMEOUT_MS = 15000
UPLOADS_TRANSIT_DIR = Path("tmp/web_uploads")


def _attach_gemini_console_logger(page: Page) -> None:
    """
    Captura console.log del navegador para diagnóstico remoto.
    Solo registra mensajes que empiecen por 'GEMINI_DEBUG:'.
    """
    try:
        # Evitar duplicar listeners si se llama más de una vez.
        if getattr(page, "_gemini_console_logger_attached", False):
            return
        setattr(page, "_gemini_console_logger_attached", True)
    except Exception:
        # Si Playwright/objetos proxied no permiten atributos, ignoramos.
        return

    def _on_console(msg):  # type: ignore[no-untyped-def]
        try:
            text = msg.text()
            if isinstance(text, str) and text.startswith("GEMINI_DEBUG:"):
                logging.info(text)
        except Exception:
            return

    page.on("console", _on_console)


async def _install_sta_main_hooks(page: Page) -> None:
    """
    Instala hooks en la página principal ANTES de abrir el popup.
    El popup llama a funciones del opener (p.ej. addDocumentoLista), y queremos ver sus argumentos.
    """
    try:
        await page.evaluate(
            """() => {
                if (window.__GEMINI_STA_HOOKS_INSTALLED) return;
                window.__GEMINI_STA_HOOKS_INSTALLED = true;

                function installHook(fnName) {
                    function wrapAndLog(fn) {
                        return function() {
                            try {
                                console.log('GEMINI_DEBUG: ' + fnName + '_args ' + JSON.stringify(Array.from(arguments)));
                            } catch (e) {}
                            try {
                                const res = fn.apply(this, arguments);
                                try {
                                    console.log('GEMINI_DEBUG: ' + fnName + '_ok');
                                } catch (e) {}
                                return res;
                            } catch (e) {
                                try {
                                    console.log('GEMINI_DEBUG: ' + fnName + '_throw ' + String(e && e.message ? e.message : e));
                                } catch (e2) {}
                                throw e;
                            }
                        };
                    }

                    try {
                        const existing = window[fnName];
                        if (typeof existing === 'function') {
                            window[fnName] = wrapAndLog(existing);
                            console.log('GEMINI_DEBUG: hook_installed ' + fnName + ' (direct)');
                            return;
                        }
                    } catch (e) {}

                    // Si aún no existe, definimos setter para envolver cuando se asigne.
                    try {
                        let current;
                        Object.defineProperty(window, fnName, {
                            configurable: true,
                            enumerable: true,
                            get: () => current,
                            set: (v) => {
                                try {
                                    if (typeof v === 'function') {
                                        current = wrapAndLog(v);
                                        console.log('GEMINI_DEBUG: hook_installed ' + fnName + ' (setter)');
                                    } else {
                                        current = v;
                                    }
                                } catch (e) {
                                    current = v;
                                }
                            },
                        });
                        console.log('GEMINI_DEBUG: hook_waiting ' + fnName);
                    } catch (e) {
                        console.log('GEMINI_DEBUG: hook_failed ' + fnName + ' ' + String(e && e.message ? e.message : e));
                    }
                }

                // Funciones relevantes para el puente popup -> opener
                installHook('addDocumentoLista');
                installHook('openUploader');
            }"""
        )
    except Exception as e:
        logging.warning(f"No se pudo instalar hooks STA en la página principal: {e}")


def _sta_sanitize_filename(name: str) -> str:
    # Mismo sanitize que en el JS del popup: fileName.replace(/[^a-zA-Z0-9-_\.]/g, '')
    return re.sub(r"[^a-zA-Z0-9\-_.]", "", name or "")


def _preparar_copias_sanitizadas(archivos_originales: List[Path]) -> tuple[List[Path], Path]:
    """
    Copia los archivos a una carpeta temporal con nombres 100% compatibles con STA
    (misma sanitización que aplica el popup al construir la lista de archivos).
    """
    run_dir = UPLOADS_TRANSIT_DIR / f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    archivos_limpios: list[Path] = []
    for i, ruta_orig in enumerate(archivos_originales, 1):
        nombre_limpio = _sta_sanitize_filename(ruta_orig.name)
        if not nombre_limpio:
            nombre_limpio = f"file_{i}"

        destino = run_dir / nombre_limpio
        # Evitar colisiones si dos ficheros acaban con el mismo nombre sanitizado
        if destino.exists():
            destino = run_dir / f"{i}_{nombre_limpio}"

        shutil.copy2(ruta_orig, destino)
        logging.info(f"[UPLOAD_TRANSIT] Copia temporal: {ruta_orig} -> {destino.name}")
        archivos_limpios.append(destino)

    return archivos_limpios, run_dir


async def _debug_dump_popup_state(ctx: Page | Frame, *, label: str, expected_files: list[str]) -> None:
    """
    Log (Python + console) del estado del popup/iframe, para diagnosticar por qué desaparecen adjuntos.
    """
    try:
        state = await ctx.evaluate(
            """({ label, expectedFiles }) => {
                const safeText = (el) => (el && (el.textContent || '') || '').trim();
                const safeStyle = (el) => {
                    if (!el) return null;
                    const cs = window.getComputedStyle(el);
                    return {
                        display: cs.display,
                        visibility: cs.visibility,
                        opacity: cs.opacity,
                        pointerEvents: cs.pointerEvents,
                    };
                };

                const inputs = Array.from(document.querySelectorAll('input[type="file"]')).map((input) => {
                    const files = input.files ? Array.from(input.files).map((f) => ({ name: f.name, size: f.size })) : [];
                    return {
                        id: input.id || null,
                        name: input.name || null,
                        value: input.value || '',
                        filesCount: files.length,
                        files,
                    };
                });

                const uploadResultado = document.getElementById('uploadResultado');
                const continuarDiv = document.getElementById('continuar');
                const fileHidden = document.getElementById('file');

                const expectedPresence = (expectedFiles || []).map((f) => ({
                    file: f,
                    inAnyInputValue: inputs.some((i) => (i.value || '').toLowerCase().includes(String(f).toLowerCase())),
                    inAnyFileName: inputs.some((i) => (i.files || []).some((ff) => (ff.name || '').toLowerCase().includes(String(f).toLowerCase()))),
                }));

                const payload = {
                    label,
                    url: String(document.location),
                    inputs,
                    uploadResultado: {
                        text: safeText(uploadResultado),
                        style: safeStyle(uploadResultado),
                    },
                    continuar: {
                        style: safeStyle(continuarDiv),
                        hasLink: !!(continuarDiv && continuarDiv.querySelector('a')),
                    },
                    hiddenFile: fileHidden ? { value: fileHidden.value || '' } : null,
                    expectedPresence,
                };

                console.log('GEMINI_DEBUG: popup_state ' + JSON.stringify(payload));
                return payload;
            }""",
            {"label": label, "expectedFiles": expected_files},
        )
        logging.info(f"[POPUP_STATE] {label}: inputs={len(state.get('inputs', []))}, continuar={state.get('continuar')}")
    except Exception as e:
        logging.warning(f"No se pudo dumpear estado del popup ({label}): {e}")


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
            if await ctx.locator("a[onclick*='uploadFile']").count() > 0:
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
    
    expected_names = [a.name for a in archivos]
    await _debug_dump_popup_state(target, label="before_select", expected_files=expected_names)
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
        # Disparar lógica STA (algunos inputs se crean dinámicamente y el onchange puede fallar)
        try:
            await inputs.nth(input_index).evaluate(
                """(el) => {
                    try {
                        if (typeof stepAfterSelect === 'function') stepAfterSelect(el);
                    } catch (e) {}
                }"""
            )
        except Exception:
            pass
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

        await _debug_dump_popup_state(target, label=f"after_select_{idx}", expected_files=expected_names)
    
    logging.info(f"Todos los archivos seleccionados ({len(archivos)}). Ahora haciendo clic en 'Clicar per adjuntar'...")
    
    # CRÍTICO: Hacer clic en "Clicar per adjuntar" UNA SOLA VEZ después de seleccionar TODOS
    await popup.wait_for_timeout(1000)  # Espera para que el popup procese todas las selecciones
    await _debug_dump_popup_state(target, label="before_click_adjuntar", expected_files=expected_names)
    await _click_cta_adjuntar(target)
    logging.info("Click en 'Clicar per adjuntar' ejecutado")
    await _debug_dump_popup_state(target, label="after_click_adjuntar", expected_files=expected_names)
    
    # Espera larga para que el JavaScript del popup procese la subida de TODOS los archivos
    await popup.wait_for_timeout(2000)
    
    # Esperar confirmación de que los archivos se subieron correctamente
    logging.info("Esperando confirmación de subida...")
    await _wait_upload_ok(target)
    logging.info(f"Todos los archivos ({len(archivos)}) subidos correctamente")
    await _debug_dump_popup_state(target, label="after_upload_ok", expected_files=expected_names)
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

async def _click_cta_adjuntar(ctx: Page | Frame) -> None:
    """
    En el popup hay varios enlaces con el mismo texto "Clicar per adjuntar":
    - el de adjuntar (onclick uploadFile) suele ser el correcto
    - el de firma (onclick procesoFirma) puede estar oculto (display:none)
    Por eso NO podemos basarnos solo en el texto ni en `visible`.
    """
    candidates = [
        "#adjuntar a[onclick*='uploadFile']",
        "a[onclick*='uploadFile']",
        "#firmaBoton a[onclick*='procesoFirma']",
        "a[onclick*='procesoFirma']",
    ]

    for css in candidates:
        loc = ctx.locator(css).first
        try:
            if await loc.count() <= 0:
                continue
            await loc.wait_for(state="attached", timeout=20000)
            # click via DOM to bypass visibility constraints (STA oculta/mostrar por CSS)
            await loc.evaluate(
                """(el) => {
                    try { el.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    el.click();
                }"""
            )
            return
        except Exception:
            continue

    # Último fallback: por texto (puede dar el oculto, pero al menos deja trazas)
    await _click_link(ctx, r"^Clicar per adjuntar")


async def _adjuntar_y_continuar(popup: Page, *, ctx: Page | Frame, espera_cierre: bool = False) -> None:
    """
    Versión final: Fuerza el registro técnico y el refresco visual en la página principal.
    """
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
        logging.info("Archivos procesados correctamente por el servidor del popup")
    except Exception as e:
        logging.warning(f"No se pudo confirmar el mensaje visual de éxito en el popup: {e}")

    # 1. Obtener parámetros del uploader y nombres de archivos REALES del popup
    # Usamos los nombres que el servidor ya ha aceptado y que aparecen en los inputs.
    popup_params = await popup.evaluate("""() => {
        const params = new URLSearchParams(window.location.search);
        const fileInputs = Array.from(document.querySelectorAll('input[type="file"]'));
        const names = fileInputs.map(i => i.value.split(/[\\\\/]/).pop()).filter(Boolean);
        
        return {
            tipoDocumento: params.get('tipoDocumento') || '',
            personDBOID: params.get('personDBOID') || '',
            firma: params.get('firma') || 'S',
            filesList: names.join('|'),
            filesDisplay: names.join(', ')
        };
    }""")

    if not popup_params['filesList']:
        logging.error("¡CRÍTICO! No hay nombres de archivos detectados en el popup antes de cerrar.")
        return

    # 2. EJECUCIÓN MAESTRA: Sincronización técnica + Parche visual del DOM
    # Inyectamos código en el popup para que actúe sobre su 'window.opener' (la página principal).
    logging.info(f"[STA_FORCE] Sincronizando {popup_params['filesList']} con la página principal...")
    
    await popup.evaluate("""(p) => {
        try {
            if (!window.opener || window.opener.closed) return;
            const o = window.opener;

            // A. Registro técnico (lo que permite avanzar de fase)
            o.addDocumentoLista(
                p.tipoDocumento, p.filesList, p.firma, 
                '', '', '', p.personDBOID, 
                false, '', '', 'false', null, 'true'
            );
            console.log('GEMINI_DEBUG: addDocumentoLista_forced enviado');

            // B. Refresco visual forzado (Para eliminar el "(pendent)")
            const refreshFns = ['actualizarEstadoDoc', 'recargarDocumentos', 'recargarTablaDocs'];
            refreshFns.forEach(fn => {
                if (typeof o[fn] === 'function') o[fn](p.tipoDocumento);
            });

            // C. CIRUGÍA DOM (Si el JS de la web falla, nosotros borramos el texto rojo)
            const statusId = 'Status' + p.tipoDocumento + '_NEW';
            const cell = o.document.getElementById(statusId);
            if (cell) {
                // Borramos el "(pendent)" y ponemos los nombres en verde
                cell.innerHTML = '<span style="color: #28a745; font-weight: bold;">✓ ' + p.filesDisplay + '</span>';
                console.log('GEMINI_DEBUG: DOM de la página principal parcheado visualmente');
            }
        } catch (e) {
            console.error('GEMINI_DEBUG: Fallo en la comunicación popup-opener:', e);
        }
    }""", popup_params)

    # 3. Finalizar el flujo oficial de la web
    try:
        continuar = ctx.locator("a", has_text=re.compile(r"^Continuar$", re.IGNORECASE)).first
        await continuar.wait_for(state="visible", timeout=5000)
        
        if espera_cierre:
            async with popup.expect_event("close", timeout=10000):
                await continuar.click(force=True)
        else:
            await continuar.click(force=True)
            
        logging.info("Popup cerrado y datos transferidos.")
    except Exception as e:
        logging.warning(f"Error al clicar Continuar (posible cierre automático): {e}")


async def subir_documento(page: Page, archivo: Union[None, Path, Sequence[Path]]) -> None:
    """
    Sube uno o varios documentos adjuntos al trámite.

    Para múltiples documentos: selecciona cada archivo en el siguiente "Tria el fitxer"
    (siguiente input <type=file> vacío), y solo al final pulsa "Clicar per adjuntar".
    """

    archivos_originales = _normalizar_archivos(archivo)
    if not archivos_originales:
        logging.info("Sin archivos para adjuntar, saltando...")
        return

    for a in archivos_originales:
        if not a.exists():
            raise FileNotFoundError(str(a))
        _validar_extension(a)

    archivos, transit_dir = _preparar_copias_sanitizadas(archivos_originales)

    try:
        logging.info(f"Adjuntando {len(archivos)} documento(s)")
        _attach_gemini_console_logger(page)
        await _install_sta_main_hooks(page)

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
            try:
                logging.error(f"URL actual (si disponible): {page.url}")
            except Exception:
                pass
            return

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

        logging.info("Intentando hacer click en 'Adjuntar i signar'...")
        popup: Optional[Page] = None

        # Seleccionar el enlace correcto (hay múltiples a.docs en el DOM)
        try:
            idx = await page.evaluate(
                """() => {
                    const links = Array.from(document.querySelectorAll('a.docs'));
                    for (let i = 0; i < links.length; i++) {
                        const el = links[i];
                        const t = (el.textContent || '').trim().toLowerCase();
                        const oc = (el.getAttribute('onclick') || '');
                        if (t.includes('adjuntar') && oc.includes('openUploader')) return i;
                    }
                    return 0;
                }"""
            )
            await page.evaluate(
                """(i) => {
                    const el = document.querySelectorAll('a.docs')[i];
                    if (!el) return null;
                    const cs = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    console.log('GEMINI_DEBUG: docs link style ' + JSON.stringify({
                        index: i,
                        display: cs.display,
                        visibility: cs.visibility,
                        opacity: cs.opacity,
                        pointerEvents: cs.pointerEvents,
                        rect: { x: r.x, y: r.y, w: r.width, h: r.height },
                        text: (el.textContent || '').trim(),
                        onclick: (el.getAttribute('onclick') || '').slice(0, 120)
                    }));
                    return true;
                }""",
                idx,
            )
        except Exception as e:
            logging.warning(f"No se pudo resolver índice de a.docs; se usará el primero. Detalle: {e}")
            idx = 0

        logging.info("Abriendo popup con click DOM (evaluate) sobre a.docs...")
        try:
            async with page.expect_popup(timeout=POPUP_TIMEOUT_MS) as popup_info_js:
                await page.evaluate(
                    """(i) => {
                        const el = document.querySelectorAll('a.docs')[i] || document.querySelector('a.docs');
                        if (!el) throw new Error('No existe a.docs');
                        el.click();
                    }""",
                    idx,
                )
            popup = await popup_info_js.value
            logging.info(f"Popup detectado: {popup.url if popup else 'None'}")
        except TimeoutError:
            logging.error("Timeout: El popup no se abrió tras click DOM (evaluate).")
            popup = None
        except Exception as e:
            logging.error(f"Error abriendo popup (evaluate): {e}")
            popup = None

        if popup is None:
            raise RuntimeError("No se pudo abrir la ventana de adjuntos.")

        logging.info("Popup detectado correctamente, procediendo con subida...")
        try:
            await popup.wait_for_load_state("domcontentloaded")
        except PlaywrightError:
            pass
        _attach_gemini_console_logger(popup)

        try:
            has_opener = await popup.evaluate("() => !!window.opener && !window.opener.closed")
            logging.info(f"Popup tiene window.opener: {has_opener}")
            if not has_opener:
                logging.warning("El popup no tiene window.opener; 'Continuar' puede cerrar sin adjuntar documentos.")
        except Exception as e:
            logging.warning(f"No se pudo comprobar window.opener en popup: {e}")

        uploader_ctx = await _seleccionar_archivos(popup, archivos)
        await _adjuntar_y_continuar(popup, ctx=uploader_ctx, espera_cierre=True)
        logging.info("Popup cerrado por el botón 'Continuar'")

        logging.info("Esperando a que la página principal procese los documentos adjuntados...")
        try:
            await page.wait_for_timeout(3000)
        except PlaywrightError:
            return

        try:
            expected_names = [a.name for a in archivos]
            expected_names_sanitized = [_sta_sanitize_filename(n) for n in expected_names]
            expected_all = list(dict.fromkeys([*expected_names, *expected_names_sanitized]))
            presence = await page.evaluate(
                """(names) => {
                    const text = (document.body && (document.body.innerText || document.body.textContent) || '');
                    const html = (document.body && document.body.innerHTML || '');
                    const lowerText = text.toLowerCase();
                    const lowerHtml = html.toLowerCase();
                    return (names || []).map((n) => {
                        const ln = String(n).toLowerCase();
                        return { file: n, inText: lowerText.includes(ln), inHtml: lowerHtml.includes(ln) };
                    });
                }""",
                expected_all,
            )
            logging.info(f"[MAIN_AFTER_POPUP] presencia_nombres={presence}")
            await page.evaluate(
                """(presence) => {
                    console.log('GEMINI_DEBUG: main_after_popup ' + JSON.stringify(presence));
                }""",
                presence,
            )
        except Exception as e:
            logging.warning(f"No se pudo verificar presencia de archivos en la página principal: {e}")

        try:
            await page.screenshot(path="debug_after_upload.png")
            logging.info("Screenshot guardado: debug_after_upload.png")
        except Exception as e:
            logging.warning(f"No se pudo guardar screenshot: {e}")

        logging.info("Documentos subidos y procesados por la página principal")
    finally:
        keep = (os.getenv("XALOC_KEEP_UPLOAD_TRANSIT") or "0").strip().lower() in {"1", "true", "yes", "y", "on"}
        if keep:
            logging.info(f"[UPLOAD_TRANSIT] Conservando carpeta temporal: {transit_dir}")
        else:
            try:
                shutil.rmtree(transit_dir, ignore_errors=True)
                logging.info(f"[UPLOAD_TRANSIT] Limpiada carpeta temporal: {transit_dir}")
            except Exception as e:
                logging.warning(f"[UPLOAD_TRANSIT] No se pudo limpiar carpeta temporal {transit_dir}: {e}")


__all__ = ["subir_documento"]
