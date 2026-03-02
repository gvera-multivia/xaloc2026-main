from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page

from sites.redsara.config import RedSaraConfig
from sites.redsara.data_models import RedSaraTarget
from sites.redsara.flows.certificado import aceptar_certificado_clave_si_aparece


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().upper().split())


def _map_fase_folder(fase: str) -> str:
    mapping = {
        "IDENTIFICACION": "IDENTIFICACIONES",
        "REQUERIMIENTOS DE IDENTIFICACION": "IDENTIFICACIONES",
        "EMBARGO": "EMBARGOS",
        "SANCION": "SANCIONES",
        "DENUNCIA": "DENUNCIAS",
        "APREMIO": "APREMIOS",
        "PROPUESTA DE RESOLUCION": "PROPUESTAS DE RESOLUCION",
        "RESOLUCION": "PROPUESTAS DE RESOLUCION",
        "ALZADA": "SANCIONES",
    }
    normalized = _normalize_text(fase)
    for key, value in mapping.items():
        if key in normalized:
            return value
    return "OTROS"


def _build_destination_folder(datos: RedSaraTarget) -> Path | None:
    ruta_cliente = datos.payload.get("ruta_cliente")
    if not ruta_cliente:
        return None
    base = Path(ruta_cliente)
    if not base.exists():
        return None

    telem1 = base / "RECURSOS TELEM\u00c1TICOS"
    telem2 = base / "RECURSOS TELEMATICOS"
    telem = telem1 if telem1.exists() else telem2
    telem.mkdir(parents=True, exist_ok=True)

    fase_folder = telem / _map_fase_folder(datos.recurso.fase)
    fase_folder.mkdir(parents=True, exist_ok=True)
    return fase_folder


async def descargar_justificante_redsara(page: Page, config: RedSaraConfig, datos: RedSaraTarget) -> Path:
    await aceptar_certificado_clave_si_aparece(page, config, timeout=config.flow_timeouts.medium_wait)

    await page.get_by_role("heading", name="Detalle del registro").wait_for(timeout=config.flow_timeouts.save_wait)

    boton = page.locator(config.selectors.descargar_justificante_btn).first
    await boton.wait_for(state="visible", timeout=config.flow_timeouts.long_wait)
    async with page.expect_download() as download_info:
        await boton.click()
    download = await download_info.value

    expediente = (datos.recurso.expediente or "SIN_EXPEDIENTE").strip()
    today = datetime.now().strftime("%Y%m%d")
    temp_dir = config.dir_screenshots / f"{today}_redsara_justificantes"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target_tmp = temp_dir / f"JUSTIFICANTE - {expediente}.pdf"
    await download.save_as(target_tmp)
    await download.delete()

    destino = _build_destination_folder(datos)
    if destino:
        destino_file = destino / target_tmp.name
        shutil.copy2(target_tmp, destino_file)
        return destino_file
    return target_tmp
