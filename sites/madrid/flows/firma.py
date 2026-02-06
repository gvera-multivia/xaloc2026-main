from __future__ import annotations

import logging
import base64
import shutil
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from playwright.async_api import Page, TimeoutError

if TYPE_CHECKING:
    from sites.madrid.config import MadridConfig

from core.client_documentation import (
    client_identity_from_payload,
    get_ruta_cliente_documentacion,
)

logger = logging.getLogger(__name__)

class MadridFirmaNonFatalError(RuntimeError):
    """
    Error no fatal: el trámite pudo haberse enviado, pero falló un paso post-envío
    (p.ej. mover el justificante a la carpeta final).
    """

# --- Helper Functions (Copied from xaloc_girona/flows/descarga_justificante.py) ---
# Copied to implement path logic specifically, NOT download logic

def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).strip().lower()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text) 
        if unicodedata.category(c) != "Mn"
    )
    return text

def _get_folder_name_from_fase(fase_raw: Any) -> str:
    MOTIVO_TO_FOLDER = {
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
    for motivo_key, folder_name in MOTIVO_TO_FOLDER.items():
        if motivo_key in fase_norm:
            return folder_name
    
    logger.warning(f"No match for phase '{fase_raw}', defaulting to base folder.")
    return "" 

def _folder_matches(folder_name: str, target_name: str) -> bool:
    folder_norm = _normalize_text(folder_name)
    target_norm = _normalize_text(target_name)
    if folder_norm == target_norm: return True
    
    target_words = set(target_norm.split())
    folder_words = set(folder_norm.split())
    if target_words.issubset(folder_words): return True
    
    target_singular = {w.rstrip('s') for w in target_words}
    folder_singular = {w.rstrip('s') for w in folder_words}
    if target_singular == folder_singular: return True
    
    return False

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

def _construir_ruta_recursos_telematicos(payload: dict, fase_procedimiento: Any = None) -> Path:
    client = client_identity_from_payload(payload)
    base_path = r"\\SERVER-DOC\clientes"
    ruta_cliente_base = get_ruta_cliente_documentacion(client, base_path=base_path)
    
    # Usar búsqueda flexible para evitar duplicados "TELEMÁTICOS" vs "TELEMATICOS"
    ruta_recursos = _find_or_create_subfolder(ruta_cliente_base, "RECURSOS TELEMATICOS")
    
    if fase_procedimiento:
        folder_name = _get_folder_name_from_fase(fase_procedimiento)
        if folder_name:
            return _find_or_create_subfolder(ruta_recursos, folder_name)
            
    return ruta_recursos

def _justificante_filename(num_expediente: str) -> str:
    clean_exp = str(num_expediente).replace("/", "-").replace(".", "_")
    return f"JUSTIFICANTE - {clean_exp}.pdf"


def _guardar_justificante_temporal(pdf_bytes: bytes, *, num_expediente: str, tmp_dir: Path) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / _justificante_filename(num_expediente)
    tmp_path.write_bytes(pdf_bytes)
    logger.info("Justificante guardado temporalmente en: %s", tmp_path)
    return tmp_path


def _mover_justificante_a_destino(tmp_path: Path, *, destino_dir: Path) -> Path:
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino_path = destino_dir / tmp_path.name
    if destino_path.exists():
        destino_path.unlink()
    shutil.move(str(tmp_path), str(destino_path))
    logger.info("Justificante movido a: %s", destino_path)
    return destino_path

# --- Main Flow ---

async def ejecutar_firma_madrid(
    page: Page, 
    config: "MadridConfig", 
    destino_descarga: Path, 
    payload: dict
) -> Page:
    """
    Descarga el PDF (verificar) en carpeta temporal y solo si está OK
    confirma el envío (checkbox + botón). Si el envío se confirma, mueve el PDF
    a la carpeta "RECURSOS TELEMATICOS" correspondiente del cliente.
    """
    logger.info("=" * 80)
    logger.info("FIRMA MADRID - EXPEDIENTE: %s", destino_descarga.stem)
    logger.info("=" * 80)

    raw_exp = payload.get("expediente") or payload.get("expediente_num") or "UNKNOWN"
    fase = payload.get("fase_procedimiento")
    id_recurso = payload.get("idRecurso") or destino_descarga.stem
    tmp_dir = Path("tmp") / "madrid" / "justificantes" / str(id_recurso)

    # ====================================================================
    # 1. Ir a pantalla de firma (SIGNA) si no lo estamos ya
    # ====================================================================
    if config.url_signa_firma_contains.lower() not in (page.url or "").lower():
        await page.wait_for_selector(
            config.firma_registrar_selector, state="visible", timeout=config.default_timeout
        )
        logger.info("Pantalla pre-firma detectada. Entrando en SIGNA (Firma y registrar)...")
        try:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
                await page.click(config.firma_registrar_selector)
        except TimeoutError:
            logger.warning("No se detectó navegación tras 'Firma y registrar'; continuando igualmente.")

    # ====================================================================
    # 2. Descargar justificante (verificar) a carpeta temporal
    # ====================================================================
    await page.wait_for_selector(
        config.verificar_documento_selector, state="attached", timeout=config.firma_navigation_timeout
    )
    logger.info("Pantalla SIGNA detectada (verificar disponible).")

    logger.info("Descargando justificante vía fetch (verificar)...")
    
    script_extraccion = """
    async () => {
        const btn = document.querySelector('button[name="verificar"]');
        if (!btn) throw new Error("Botón 'verificar' no encontrado en pantalla de firma.");
        const formData = new FormData(btn.form);
        formData.append('verificar', '1');

        const response = await fetch(btn.form.action, {
            method: 'POST',
            body: new URLSearchParams(formData)
        });

        if (!response.ok) throw new Error("Servidor Madrid falló: " + response.status);

        const buffer = await response.arrayBuffer();
        // Convertimos el buffer a Base64 para pasarlo de JS a Python sin pérdidas
        return btoa(String.fromCharCode(...new Uint8Array(buffer)));
    }
    """

    base64_pdf = await page.evaluate(script_extraccion)
    pdf_bytes = base64.b64decode(base64_pdf)

    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError("Los datos recibidos no tienen formato PDF.")
    if len(pdf_bytes) < 10_000:
        raise RuntimeError(f"PDF sospechosamente pequeño: {len(pdf_bytes)} bytes")

    tmp_pdf_path = _guardar_justificante_temporal(
        pdf_bytes, num_expediente=str(raw_exp), tmp_dir=tmp_dir
    )

    # ====================================================================
    # 3. Confirmar envío (checkbox + botón final)
    # ====================================================================
    logger.info("Confirmando envío del trámite (checkbox + botón)...")
    checkbox = page.locator("#consentimiento")
    if await checkbox.count() > 0:
        await checkbox.check()

    firmar_btn = page.locator('input.button.button4[name="btnFirmar"]')
    if await firmar_btn.count() == 0:
        raise RuntimeError("Botón final de firma/envío no encontrado (btnFirmar).")

    prev_url = page.url or ""
    try:
        # Madrid va lenta: esperar un poco antes de enviar el formulario
        await page.wait_for_timeout(2000)
        async with page.expect_navigation(
            wait_until="domcontentloaded", timeout=config.firma_navigation_timeout
        ):
            await firmar_btn.click()
    except TimeoutError:
        # A veces no hay navegación clásica (refresh parcial). El click ya se ejecutó.
        logger.warning("No se detectó navegación tras el envío; continuando con espera blanda.")

    try:
        await page.wait_for_function(
            "prev => window.location.href !== prev", arg=prev_url, timeout=15000
        )
    except Exception:
        pass
    await page.wait_for_timeout(1200)

    # ====================================================================
    # 4. Mover justificante a carpeta final (solo tras confirmar envío)
    # ====================================================================
    ruta_recursos = _construir_ruta_recursos_telematicos(payload, fase)
    try:
        _mover_justificante_a_destino(tmp_pdf_path, destino_dir=ruta_recursos)
    except Exception as e:
        raise MadridFirmaNonFatalError(
            f"Trámite enviado, pero no se pudo mover el justificante a la carpeta final: {e}"
        ) from e

    # 5. FINALIZACIÓN
    logger.info("=" * 80)
    logger.info("PROCESO DE FIRMA Y ENVÍO COMPLETADO CON ÉXITO")
    logger.info("=" * 80)
    
    return page
