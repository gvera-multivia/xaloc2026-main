from __future__ import annotations

import logging
import re
import shutil
import time
import unicodedata
from pathlib import Path
from typing import Any

import asyncio
import base64
from playwright.async_api import Page, TimeoutError

from core.client_documentation import client_identity_from_payload, get_ruta_cliente_documentacion

logger = logging.getLogger(__name__)

SUCCESS_TIMEOUT_MS = 180000
POPUP_TIMEOUT_MS = 30000
DOWNLOAD_TIMEOUT_MS = 90000


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).strip().lower()
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return text


def _folder_matches(folder_name: str, target_name: str) -> bool:
    folder_norm = _normalize_text(folder_name)
    target_norm = _normalize_text(target_name)
    if folder_norm == target_norm:
        return True
    target_words = set(target_norm.split())
    folder_words = set(folder_norm.split())
    if target_words.issubset(folder_words):
        return True
    target_singular = {w.rstrip("s") for w in target_words}
    folder_singular = {w.rstrip("s") for w in folder_words}
    return target_singular == folder_singular


def _find_or_create_subfolder(base_path: Path, folder_name: str) -> Path:
    if not folder_name:
        return base_path
    if base_path.exists():
        for item in base_path.iterdir():
            if item.is_dir() and _folder_matches(item.name, folder_name):
                return item
    new_folder = base_path / folder_name
    new_folder.mkdir(parents=True, exist_ok=True)
    return new_folder


def _get_folder_name_from_fase(fase_raw: Any) -> str:
    motivo_to_folder = {
        "identificacion": "IDENTIFICACIONES",
        "denuncia": "ALEGACIONES",
        "propuesta de resolucion": "ALEGACIONES",
        "extraordinario de revision": "EXTRAORDINARIOS DE REVISIÓN",
        "subsanacion": "SUBSANACIONES",
        "reclamaciones": "RECLAMACIONES",
        "requerimiento embargo": "EMBARGOS",
        "sancion": "SANCIONES",
        "apremio": "APREMIOS",
        "embargo": "EMBARGOS",
    }
    fase_norm = _normalize_text(fase_raw)
    for key, folder in motivo_to_folder.items():
        if key in fase_norm:
            return folder
    return ""


def _construir_ruta_recursos_telematicos(payload: dict, fase_procedimiento: Any = None) -> Path:
    client = client_identity_from_payload(payload)
    base_path = r"\\SERVER-DOC\clientes"
    ruta_cliente_base = get_ruta_cliente_documentacion(client, base_path=base_path)

    ruta_recursos = _find_or_create_subfolder(ruta_cliente_base, "RECURSOS TELEMATICOS")
    if fase_procedimiento:
        folder = _get_folder_name_from_fase(fase_procedimiento)
        if folder:
            return _find_or_create_subfolder(ruta_recursos, folder)
    return ruta_recursos


