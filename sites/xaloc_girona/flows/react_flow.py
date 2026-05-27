from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Iterable

from playwright.async_api import Page, TimeoutError

from core.contact_defaults import get_default_contact_email
from sites.xaloc_girona.data_models import DatosMandatario, DatosMulta

logger = logging.getLogger("xaloc_automation.xaloc_girona.react")

DELAY_MS = 500
REG_URL_MARKER = "seu.xalocgirona.cat/sta/reg/tramit/"
AUTH_FILE_TOKENS = ("autoriz", "autoriza", "acredit", "mandat", "represent")
NATURAL_NAME_SELECTOR = "#name-of-natural-for-ungrouped-value"
NATURAL_FIRST_SURNAME_SELECTOR = "#firstSurname-of-natural-for-ungrouped-value"
NATURAL_LAST_SURNAME_SELECTOR = "#lastSurname-of-natural-for-ungrouped-value"
LEGAL_NAME_CANDIDATES = (
    "#name-of-legal-for-ungrouped-value",
    "#businessName-of-legal-for-ungrouped-value",
    "#business-name-for-ungrouped-value",
    'input[id*="legal"][id*="name"]',
    'input[id*="juridic"][id*="name"]',
    'input[id*="business"]',
)


async def is_react_reg_flow(page: Page) -> bool:
    try:
        return REG_URL_MARKER in (page.url or "").lower()
    except Exception:
        return False


def _norm(value: object) -> str:
    return str(value or "").strip()


def _clean_doc(value: str) -> str:
    return _norm(value).upper().replace(" ", "")


def _mandatario_doc(m: DatosMandatario | None) -> str:
    if not m:
        return ""
    if m.tipo_persona == "JURIDICA":
        return _clean_doc(f"{m.cif_documento or ''}{m.cif_control or ''}")
    return _clean_doc(f"{m.doc_numero or ''}{m.doc_control or ''}")


def _mandatario_name_parts(m: DatosMandatario | None) -> tuple[str, str, str]:
    if not m:
        return "", "", ""
    if m.tipo_persona == "JURIDICA":
        return _norm(m.razon_social), "", ""
    return _norm(m.nombre), _norm(m.apellido1), _norm(m.apellido2)


def _interesado_doc_and_name_parts(datos: DatosMulta) -> tuple[str, str, str, str]:
    doc = _clean_doc(datos.interesado_doc or "")
    nombre = _norm(datos.interesado_nombre)
    apellido1 = _norm(datos.interesado_apellido1)
    apellido2 = _norm(datos.interesado_apellido2)
    if doc and nombre and apellido1:
        return doc, nombre, apellido1, apellido2

    return _mandatario_doc(datos.mandatario), *_mandatario_name_parts(datos.mandatario)


def _interesado_legal_name(datos: DatosMulta) -> str:
    m = datos.mandatario
    if m and m.tipo_persona == "JURIDICA":
        return _norm(m.razon_social)
    parts = [datos.interesado_nombre, datos.interesado_apellido1, datos.interesado_apellido2]
    return " ".join(_norm(part) for part in parts if _norm(part))


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).lower()
    except Exception:
        return str(path).lower()


def _looks_like_authorization(path: Path) -> bool:
    text = path.name.lower()
    return any(token in text for token in AUTH_FILE_TOKENS)


