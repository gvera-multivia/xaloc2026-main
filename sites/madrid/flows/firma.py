from __future__ import annotations

import logging
import base64
import os
import shutil
import unicodedata
import re
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
    base_path = os.getenv("CLIENT_DOCS_BASE_PATH") or r"\\SERVER-DOC\clientes"
    ruta_cliente_base = get_ruta_cliente_documentacion(client, base_path=base_path)
    
    ruta_recursos = ruta_cliente_base / "RECURSOS TELEMATICOS"
    ruta_recursos.mkdir(parents=True, exist_ok=True)
    
    if fase_procedimiento:
        folder_name = _get_folder_name_from_fase(fase_procedimiento)
        if folder_name:
            return _find_or_create_subfolder(ruta_recursos, folder_name)
            
    return ruta_recursos

def _renombrar_y_mover_justificante_bytes(
    pdf_bytes: bytes, num_expediente: str, destino_dir: Path
) -> Path:
    """
    Guarda los bytes directamente en la ruta de destino.
    """
    # JUSTIFICANTE - (numero de expediente) (replace . with _ and / with -)
    clean_exp = num_expediente.replace("/", "-").replace(".", "_")
    nombre_final = f"JUSTIFICANTE - {clean_exp}.pdf"
    ruta_final = destino_dir / nombre_final
    
    # Ensure destination directory exists
    destino_dir.mkdir(parents=True, exist_ok=True)
    
    # Write bytes
    try:
        ruta_final.write_bytes(pdf_bytes)
        logger.info(f"✓ Justificante guardado en: {ruta_final}")
    except Exception as e:
        raise RuntimeError(f"Failed to save justificante to {ruta_final}: {e}") from e
    
    return ruta_final

# --- Main Flow ---

async def ejecutar_firma_madrid(
    page: Page, 
    config: "MadridConfig", 
    destino_descarga: Path, 
    payload: dict
) -> Page:
    """
    Extrae el documento original inyectando la lógica de fetch validada en consola.
    Garantiza el binario de 67KB y evita el visor de la extensión.
    """
    logger.info("=" * 80)
    logger.info(f"EXTRACCIÓN BINARIA DIRECTA - EXPEDIENTE: {destino_descarga.stem}")
    logger.info("=" * 80)

    # 1. Definir ruta en la raíz del proyecto (LEGACY/BACKUP PATH)
    nombre_final = f"{destino_descarga.stem}.pdf"
    ruta_raiz = Path(".") / nombre_final

    # 2. Navegar a la pantalla de firma (MODIFIED UI INTERACTION)
    await page.wait_for_selector(config.firma_registrar_selector, state="visible")
    
    # checkbox interaction
    logger.info("Marcando checkbox consentimiento...")
    if await page.locator("#consentimiento").count() > 0:
        await page.locator("#consentimiento").check()
    
    # button interaction (Using user specified selector)
    logger.info("Clicando Firmar y registrar...")
    firmar_btn = page.locator('input.button.button4[value="Firmar y registrar"]')
    
    if await firmar_btn.count() > 0:
         async with page.expect_navigation(wait_until="domcontentloaded"):
            await firmar_btn.click()
    else:
        logger.warning("Botón específico no encontrado, usando selector config...")
        async with page.expect_navigation(wait_until="domcontentloaded"):
            await page.click(config.firma_registrar_selector)
    
    await page.wait_for_load_state("networkidle")

    # 3. EJECUCIÓN DEL "HACK" DE CONSOLA (PRESERVED EXACTLY AS REQUESTED)
    # Le pedimos al navegador que haga el fetch y nos devuelva el PDF en Base64
    logger.info("Ejecutando fetch interceptor para el vehículo 5748LFZ...")
    
    script_extraccion = """
    async () => {
        const btn = document.querySelector('button[name="verificar"]');
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

    try:
        # Ejecutamos la lógica que funcionó en tu consola
        base64_pdf = await page.evaluate(script_extraccion)
        
        # 4. DECODIFICACIÓN Y GUARDADO FÍSICO
        pdf_bytes = base64.b64decode(base64_pdf)
        
        if pdf_bytes.startswith(b"%PDF"):
            # Save to root (Legacy/Backup behavior from original script)
            ruta_raiz.write_bytes(pdf_bytes)
            logger.info(f"✓ DOCUMENTO ORIGINAL GUARDADO (ROOT) ({len(pdf_bytes)} bytes)")
            
            # Save to Protocol Path (NEW REQUIREMENT)
            raw_exp = payload.get("expediente") or payload.get("expediente_num") or "UNKNOWN"
            fase = payload.get("fase_procedimiento")
            
            ruta_recursos = _construir_ruta_recursos_telematicos(payload, fase)
            ruta_final = _renombrar_y_mover_justificante_bytes(pdf_bytes, str(raw_exp), ruta_recursos)
            
            logger.info(f"✓ JUSTIFICANTE GUARDADO SEGÚN PROTOCOLO: {ruta_final}")
            
        else:
            raise RuntimeError("Los datos recibidos no tienen formato PDF.")

    except Exception as e:
        logger.error(f"Fallo en la extracción por inyección: {e}")
        raise

    # 5. FINALIZACIÓN
    # Ya no hay popups que cerrar porque nunca dejamos que se abrieran
    logger.info("=" * 80)
    logger.info("PROCESO DE FIRMA Y EXTRACCIÓN COMPLETADO CON ÉXITO")
    logger.info("=" * 80)
    
    return page