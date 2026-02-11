from __future__ import annotations

import logging
import re
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

CARPETA_URL = "https://servcla.madrid.es/RGAYT_FTCARPETA/#/"
ANOTACION_TIMEOUT_MS = 60000
TABLA_TIMEOUT_MS = 90000
DOWNLOAD_TIMEOUT_MS = 90000


class MadridFirmaNonFatalError(RuntimeError):
    """
    Error no fatal: el tramite pudo haberse enviado, pero fallo un paso post-envio
    (por ejemplo mover el justificante a la carpeta final).
    """


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
    motivo_to_folder = {
        "identificacion": "IDENTIFICACIONES",
        "denuncia": "ALEGACIONES",
        "propuesta de resolucion": "ALEGACIONES",
        "extraordinario de revision": "EXTRAORDINARIOS DE REVISION",
        "subsanacion": "SUBSANACIONES",
        "reclamaciones": "RECLAMACIONES",
        "requerimiento embargo": "EMBARGOS",
        "sancion": "SANCIONES",
        "apremio": "APREMIOS",
        "embargo": "EMBARGOS",
    }

    fase_norm = _normalize_text(fase_raw)
    for motivo_key, folder_name in motivo_to_folder.items():
        if motivo_key in fase_norm:
            return folder_name

    logger.warning("No match for phase '%s', defaulting to base folder.", fase_raw)
    return ""


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
    if target_singular == folder_singular:
        return True

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

    ruta_recursos = _find_or_create_subfolder(ruta_cliente_base, "RECURSOS TELEMATICOS")

    if fase_procedimiento:
        folder_name = _get_folder_name_from_fase(fase_procedimiento)
        if folder_name:
            return _find_or_create_subfolder(ruta_recursos, folder_name)

    return ruta_recursos


def _justificante_filename(num_expediente: str) -> str:
    clean_exp = str(num_expediente).replace("/", "-").replace("\\", "-")
    clean_exp = re.sub(r'[<>:"|?*\x00-\x1F]', "_", clean_exp).strip().rstrip(". ")
    if not clean_exp:
        clean_exp = "UNKNOWN"
    return f"JUSTIFICANTE - {clean_exp}.pdf"


async def _guardar_justificante_temporal(download: Any, *, num_expediente: str, tmp_dir: Path) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / _justificante_filename(num_expediente)
    await download.save_as(tmp_path)
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


def _normalizar_anotacion(value: str) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _extraer_n_expediente(payload: dict) -> str:
    keys = (
        "expediente",
        "expediente_num",
        "denuncia_num",
        "Expedient",
        "nExp",
        "numero_expediente",
    )
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "UNKNOWN"


def _extraer_anotacion_de_texto(texto: str) -> str:
    if not texto:
        return ""

    # Caso esperado: "Numero de anotacion: 20260215781"
    m = re.search(
        r"numero\s+de\s+anotaci\w*n\s*:\s*([0-9/]{8,20})",
        texto,
        flags=re.IGNORECASE,
    )
    if m:
        return _normalizar_anotacion(m.group(1))

    # Fallback: cualquier numero largo con formato de anotacion.
    m = re.search(r"\b(20\d{2}/?\d{6,10})\b", texto)
    if m:
        return _normalizar_anotacion(m.group(1))

    return ""


