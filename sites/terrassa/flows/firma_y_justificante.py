"""
Terrassa: firma del trámite, descarga del justificante y guardado en carpeta del cliente.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget

from core.client_paths import (
    ClientIdentity,
)
from core.justificantes_storage import (
    build_receipt_filename,
    resolve_receipt_dir_for_client,
    save_receipt_from_tmp,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Step 1 – Signing
# ---------------------------------------------------------------------------

async def _click_signar_tramit(page: "Page", config: "TerrassaConfig") -> None:
    """Click the 'Signar el tràmit' button on the review page (Pas 2)."""
    logger.info("Haciendo clic en 'Signar el tràmit'...")
    btn = page.locator(config.signar_selector).first
    await btn.wait_for(state="visible", timeout=config.timeouts.transicion)
    await btn.click()
    await page.wait_for_load_state("domcontentloaded")
    logger.info("OK Botón 'Signar el tràmit' pulsado")


async def _click_signar_ordinari(page: "Page", config: "TerrassaConfig") -> None:
    """Click the actual 'Signar' button that triggers the certificate signing."""
    logger.info("Esperando botón 'Signar' (ordinari)...")
    btn = page.locator(config.signar_ordinari_selector)
    wait_ms = int(config.firma_timeout_ms)
    await btn.wait_for(state="visible", timeout=wait_ms)
    try:
        await btn.click(timeout=wait_ms)
    except PlaywrightTimeoutError:
        # Fallback: en Terrassa a veces el enlace está visible pero Playwright
        # no lo considera accionable por overlays/transiciones.
        logger.warning("Click normal en 'Signar' agotado; aplicando fallback JS click.")
        await btn.evaluate("(el) => el.click()")
    logger.info("OK Botón 'Signar' pulsado — procesando firma...")


async def _wait_for_success(page: "Page", config: "TerrassaConfig") -> None:
    """Wait for the green success message after signing (up to firma_timeout_ms)."""
    logger.info("Esperando confirmación de firma (hasta %d s)...", config.firma_timeout_ms // 1000)
    success = page.locator(config.success_selector)
    await success.wait_for(state="visible", timeout=config.firma_timeout_ms)

    # Double-check the text content
    text = (await success.text_content() or "").strip()
    if "correctament" not in text.lower():
        logger.warning("Mensaje de éxito detectado pero texto inesperado: %s", text[:200])
    else:
        logger.info("OK Firma completada: %s", text[:120])


# ---------------------------------------------------------------------------
#  Step 2 – Receipt download
# ---------------------------------------------------------------------------

async def _download_receipt_pdf(page: "Page", config: "TerrassaConfig") -> Path:
    """Extract the receipt URL and download via fetch (keeps session cookies)."""
    logger.info("Descargando justificante (comprovant)...")

    link = page.locator(config.receipt_link_selector).first
    await link.wait_for(state="visible", timeout=30_000)

    # Extract the href directly — the link has target="_blank" so clicking it
    # would open a PDF viewer in a new tab, which is unnecessary.
    href = await link.get_attribute("href")
    if not href:
        raise RuntimeError("No se pudo obtener la URL del justificante")
    if href.startswith("/"):
        href = f"{config.url_base}{href}"

    logger.info("URL del justificante: %s", href)
    return await _fetch_pdf_from_url(page, href)


async def _fetch_pdf_from_url(page: "Page", url: str) -> Path:
    """Download a PDF using an in-page fetch (keeps cookies/session)."""
    logger.info("Realizando fetch interno desde: %s", url)
    js = """
    async (url) => {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const blob = await resp.blob();
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result.split(',')[1]);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    }
    """
    b64 = await page.evaluate(js, url)
    pdf_bytes = base64.b64decode(b64)
    tmp_path = Path("tmp") / f"terrassa_receipt_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(pdf_bytes)
    logger.info("OK Justificante descargado via fetch (%d bytes)", len(pdf_bytes))
    return tmp_path


# ---------------------------------------------------------------------------
#  Step 3 – Save to client folder
# ---------------------------------------------------------------------------

def _save_receipt_to_client_folder(
    tmp_path: Path,
    datos: "TerrassaTarget",
) -> Path:
    """Move the receipt PDF to the client's RECURSOS TELEMATICOS folder."""
    logger.info("Guardando justificante en carpeta del cliente...")

    # Build client identity
    if datos.is_company:
        client = ClientIdentity(
            is_company=True,
            sujeto_recurso=datos.sujeto_recurso or None,
            empresa=datos.nombre,
        )
    else:
        client = ClientIdentity(
            is_company=False,
            sujeto_recurso=datos.sujeto_recurso or None,
            nombre=datos.nombre,
            apellido1=datos.apellido1,
            apellido2=datos.apellido2,
        )

    dest_dir = resolve_receipt_dir_for_client(
        client=client,
        fase_procedimiento=datos.fase_procedimiento or None,
    )
    logger.info("Carpeta destino: %s", dest_dir)

    # Build filename: JUSTIFICANTE <expediente>.pdf (no overwrite)
    filename = build_receipt_filename(
        expediente=datos.expediente,
        template="JUSTIFICANTE {expediente}.pdf",
    )

    try:
        ruta_final = save_receipt_from_tmp(
            tmp_path=tmp_path,
            destino_dir=dest_dir,
            filename=filename,
        )
    except Exception as e:
        logger.error("Error al copiar justificante: %s", e)
        raise RuntimeError(f"No se pudo copiar el justificante al cliente: {e}") from e

    return ruta_final


# ---------------------------------------------------------------------------
#  Public entry point
# ---------------------------------------------------------------------------

async def run_firma_y_justificante(
    page: "Page",
    config: "TerrassaConfig",
    datos: "TerrassaTarget",
) -> tuple["Page", str | None]:
    """
    Complete the signing flow and download/save the receipt.

    Returns:
        (page, justificante_path) — justificante_path is the absolute path
        to the saved receipt, or None if saving failed non-fatally.
    """
    # 1. Click "Signar el tràmit"
    await _click_signar_tramit(page, config)

    # 2. Click "Signar" (ordinari)
    await _click_signar_ordinari(page, config)

    # 3. Wait for green success message
    await _wait_for_success(page, config)

    # 4. Download receipt PDF
    tmp_pdf = await _download_receipt_pdf(page, config)

    # 5. Save to client folder
    try:
        ruta_final = _save_receipt_to_client_folder(tmp_pdf, datos)
        return page, str(ruta_final)
    except Exception as e:
        logger.error("No se pudo guardar justificante en carpeta cliente: %s", e)
        # Non-fatal: the signing itself succeeded
        return page, str(tmp_pdf)