def select_mandate_file(datos: DatosMulta) -> Path:
    candidates: list[Path] = []
    for p in datos.required_client_doc_paths or []:
        if p and _looks_like_authorization(p):
            candidates.append(p)
    for p in datos.archivos_para_subir:
        if p and _looks_like_authorization(p):
            candidates.append(p)

    seen: set[str] = set()
    unique: list[Path] = []
    for p in candidates:
        key = _path_key(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    if not unique:
        raise RuntimeError(
            "xaloc_girona/react: no se encontro autorizacion/mandato entre los archivos. "
            "La nueva sede exige subir 'Mandat de representacio' antes del formulario."
        )
    return unique[0]


def select_notification_files(datos: DatosMulta, mandate_file: Path | None) -> list[Path]:
    mandate_key = _path_key(mandate_file) if mandate_file else ""
    selected: list[Path] = []
    seen: set[str] = set()
    for p in datos.archivos_para_subir:
        if not p:
            continue
        key = _path_key(p)
        if key == mandate_key or key in seen:
            continue
        seen.add(key)
        selected.append(p)
    if not selected:
        raise RuntimeError("xaloc_girona/react: no hay documentos para subir en el slot Notificacio.")
    return selected


def split_motivos_for_react(motivos: str) -> tuple[str, str]:
    text = _norm(motivos)
    if not text:
        return "", ""

    expone_match = re.search(r"\bEXPON[EO]\s*:", text, re.IGNORECASE)
    solicita_match = re.search(r"\bSOLICIT[AO]\s*:", text, re.IGNORECASE)
    if expone_match and solicita_match and expone_match.start() < solicita_match.start():
        expone = text[expone_match.end():solicita_match.start()].strip()
        solicita = text[solicita_match.end():].strip()
        return expone or text, solicita
    if solicita_match:
        return text[:solicita_match.start()].strip(), text[solicita_match.end():].strip()
    return text, ""


async def _click_if_visible(page: Page, selector: str, *, timeout_ms: int = 2500) -> bool:
    loc = page.locator(selector).first
    try:
        await loc.wait_for(state="visible", timeout=timeout_ms)
        await loc.scroll_into_view_if_needed(timeout=1000)
        await loc.click(no_wait_after=True)
        await page.wait_for_timeout(DELAY_MS)
        return True
    except Exception:
        return False


async def _click_continue_credentials(page: Page) -> None:
    button = page.locator('button[data-testid="choosepars-continue-button"]').first
    await button.wait_for(state="visible", timeout=30000)
    await button.scroll_into_view_if_needed()
    await button.click(no_wait_after=True)
    await page.wait_for_timeout(1200)


async def _fill_text(page: Page, selector: str, value: object, *, required: bool = True) -> None:
    text = _norm(value)
    if required and not text:
        raise RuntimeError(f"xaloc_girona/react: valor obligatorio vacio para selector {selector}")
    loc = page.locator(selector).first
    await loc.wait_for(state="visible", timeout=20000)
    await loc.scroll_into_view_if_needed()
    await loc.fill(text)
    await loc.dispatch_event("input")
    await loc.dispatch_event("change")
    await loc.dispatch_event("blur")
    await page.wait_for_timeout(150)


async def _is_visible(page: Page, selector: str, *, timeout_ms: int = 800) -> bool:
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return False


async def _find_legal_name_selector(page: Page) -> str:
    for selector in LEGAL_NAME_CANDIDATES:
        if await _is_visible(page, selector, timeout_ms=500):
            return selector

    selector = await page.evaluate(
        """() => {
            const labelRe = /ra[oóò]\\s*social|raz[oó]n\\s*social|denominaci[oó]|nom\\s+social/i;
            const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea'));
            for (const input of inputs) {
                const id = input.id || '';
                const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                let text = label ? label.innerText || '' : '';
                let node = input.parentElement;
                for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
                    text += ' ' + (node.innerText || '');
                }
                if (labelRe.test(text)) {
                    if (id) return `#${CSS.escape(id)}`;
                    if (input.name) return `[name="${CSS.escape(input.name)}"]`;
                }
            }
            return '';
        }"""
    )
    if selector:
        return str(selector)
    raise RuntimeError("xaloc_girona/react: no se encontro campo de razon social para interesado juridico.")


async def _fill_rendered_interested_variant(
    page: Page,
    *,
    natural_name: str,
    natural_first_surname: str,
    natural_last_surname: str,
    legal_name: str,
) -> None:
    if await _is_visible(page, NATURAL_NAME_SELECTOR, timeout_ms=2500):
        logger.info("XALOC React: formulario de interesado detectado como persona fisica.")
        await _fill_text(page, NATURAL_NAME_SELECTOR, natural_name)
        await _fill_text(page, NATURAL_FIRST_SURNAME_SELECTOR, natural_first_surname)
        await _fill_text(page, NATURAL_LAST_SURNAME_SELECTOR, natural_last_surname, required=False)
        return

    logger.info("XALOC React: formulario de interesado detectado como persona juridica.")
    selector = await _find_legal_name_selector(page)
    await _fill_text(page, selector, legal_name)


async def _check_radio_or_checkbox(page: Page, selector: str) -> None:
    loc = page.locator(selector).first
    await loc.wait_for(state="attached", timeout=20000)
    await loc.scroll_into_view_if_needed()
    try:
        await loc.check(force=True)
    except Exception:
        await loc.click(force=True)
    await page.wait_for_timeout(250)


async def _upload_files(page: Page, selector: str, files: Iterable[Path]) -> None:
    paths = [Path(p) for p in files if p]
    if not paths:
        raise RuntimeError(f"xaloc_girona/react: lista de archivos vacia para {selector}")
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(str(p))
    loc = page.locator(selector).first
    await loc.wait_for(state="attached", timeout=20000)
    await loc.set_input_files([str(p) for p in paths])
    await page.wait_for_timeout(2500)


async def _get_file_input_for_card(page: Page, label_pattern: str) -> str:
    input_id = await page.evaluate(
        """({ pattern }) => {
            const re = new RegExp(pattern, 'i');
            const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
            for (const input of inputs) {
                let node = input.parentElement;
                for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
                    const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (re.test(text)) return input.id || '';
                }
            }
            return '';
        }""",
        {"pattern": label_pattern},
    )
    if not input_id:
        raise RuntimeError(f"xaloc_girona/react: no se encontro input file para tarjeta {label_pattern!r}")
    return f'input[id="{input_id}"]'


async def _wait_for_url_part(page: Page, part: str, *, timeout_ms: int = 30000) -> None:
    try:
        await page.wait_for_url(re.compile(re.escape(part), re.IGNORECASE), timeout=timeout_ms)
    except TimeoutError:
        if part.lower() not in (page.url or "").lower():
            raise


async def completar_representacion_react(page: Page, datos: DatosMulta) -> Path:
    logger.info("XALOC React: completando pantalla de credenciales/representacion.")

    if "credentials" in (page.url or "").lower() and "representacionjuridica" not in (page.url or "").lower():
        await _click_continue_credentials(page)

    await _wait_for_url_part(page, "/credentials/representacionjuridica", timeout_ms=30000)

    await _check_radio_or_checkbox(page, "#ungrouped-radio-text-radiogroup-representante")
    doc, nombre, apellido1, apellido2 = _interesado_doc_and_name_parts(datos)
    logger.info(
        "XALOC React: interesado para representacion doc=%s nombre=%s apellido1=%s",
        doc,
        nombre,
        apellido1,
    )
    await _fill_text(page, "#id-number-for-ungrouped-value", doc)
    await page.wait_for_timeout(1200)
    await _fill_rendered_interested_variant(
        page,
        natural_name=nombre,
        natural_first_surname=apellido1,
        natural_last_surname=apellido2,
        legal_name=_interesado_legal_name(datos),
    )
    await _check_radio_or_checkbox(page, "#ungrouped-radio-text-radiogroup-MANDATE")

    mandate = select_mandate_file(datos)
    logger.info("XALOC React: subiendo mandato/autorizacion: %s", mandate)
    await _upload_files(page, "#input-for-file-MANDATE", [mandate])
    await _click_continue_credentials(page)
    await _wait_for_url_part(page, "/formulari/data", timeout_ms=30000)
    return mandate


async def rellenar_datos_react(page: Page, datos: DatosMulta) -> None:
    logger.info("XALOC React: rellenando datos de solicitud.")
    await _wait_for_url_part(page, "/formulari/data", timeout_ms=30000)
    await _fill_text(page, 'input[name="RT_NUMDEN"]', datos.num_denuncia)
    await _fill_text(page, 'input[name="RT_MATRICULA"]', datos.matricula)
    await _fill_text(page, 'input[name="RT_NUMEXP_SAN"]', datos.num_expediente)

    expone, solicita = split_motivos_for_react(datos.motivos)
    if expone:
        # El texto historico suele contener EXPONE/SOLICITA; si no, se duplica como exposicion.
        await _fill_text(page, 'textarea[name="RT_MOTIUS"]', expone, required=False)
    if solicita:
        await _fill_text(page, 'textarea[name="RT_SOL"]', solicita, required=False)

    await page.locator('[data-testid="next-step-button"]').first.click(no_wait_after=True)
    await page.wait_for_timeout(1500)
    await _wait_for_url_part(page, "/formulari/documents", timeout_ms=30000)


async def subir_documentos_react(page: Page, datos: DatosMulta, mandate_file: Path) -> None:
    logger.info("XALOC React: subiendo documentos en Notificacio.")
    await _wait_for_url_part(page, "/formulari/documents", timeout_ms=30000)
    files = select_notification_files(datos, mandate_file)
    selector = await _get_file_input_for_card(page, r"Notificaci[oó]")
    logger.info("XALOC React: subiendo %s archivo(s) en Notificacio: %s", len(files), files)
    await _upload_files(page, selector, files)
    await page.locator('[data-testid="next-step-button"]').first.click(no_wait_after=True)
    await page.wait_for_timeout(1500)
    await _wait_for_url_part(page, "/formulari/summary", timeout_ms=30000)


async def _select_existing_email(page: Page, email: str) -> None:
    input_loc = page.locator('input[name="existing-notification-email"]').first
    try:
        await input_loc.wait_for(state="attached", timeout=8000)
        current = _norm(await input_loc.input_value())
        if current:
            return
    except Exception:
        return

    combo = page.get_by_role("combobox").first
    await combo.wait_for(state="visible", timeout=10000)
    await combo.click()
    await page.wait_for_timeout(400)

    wanted = _norm(email).lower()
    option_count = await page.locator('[role="option"]').count()
    chosen = None
    fallback = None
    for idx in range(option_count):
        option = page.locator('[role="option"]').nth(idx)
        text = _norm(await option.inner_text()).lower()
        if text and fallback is None and "@" in text and "altre" not in text and "otro" not in text:
            fallback = option
        if wanted and text == wanted:
            chosen = option
            break
    if chosen is None:
        chosen = fallback
    if chosen is None:
        raise RuntimeError("xaloc_girona/react: no hay opcion de email existente seleccionable.")
    await chosen.click()
    await page.wait_for_timeout(700)


def _confirm_before_presentar_if_enabled() -> None:
    confirm = (os.getenv("XALOC_CONFIRM_BEFORE_SEND") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not confirm:
        return

    print("\n" + "=" * 80)
    print("PAUSA INTERACTIVA XALOC REG")
    print("=" * 80)
    print("La nueva sede XALOC esta lista para pulsar PRESENTAR.")
    print("Revisa en el navegador que datos, documentos y declaraciones sean correctos.")
    print("Pulsa Enter para PRESENTAR realmente, o Ctrl+C para cancelar.")
    print("=" * 80)
    try:
        input()
    except KeyboardInterrupt:
        logger.warning("Usuario cancelo PRESENTAR en flujo React XALOC.")
        raise


async def presentar_react(page: Page, datos: DatosMulta) -> str:
    logger.info("XALOC React: preparando presentacion final.")
    await _wait_for_url_part(page, "/formulari/summary", timeout_ms=30000)
    await _select_existing_email(page, datos.email or get_default_contact_email())
    await _check_radio_or_checkbox(page, 'input[name="privacy"]')
    await _check_radio_or_checkbox(page, 'input[name="affirmation"]')

    submit = page.get_by_role("button", name=re.compile(r"^presentar$", re.IGNORECASE)).first
    await submit.wait_for(state="visible", timeout=15000)
    try:
        disabled = await submit.is_disabled()
    except Exception:
        disabled = False
    if disabled:
        raise RuntimeError("xaloc_girona/react: boton PRESENTAR sigue deshabilitado.")

    _confirm_before_presentar_if_enabled()

    logger.info("XALOC React: pulsando PRESENTAR.")
    await submit.click(no_wait_after=True)
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    try:
        await page.wait_for_url(re.compile(r"(justif|receipt|registre|resum|final|success|tramita)", re.IGNORECASE), timeout=120000)
    except Exception:
        logger.warning("XALOC React: no se detecto URL final conocida tras PRESENTAR. URL actual=%s", page.url)
    return page.url


async def ejecutar_flujo_react(page: Page, datos: DatosMulta) -> str:
    mandate = await completar_representacion_react(page, datos)
    await rellenar_datos_react(page, datos)
    await subir_documentos_react(page, datos, mandate)
    return await presentar_react(page, datos)


__all__ = [
    "ejecutar_flujo_react",
    "is_react_reg_flow",
    "select_mandate_file",
    "select_notification_files",
    "split_motivos_for_react",
]