async def _extraer_anotacion_desde_exito(page: Page) -> str:
    # Esperar a que exista contenido de "acuse de recibo / datos de registro".
    await page.wait_for_function(
        r"""() => {
            const root = document.querySelector("form") || document.body;
            if (!root) return false;
            const normalize = (s) =>
              (s || "")
                .toString()
                .normalize("NFD")
                .replace(/[\u0300-\u036f]/g, "")
                .toLowerCase();
            const txt = normalize(root.innerText || "");
            return txt.includes("datos de registro") || txt.includes("numero de anotacion");
        }""",
        timeout=ANOTACION_TIMEOUT_MS,
    )

    # 1) Intento estructural: form > div/ul/li (como comentas).
    texto_form = await page.evaluate(
        r"""() => {
            const root = document.querySelector("form") || document.body;
            if (!root) return "";
            const nodes = root.querySelectorAll("ul, li, div, p, span, strong, b");
            let out = "";
            for (const n of nodes) {
                const t = (n.textContent || "").trim();
                if (t) out += t + "\n";
            }
            return out;
        }"""
    )

    texto_form_norm = "".join(
        c for c in unicodedata.normalize("NFD", texto_form.lower())
        if unicodedata.category(c) != "Mn"
    )
    logger.info("Longitud texto form para extraer anotacion: %s", len(texto_form_norm))
    anotacion = _extraer_anotacion_de_texto(texto_form_norm)

    # 2) Fallback: body completo.
    if not anotacion:
        texto_body = await page.locator("body").inner_text()
        texto_body_norm = "".join(
            c for c in unicodedata.normalize("NFD", texto_body.lower())
            if unicodedata.category(c) != "Mn"
        )
        logger.info("Longitud texto body para extraer anotacion: %s", len(texto_body_norm))
        anotacion = _extraer_anotacion_de_texto(texto_body_norm)

    if not anotacion:
        raise RuntimeError("No se pudo extraer el numero de anotacion del mensaje de exito.")

    logger.info("Anotacion detectada en exito: %s", anotacion)
    return anotacion


async def _abrir_fila_por_anotacion(page: Page, anotacion_objetivo: str) -> None:
    await page.goto(CARPETA_URL, wait_until="domcontentloaded", timeout=TABLA_TIMEOUT_MS)
    await page.wait_for_selector("table.iam-b-table tbody tr", state="attached", timeout=TABLA_TIMEOUT_MS)

    target = _normalizar_anotacion(anotacion_objetivo)
    deadline_ms = TABLA_TIMEOUT_MS
    poll_ms = 700
    elapsed = 0

    while elapsed <= deadline_ms:
        celdas = page.locator("table.iam-b-table tbody tr td:first-child div")
        count = await celdas.count()
        for idx in range(count):
            celda = celdas.nth(idx)
            text = (await celda.inner_text()).strip()
            if _normalizar_anotacion(text) != target:
                continue

            logger.info("Anotacion localizada en tabla: %s (texto celda: %s)", anotacion_objetivo, text)
            try:
                await celda.scroll_into_view_if_needed()
            except Exception:
                pass

            click_ok = False
            for click_mode in ("normal", "force", "dom"):
                try:
                    if click_mode == "normal":
                        await celda.click(timeout=5000)
                    elif click_mode == "force":
                        await celda.click(timeout=5000, force=True)
                    else:
                        await celda.evaluate("el => el.click()")
                    click_ok = True
                    logger.info("Click en celda de anotacion realizado (%s).", click_mode)
                    break
                except Exception:
                    continue

            if not click_ok:
                raise RuntimeError(
                    f"Se encontro la anotacion {anotacion_objetivo}, pero no se pudo clickar su celda."
                )

            await page.wait_for_timeout(500)
            logger.info("Fila de carpeta seleccionada para anotacion: %s", anotacion_objetivo)
            return

        await page.wait_for_timeout(poll_ms)
        elapsed += poll_ms

    raise RuntimeError(f"No se encontro en carpeta la fila con anotacion {anotacion_objetivo}.")


async def _descargar_justificante_desde_carpeta(
    page: Page,
    *,
    anotacion: str,
    expediente_nombre: str,
    tmp_dir: Path,
) -> Path:
    await _abrir_fila_por_anotacion(page, anotacion)

    label = page.locator("label", has_text=re.compile(r"Justificante\s+de\s+registro", re.IGNORECASE)).first
    await label.wait_for(state="visible", timeout=TABLA_TIMEOUT_MS)

    download = None
    click_attempts = (
        lambda: label.click(),
        lambda: label.click(force=True),
        lambda: label.evaluate("el => el.click()"),
    )
    for click_action in click_attempts:
        try:
            async with page.expect_download(timeout=30000) as download_info:
                await click_action()
            download = await download_info.value
            break
        except TimeoutError:
            continue

    if download is None:
        raise RuntimeError(
            "No se detecto descarga al pulsar 'Justificante de registro' tras varios intentos."
        )

    return await _guardar_justificante_temporal(
        download,
        num_expediente=expediente_nombre,
        tmp_dir=tmp_dir,
    )


