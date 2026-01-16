"""
Flujo para el formulario de Recurso de Reposición (P3) - paso 1/3.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re

from playwright.async_api import Page

from sites.base_online.config import BaseOnlineConfig
from sites.base_online.data_models import BaseOnlineReposicionData


def _normalizar_tipus_objecte(raw: str) -> str:
    valor = (raw or "").strip().upper()
    if valor in {"IBI"}:
        return "IBI"
    if valor in {"IVTM"}:
        return "IVTM"
    if valor in {"EXPEDIENTE EJECUTIVO", "EXPEDIENTE_EJECUTIVO", "EXPEDIENT EXECUTIU", "EXPEDIENT_EXECUTIU"}:
        return "EXPEDIENTE EJECUTIVO"
    if valor in {"OTROS", "ALTRES"}:
        return "OTROS"
    raise ValueError(f"tipus_objecte inválido: {raw}. Usa IBI, IVTM, Expediente Ejecutivo u Otros.")

async def _subir_documentos_p3(page: Page, archivos: list[Path]) -> None:
    # Limitamos a un máximo de 5 archivos según requerimiento
    archivos_a_subir = archivos[:5]
    logging.info(f"[P3] Iniciando subida de {len(archivos_a_subir)} archivo(s)...")

    for i, archivo in enumerate(archivos_a_subir, 1):
        if not archivo.exists():
            logging.error(f"[P3] Archivo no encontrado: {archivo}")
            continue

        logging.info(f"[P3] Subiendo archivo {i}/{len(archivos_a_subir)}: {archivo.name}")

        # 1. Abrir popup (Botón en página principal)
        await page.get_by_role("button", name=re.compile(r"Carregar\s+Fitxer", re.IGNORECASE)).first.click()

        # 2. Localizar Modal e Iframe
        modal = page.locator("#fitxer").first
        await modal.wait_for(state="visible", timeout=15000)
        frame = page.frame_locator("#contingut_fitxer").first

        # 3. Seleccionar archivo (Seleccionar fitxer)
        file_input = frame.locator("input[type='file'][name='qqfile']").first
        await file_input.wait_for(state="attached", timeout=20000)
        await file_input.set_input_files(str(archivo.resolve()))

        # 4. Pulsar botón 'Carregar' (penjar_fitxers)
        logging.info(f"[P3] ({i}) Procesando subida...")
        await frame.locator("#penjar_fitxers").first.click()

        # 5. Esperar éxito
        success_text = frame.locator("#textSuccess").first
        await success_text.wait_for(state="visible", timeout=30000)
        
        # 6. Cerrar popup (Botón Continuar del popup)
        logging.info(f"[P3] ({i}) Confirmado. Cerrando popup...")
        await frame.locator("#continuar").first.click()

        # Esperamos a que el modal desaparezca antes de ir a por el siguiente
        await modal.wait_for(state="hidden", timeout=15000)
        await page.wait_for_timeout(1000) # Pausa de seguridad entre archivos


async def _avanzar_a_presentacion_p3(page: Page) -> None:
    logging.info("[P3] Continuando al paso de presentación...")
    await page.locator("input[type='submit'][name='form0:j_id66'][value='Continuar']").first.click()
    await page.wait_for_load_state("domcontentloaded")

    boton_firma = page.locator("input[type='button'][value='Signar i Presentar']").first
    await boton_firma.wait_for(state="visible", timeout=20000)
    logging.info("[P3] Pantalla 'Signar i Presentar' detectada (no se pulsa en modo demo).")


async def rellenar_formulario_p3(page: Page, config: BaseOnlineConfig, data: BaseOnlineReposicionData) -> None:
    logging.info("[P3] Rellenando formulario de Recurso de Reposición...")

    # 1. Inputs radio: tipo de objeto
    tipus_objecte = _normalizar_tipus_objecte(data.tipus_objecte)
    radio_selector = {
        "IBI": config.p3_radio_ibi,
        "IVTM": config.p3_radio_ivtm,
        "EXPEDIENTE EJECUTIVO": config.p3_radio_executiu,
        "OTROS": config.p3_radio_altres,
    }[tipus_objecte]
    logging.info(f"[P3] Seleccionando tipo de objeto: {tipus_objecte}")
    await page.locator(radio_selector).first.click()

    # 2. Dades específiques
    logging.info("[P3] Introduciendo datos específicos...")
    await page.locator(config.p3_textarea_dades).first.fill(data.dades_especifiques)

    # 3. Tipo de solicitud
    logging.info(f"[P3] Seleccionando tipo de solicitud: value={data.tipus_solicitud_value}")
    await page.locator(config.p3_select_tipus).first.select_option(value=str(data.tipus_solicitud_value))

    # 4. Exposición
    logging.info("[P3] Introduciendo exposición...")
    await page.locator(config.p3_textarea_exposo).first.fill(data.exposo)

    # 5. Solicitud
    logging.info("[P3] Introduciendo solicitud...")
    await page.locator(config.p3_textarea_solicito).first.fill(data.solicito)

    # 6. Botón Continuar (Página 1 -> Página Documentos)
    logging.info("[P3] Pulsando el botón de continuar...")
    await page.locator(config.p3_button_continuar).first.click()
    await page.wait_for_load_state("domcontentloaded")

    # 7. Subida de múltiples documentos (Bucle de popups)
    if data.archivos_adjuntos:
        await _subir_documentos_p3(page, data.archivos_adjuntos)
    else:
        logging.warning("[P3] No hay archivos adjuntos para subir.")

    # 8. Paso final de confirmación (Llegar hasta el botón de firma)
    await _avanzar_a_presentacion_p3(page)