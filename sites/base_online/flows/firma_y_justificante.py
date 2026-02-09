from __future__ import annotations

import logging
import re
import shutil
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
    return f"JUSTIFICANTE - {clean_exp}.pdf"


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


async def _obtener_popup_si_existe(page: Page, trigger_locator) -> Page | None:
    try:
        async with page.expect_popup(timeout=10000) as p:
            await trigger_locator.click()
        popup = await p.value
        await popup.wait_for_load_state("domcontentloaded")
        return popup
    except TimeoutError:
        await trigger_locator.click()
        return None


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
    popup_task = asyncio.create_task(page.wait_for_event("popup", timeout=15000))
    download_task = asyncio.create_task(page.wait_for_event("download", timeout=15000))
    await link_locator.click()

    done, pending = await asyncio.wait({popup_task, download_task}, return_when=asyncio.FIRST_COMPLETED)
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
            download = result
        else:
            popup = result
    return download, popup


async def firmar_presentar_y_descargar_justificante(page: Page, *, payload: dict) -> Path:
    """
    BASE Online (P3): pulsa 'Signar i Presentar', firma en el popup, espera success y descarga justificante.
    Devuelve la ruta final del justificante guardado en la carpeta del cliente.
    """
    fase = payload.get("fase_procedimiento")
    id_recurso = payload.get("idRecurso") or "unknown"

    trigger = page.locator("input[type='button'][value='Signar i Presentar']").first
    await trigger.wait_for(state="visible", timeout=30000)

    logger.info("[BASE] Abriendo popup de firma...")
    popup = await _obtener_popup_si_existe(page, trigger)
    popup_page = popup or page

    logger.info("[BASE] Confirmando checkbox en popup...")
    checkbox = popup_page.locator("#confirmacio").first
    await checkbox.wait_for(state="visible", timeout=POPUP_TIMEOUT_MS)
    try:
        await checkbox.check()
    except Exception:
        await checkbox.click()

    logger.info("[BASE] Click en 'Signar' dentro del popup...")
    sig_button = popup_page.locator("#form_0\\:sig_button").first
    await sig_button.wait_for(state="visible", timeout=POPUP_TIMEOUT_MS)
    await sig_button.click()

    logger.info("[BASE] Cerrando popup (Continuar)...")
    close_button = popup_page.locator("#form_0\\:close_button").first
    await close_button.wait_for(state="visible", timeout=POPUP_TIMEOUT_MS)
    await close_button.click()

    if popup is not None:
        try:
            await popup.wait_for_event("close", timeout=20000)
        except TimeoutError:
            pass

    logger.info("[BASE] Esperando mensaje de éxito tras cerrar popup...")
    success = page.locator("div.success").first
    await success.wait_for(state="visible", timeout=SUCCESS_TIMEOUT_MS)
    success_text = (await success.inner_text()).strip()
    logger.info("[BASE] Success detectado: %s", " ".join(success_text.split())[:200])

    expediente = (
        _extraer_expediente_desde_success_text(success_text)
        or payload.get("expediente")
        or payload.get("expediente_num")
        or payload.get("expediente_raw")
        or "UNKNOWN"
    )

    link = page.locator("a.button.default", has_text=re.compile(r"Imprimir\\s+justificant", re.IGNORECASE)).first
    await link.wait_for(state="visible", timeout=30000)

    tmp_dir = Path("tmp") / "base_online" / "justificantes" / str(id_recurso)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / _justificante_filename(str(expediente))

    logger.info("[BASE] Descargando justificante...")
    download, popup_doc = await _click_y_capturar_descarga_o_popup(page, link)
    if download is not None:
        await download.save_as(tmp_path)
    else:
        if popup_doc is None:
            raise TimeoutError("No se detectó ni descarga ni popup del justificante.")
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

        url = popup_doc.url or ""
        if not url or url == "about:blank":
            raise RuntimeError("Popup del justificante sin URL válida (about:blank).")

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
    logger.info("[BASE] Justificante guardado en: %s", final_path)
    return final_path


__all__ = ["firmar_presentar_y_descargar_justificante"]