def _sanitize_filename_component(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("/", "-").replace("\\", "-")
    value = re.sub(r'[<>:"|?*\x00-\x1F]', "_", value)
    value = value.rstrip(". ")
    return value or "UNKNOWN"


def _justificante_filename(num_expediente: str) -> str:
    clean_exp = _sanitize_filename_component(num_expediente)
    return f"JUSTIFICANTE- {clean_exp}.pdf"


def _extraer_expediente_desde_success_text(texto: str) -> str | None:
    if not texto:
        return None
    # Ej: "El número d'expedient és: 1-2026/898-GIR."
    m = re.search(r"n[uú]mero\s+d[' ]expedient\s+e[sí]:\s*([^\s.]+)", texto, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"(\d-\d{4}/\d{1,10}-[A-Z]{2,5})", texto)
    if m:
        return m.group(1).strip()
    return None


def _extraer_expediente_desde_payload(payload: dict) -> str | None:
    """
    Preferir SIEMPRE el expediente que viene de base de datos (payload), no el que devuelve la web.
    """
    for key in ("expediente", "Expedient", "expediente_num", "expediente_raw", "expediente_base"):
        val = payload.get(key)
        if val:
            return str(val).strip()
    return None


def _normalizar_expediente_para_nombre(expediente_raw: str) -> str:
    """
    Extrae/normaliza el expediente para usarlo en nombre de archivo.
    - Quita puntos finales y espacios
    - Si viene con texto alrededor, intenta extraer el token de expediente
    """
    exp = (expediente_raw or "").strip()
    exp = exp.rstrip(".").strip()
    if not exp:
        return "UNKNOWN"

    # Patrones comunes BASE: 43150-2026/3320-GIM, 1-2026/899-GIR, 1-2025/27474-EXE, etc.
    patterns = [
        r"\b\d{5}-\d{4}/\d{1,10}-[A-Z]{2,5}\b",
        r"\b\d-\d{4}[/\-]\d{1,10}-[A-Z]{2,5}\b",
    ]
    for pat in patterns:
        m = re.search(pat, exp)
        if m:
            return m.group(0)

    return exp


async def _abrir_modal_firma(page: Page, trigger_locator) -> None:
    """
    En BASE no se abre un popup de ventana: se abre un modal Bootstrap (#signatura)
    con un iframe #contingut_signatura. Abrimos el modal evitando bloqueos del backdrop.
    """
    modal = page.locator("#signatura").first

    # Si ya está abierto, no hacer nada.
    try:
        if await modal.is_visible():
            return
    except Exception:
        pass

    # Preferir la función JS (evita "backdrop intercepts pointer events").
    try:
        await page.evaluate(
            """() => {
              if (typeof peticioDeSignatura === 'function') return peticioDeSignatura();
              if (typeof signarEnvelopedModal === 'function') return signarEnvelopedModal();
              return null;
            }"""
        )
    except Exception:
        pass

    # Fallback: click forzado sobre el botón visible (puede estar parcialmente tapado por el modal).
    try:
        await trigger_locator.click(force=True, timeout=5000)
    except Exception:
        pass

    await modal.wait_for(state="visible", timeout=POPUP_TIMEOUT_MS)
    iframe = page.locator("iframe#contingut_signatura").first
    await iframe.wait_for(state="attached", timeout=POPUP_TIMEOUT_MS)


async def _mover_a_destino(tmp_path: Path, *, destino_dir: Path) -> Path:
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino_path = destino_dir / tmp_path.name
    if destino_path.exists():
        destino_path.unlink()

    # copy2 para permitir mover entre unidades/UNC sin WinError 17.
    shutil.copy2(tmp_path, destino_path)
    tmp_path.unlink(missing_ok=True)
    return destino_path


async def _descargar_pdf_via_fetch(page: Page, url: str) -> bytes:
    js = """
    async (url) => {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const buf = await resp.arrayBuffer();
      return btoa(String.fromCharCode(...new Uint8Array(buf)));
    }
    """
    base64_data = await page.evaluate(js, url)
    return base64.b64decode(base64_data)


async def _click_y_capturar_descarga_o_popup(page: Page, link_locator) -> tuple[Any | None, Page | None]:
    # Aumentamos el timeout a 45s porque BASE puede tardar tras la firma.
    event_timeout = 45000
    popup_task = asyncio.create_task(page.wait_for_event("popup", timeout=event_timeout))
    download_task = asyncio.create_task(page.wait_for_event("download", timeout=event_timeout))
    
    try:
        try:
            await link_locator.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass

        # Pequeña pausa para asegurar estabilidad antes del click
        await page.wait_for_timeout(2000)

        # Intentar obtener info del elemento para logs
        try:
            tag = await link_locator.evaluate("el => el.tagName")
            text = await link_locator.inner_text()
            logger.info(f"[BASE] Haciendo click en justificante ({tag}: '{text.strip()}')")
        except Exception:
            logger.info("[BASE] Haciendo click en justificante (tag/texto no disponible)")

        try:
            await link_locator.click(timeout=10000)
        except Exception:
            # Fallback: dispara el click desde el DOM
            await link_locator.evaluate("(el) => el.click()")
    except Exception:
        popup_task.cancel()
        download_task.cancel()
        raise

    done, pending = await asyncio.wait(
        {popup_task, download_task}, 
        return_when=asyncio.FIRST_COMPLETED,
        timeout=event_timeout / 1000 + 5
    )
    
    for task in pending:
        task.cancel()

    popup = None
    download = None
    for task in done:
        try:
            result = task.result()
        except Exception:
            result = None
        if result is None:
            continue
        if hasattr(result, "save_as"):
            logger.info("[BASE] Evento DETECTADO: download")
            download = result
        else:
            logger.info("[BASE] Evento DETECTADO: popup (nueva pestaña)")
            popup = result

    return download, popup


def _iter_page_frames(page: Page):
    try:
        frames = list(page.frames)
    except Exception:
        frames = []
    if page.main_frame not in frames:
        frames.insert(0, page.main_frame)
    else:
        frames.sort(key=lambda f: 0 if f == page.main_frame else 1)
    return frames


async def _find_justificante_action_locator(page: Page, *, timeout_ms: int = 60000):
    justificante_re = re.compile(r"Imprimir\s+justific(?:ant|ante)", re.IGNORECASE)
    imprimir_re = re.compile(r"Imprimir", re.IGNORECASE)
    justificant_registre_re = re.compile(r"Justificant\s+de\s+registre", re.IGNORECASE)

    deadline = time.monotonic() + (timeout_ms / 1000)
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        for frame in _iter_page_frames(page):
            try:
                candidates = [
                    frame.locator("a.button.default").filter(has_text=justificante_re),
                    frame.locator("a").filter(has_text=justificante_re),
                    frame.locator("a[onclick*='jsfcljs']").filter(has_text=imprimir_re),
                    frame.locator("a.button.default").filter(has_text=imprimir_re),
                    frame.locator("input[type='submit'][value*='Imprimir'], input[type='button'][value*='Imprimir']"),
                    frame.locator("button").filter(has_text=imprimir_re),
                    frame.locator("button").filter(has_text=justificant_registre_re),
                    frame.locator("button[onclick*='justificant']"),
                ]
                for i, locator in enumerate(candidates):
                    if await locator.count() > 0:
                        first = locator.first
                        try:
                            # Loguear qué candidato ha funcionado para referencia futura
                            text = await first.inner_text()
                            logger.info(f"[BASE] Candidato justificante #{i+1} encontrado: '{text.strip()}'")
                            await first.wait_for(state="attached", timeout=2000)
                        except Exception:
                            pass
                        return first
            except Exception as e:
                last_error = e
                continue

        await page.wait_for_timeout(1000)

    if last_error is not None:
        raise TimeoutError(
            "No se encontró el botón/enlace de justificante dentro del timeout."
        ) from last_error
    raise TimeoutError("No se encontró el botón/enlace de justificante dentro del timeout.")


async def _descargar_desde_popup_visor(popup_doc: Page, tmp_path: Path) -> bool:
    try:
        await popup_doc.wait_for_load_state("domcontentloaded")
    except Exception:
        pass

    # Preferimos CSV estampado: a onclick="descarrega(true)"
    try:
        csv_link = popup_doc.locator("a[onclick*='descarrega(true)']").first
        if await csv_link.count() > 0:
            download_task = asyncio.create_task(popup_doc.wait_for_event("download", timeout=15000))
            await csv_link.click()
            download = await download_task
            await download.save_as(tmp_path)
            return True
    except Exception:
        pass

    # Fallback robusto: construir URL de descarga desde JS y bajar por fetch en el contexto autenticado del popup.
    try:
        csv_url = await popup_doc.evaluate(
            "() => (typeof generarUrlDescarrega === 'function' ? generarUrlDescarrega(true) : '')"
        )
        csv_url = (csv_url or "").strip()
        if csv_url:
            pdf_bytes = await _descargar_pdf_via_fetch(popup_doc, csv_url)
            tmp_path.write_bytes(pdf_bytes)
            return True
    except Exception:
        pass

    return False


async def _descargar_desde_modal_visor_embebido(page: Page, tmp_path: Path) -> bool:
    """
    BASE puede abrir el visor en modal embebido (#visorGEA) con iframe
    #contingut_modal_visorGEA, sin popup de ventana.
    """
    modal = page.locator("#visorGEA").first
    iframe_node = page.locator("#contingut_modal_visorGEA").first

    try:
        await modal.wait_for(state="visible", timeout=15000)
        await iframe_node.wait_for(state="attached", timeout=15000)
        await page.wait_for_function(
            """() => {
              const f = document.getElementById('contingut_modal_visorGEA');
              return !!f && !!f.getAttribute('src') && f.getAttribute('src') !== 'about:blank';
            }""",
            timeout=15000,
        )
    except Exception:
        return False

    frame = page.frame_locator("#contingut_modal_visorGEA").first

    # Opcion 1: click directo en enlace CSV.
    try:
        csv_link = frame.locator("a[onclick*='descarrega(true)']").first
        if await csv_link.count() > 0:
            async with page.expect_download(timeout=20000) as dl_info:
                await csv_link.click()
            download = await dl_info.value
            await download.save_as(tmp_path)
            return True
    except Exception:
        pass

    # Opcion 2: fallback JS dentro del iframe.
    try:
        async with page.expect_download(timeout=20000) as dl_info:
            await frame.evaluate(
                """() => {
                  if (typeof descarrega === 'function') {
                    descarrega(true);
                    return true;
                  }
                  return false;
                }"""
            )
        download = await dl_info.value
        await download.save_as(tmp_path)
        return True
    except Exception:
        pass

    return False


async def _find_signar_presentar_trigger(page: Page, *, timeout_ms: int = 30000):
    candidates = [
        page.locator("input[type='button'][value='Signar i Presentar']"),
        page.locator("input[type='button'][value='Signar i presentar']"),
        page.locator("input[type='submit'][value='Signar i Presentar']"),
        page.locator("input[type='submit'][value='Signar i presentar']"),
        page.locator("input[type='button'][onclick*='mostrarProcessant']"),
        page.locator("input[type='submit'][onclick*='mostrarProcessant']"),
    ]
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        for locator in candidates:
            try:
                if await locator.count() > 0:
                    first = locator.first
                    try:
                        await first.wait_for(state="visible", timeout=1500)
                        return first
                    except Exception:
                        continue
            except Exception:
                continue
        await page.wait_for_timeout(1000)
    raise TimeoutError("No se encontro el boton de firma 'Signar i Presentar/presentar' dentro del timeout.")


async def firmar_presentar_y_descargar_justificante(page: Page, *, payload: dict) -> Path:
    """
    BASE Online (P3): pulsa 'Signar i Presentar', firma en el popup, espera success y descarga justificante.
    Devuelve la ruta final del justificante guardado en la carpeta del cliente.
    """
    fase = payload.get("fase_procedimiento")
    id_recurso = payload.get("idRecurso") or "unknown"

    trigger = await _find_signar_presentar_trigger(page, timeout_ms=30000)

    logger.info("[BASE] Abriendo popup de firma...")
    await _abrir_modal_firma(page, trigger)
    await page.wait_for_timeout(3000)
    popup_frame = page.frame_locator("#contingut_signatura").first

    logger.info("[BASE] Confirmando checkbox en popup...")
    checkbox = popup_frame.locator("#confirmacio").first
    await checkbox.wait_for(state="visible", timeout=POPUP_TIMEOUT_MS)
    try:
        await checkbox.check()
    except Exception:
        await checkbox.click()
    await page.wait_for_timeout(3000)

    logger.info("[BASE] Click en 'Signar' dentro del popup...")
    sig_button = popup_frame.locator("#form_0\\:sig_button").first
    await sig_button.wait_for(state="visible", timeout=POPUP_TIMEOUT_MS)
    await sig_button.click()
    await page.wait_for_timeout(3000)

    logger.info("[BASE] Cerrando popup (Continuar)...")
    close_button = popup_frame.locator("#form_0\\:close_button").first
    await close_button.wait_for(state="visible", timeout=POPUP_TIMEOUT_MS)
    await close_button.click()
    await page.wait_for_timeout(3000)

    # Esperar a que el modal se cierre en la página principal.
    try:
        await page.wait_for_function(
            """() => {
              const el = document.getElementById('signatura');
              if (!el) return true;
              const style = window.getComputedStyle(el);
              const hidden = el.getAttribute('aria-hidden') === 'true';
              const displayNone = style && style.display === 'none';
              return hidden || displayNone || !el.classList.contains('in');
            }""",
            timeout=30000,
        )
    except Exception:
        pass

    logger.info("[BASE] Esperando mensaje de exito tras cerrar popup...")
    success = page.locator("div.success").first
    await success.wait_for(state="visible", timeout=SUCCESS_TIMEOUT_MS)
    success_text = (await success.inner_text()).strip()
    logger.info("[BASE] Success detectado: %s", " ".join(success_text.split())[:200])

    expediente_db = _extraer_expediente_desde_payload(payload)
    expediente_web = _extraer_expediente_desde_success_text(success_text)
    expediente = _normalizar_expediente_para_nombre(expediente_db or expediente_web or "UNKNOWN")

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass

    link = await _find_justificante_action_locator(page, timeout_ms=60000)

    tmp_dir = Path("tmp") / "base_online" / "justificantes" / str(id_recurso)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / _justificante_filename(str(expediente))

    logger.info("[BASE] Descargando justificante...")
    download, popup_doc = await _click_y_capturar_descarga_o_popup(page, link)
    if download is not None:
        await download.save_as(tmp_path)
    else:
        if popup_doc is None:
            ok_modal_download = await _descargar_desde_modal_visor_embebido(page, tmp_path)
            if not ok_modal_download:
                raise TimeoutError("No se detecto descarga, popup ni modal visor del justificante.")
        else:
            try:
                await popup_doc.wait_for_load_state("domcontentloaded")
            except Exception:
                pass

            try:
                await popup_doc.wait_for_function(
                    "() => location.href && location.href !== 'about:blank'",
                    timeout=30000,
                )
            except Exception:
                pass

            ok_popup_download = await _descargar_desde_popup_visor(popup_doc, tmp_path)
            if not ok_popup_download:
                url = popup_doc.url or ""
                if not url or url == "about:blank":
                    raise RuntimeError("Popup del justificante sin URL valida (about:blank).")
                pdf_bytes = await _descargar_pdf_via_fetch(popup_doc, url)
                tmp_path.write_bytes(pdf_bytes)
            try:
                await popup_doc.close()
            except Exception:
                pass

    pdf_bytes = tmp_path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError("Justificante descargado no parece PDF (no empieza por %PDF).")
    if len(pdf_bytes) < 2000:
        raise RuntimeError(f"Justificante PDF sospechosamente pequeño: {len(pdf_bytes)} bytes")

    destino_dir = _construir_ruta_recursos_telematicos(payload, fase)
    final_path = await _mover_a_destino(tmp_path, destino_dir=destino_dir)
    payload["base_justificante_descargado"] = True
    payload["base_justificante_path"] = str(final_path)
    logger.info("[BASE] Justificante guardado en: %s", final_path)
    return final_path


__all__ = ["firmar_presentar_y_descargar_justificante"]