async def ejecutar_firma_madrid(
    page: Page,
    config: "MadridConfig",
    destino_descarga: Path,
    payload: dict,
) -> Page:
    """
    Firma y envia en Madrid sin descargar en SIGNA.

    Tras exito:
    1) Extrae numero de anotacion.
    2) Navega a carpeta de tramites.
    3) Busca la fila por anotacion (normalizando sin '/').
    4) Descarga "Justificante de registro" y lo mueve a carpeta final.
    """
    logger.info("=" * 80)
    logger.info("FIRMA MADRID - EXPEDIENTE: %s", destino_descarga.stem)
    logger.info("=" * 80)

    _ = destino_descarga
    fase = payload.get("fase_procedimiento")
    id_recurso = payload.get("idRecurso") or destino_descarga.stem
    tmp_dir = Path("tmp") / "madrid" / "justificantes" / str(id_recurso)

    # 1. Ir a pantalla de firma (SIGNA) si no estamos ya.
    if config.url_signa_firma_contains.lower() not in (page.url or "").lower():
        await page.wait_for_selector(
            config.firma_registrar_selector,
            state="visible",
            timeout=config.default_timeout,
        )
        logger.info("Pantalla pre-firma detectada. Entrando en SIGNA (Firma y registrar)...")
        try:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=config.navigation_timeout):
                await page.click(config.firma_registrar_selector)
        except TimeoutError:
            logger.warning("No se detecto navegacion tras 'Firma y registrar'; continuando.")

    # 2. Confirmar envio (checkbox + boton final).
    await page.wait_for_selector(
        config.verificar_documento_selector,
        state="attached",
        timeout=config.firma_navigation_timeout,
    )
    logger.info("Pantalla SIGNA detectada.")

    logger.info("Confirmando envio del tramite (checkbox + boton)...")
    checkbox = page.locator("#consentimiento")
    if await checkbox.count() > 0:
        await checkbox.check()

    firmar_btn = page.locator('input.button.button4[name="btnFirmar"]')
    if await firmar_btn.count() == 0:
        raise RuntimeError("Boton final de firma/envio no encontrado (btnFirmar).")

    prev_url = page.url or ""
    try:
        await page.wait_for_timeout(2000)
        async with page.expect_navigation(
            wait_until="domcontentloaded",
            timeout=config.firma_navigation_timeout,
        ):
            await firmar_btn.click()
    except TimeoutError:
        logger.warning("No se detecto navegacion tras el envio; continuando con espera blanda.")

    try:
        await page.wait_for_function(
            "prev => window.location.href !== prev",
            arg=prev_url,
            timeout=15000,
        )
    except Exception:
        pass

    await page.wait_for_timeout(1200)

    # 3. Extraer anotacion y descargar justificante desde carpeta.
    anotacion = await _extraer_anotacion_desde_exito(page)
    expediente_nombre = _extraer_n_expediente(payload)

    tmp_pdf_path = await _descargar_justificante_desde_carpeta(
        page=page,
        anotacion=anotacion,
        expediente_nombre=expediente_nombre,
        tmp_dir=tmp_dir,
    )

    # 4. Mover justificante a carpeta final.
    ruta_recursos = _construir_ruta_recursos_telematicos(payload, fase)
    try:
        _mover_justificante_a_destino(tmp_pdf_path, destino_dir=ruta_recursos)
    except Exception as e:
        raise MadridFirmaNonFatalError(
            f"Tramite enviado, pero no se pudo mover el justificante a la carpeta final: {e}"
        ) from e

    logger.info("=" * 80)
    logger.info("PROCESO DE FIRMA Y ENVIO COMPLETADO CON EXITO")
    logger.info("=" * 80)
    return page
