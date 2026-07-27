from __future__ import annotations

import re
import logging
import os
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from .cookies import dismiss_cookie_banner_if_present

if TYPE_CHECKING:
    from playwright.async_api import Frame, Page
    from ..config import ServeiCatTransConfig
    from ..data_models import ServeiCatTransTarget

from .form_scope import wait_form_scope

FAST_ACTION_TIMEOUT_MS = 1200
FAST_SELECT_TIMEOUT_MS = 1500
CASCADE_OPTIONS_TIMEOUT_MS = int(os.getenv("XALOC_SERVEI_CASCADE_TIMEOUT_MS", "12000"))

_TIPO_VIA_LABEL_BY_CODE = {
    "AL": "Alameda",
    "AP": "Apartamento",
    "AV": "Avenida",
    "BD": "Bajada",
    "BC": "Barranco",
    "BO": "Barrio",
    "BL": "Bloque",
    "CA": "Calle",
    "CJ": "Callejon",
    "CM": "Camino",
    "CR": "Carretera",
    "CS": "Casas",
    "CH": "Chalet",
    "CO": "Colonia",
    "CT": "Cuesta",
    "DS": "Diseminado",
    "ED": "Edificio",
    "GL": "Glorieta",
    "GRAN VIA": "Gran Via",
    "GR": "Grupo",
    "LG": "Lugar",
    "MC": "Mercado",
    "PQ": "Parque",
    "PD": "Partida",
    "PJ": "Pasaje",
    "PS": "Paseo",
    "PT": "Playa",
    "PZ": "Plaza",
    "PL": "Plazuela",
    "PB": "Poblado",
    "PG": "Poligono",
    "PR": "Prolongacion",
    "PO": "Puerto",
    "RB": "Rambla",
    "RD": "Ronda",
    "SN": "Senda",
    "SD": "Subida",
    "TT": "Torrente",
    "TRAVESSERA": "Travessera",
    "TR": "Travesia",
    "UR": "Urbanizacion",
    "VE": "Vecindario",
    "VIA": "Via",
}

_TIPO_VIA_CODE_BY_ALIAS = {
    "ALAMEDA": "AL",
    "APARTAMENTO": "AP",
    "AVENIDA": "AV",
    "AVDA": "AV",
    "AV": "AV",
    "BAJADA": "BD",
    "BARRANCO": "BC",
    "BARRIO": "BO",
    "BLOQUE": "BL",
    "CALLE": "CA",
    "CARRER": "CA",
    "C": "CA",
    "CL": "CA",
    "C/": "CA",
    "CALLEJON": "CJ",
    "CAMINO": "CM",
    "CARRETERA": "CR",
    "CASAS": "CS",
    "CHALET": "CH",
    "COLONIA": "CO",
    "CUESTA": "CT",
    "DISEMINADO": "DS",
    "EDIFICIO": "ED",
    "GLORIETA": "GL",
    "GRAN VIA": "GRAN VIA",
    "GRUPO": "GR",
    "LUGAR": "LG",
    "MERCADO": "MC",
    "PARQUE": "PQ",
    "PARTIDA": "PD",
    "PASAJE": "PJ",
    "PASEO": "PS",
    "PS": "PS",
    "PLAYA": "PT",
    "PLAZA": "PZ",
    "PLAZUELA": "PL",
    "POBLADO": "PB",
    "POLIGONO": "PG",
    "PROLONGACION": "PR",
    "PUERTO": "PO",
    "RAMBLA": "RB",
    "RONDA": "RD",
    "SENDA": "SN",
    "SUBIDA": "SD",
    "TORRENTE": "TT",
    "TRAVESSERA": "TRAVESSERA",
    "TRAVESIA": "TR",
    "URBANIZACION": "UR",
    "VECINDARIO": "VE",
    "VIA": "VIA",
}


def _clean(v: object) -> str:
    raw = str(v or "")
    if any(ch in raw for ch in ("Ã", "Â", "â")):
        for enc in ("latin-1", "cp1252"):
            try:
                fixed = raw.encode(enc, errors="strict").decode("utf-8", errors="strict")
                if fixed:
                    raw = fixed
                    break
            except Exception:
                continue
    raw = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]+", " ", raw)
    return raw.strip()


def _sanitize_doc(v: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", _clean(v).upper())


def _sanitize_phone(v: object) -> str:
    raw = _clean(v)
    # El formulario de SCT valida teléfono numérico; evitamos caracteres inválidos.
    digits = re.sub(r"\D+", "", raw)
    return digits


def _phone_matches(expected: str, actual: str) -> bool:
    exp = _sanitize_phone(expected)
    cur = _sanitize_phone(actual)
    if not exp or not cur:
        return False
    if cur == exp:
        return True
    # Algunos campos autoformatean o añaden prefijo país.
    return cur.endswith(exp) or exp.endswith(cur)


def _norm_text(v: object) -> str:
    text = _clean(v).upper()
    if not text:
        return ""
    text = text.replace("/", " ").replace(".", " ").replace(",", " ")
    text = re.sub(r"[^A-Z0-9]+", " ", text).strip()
    return re.sub(r"\s+", " ", text)


def _infer_tipo_via_code(raw_tipo_via: str, raw_street: str = "") -> str:
    for candidate in (_norm_text(raw_tipo_via), _norm_text(raw_street)):
        if not candidate:
            continue
        if candidate in _TIPO_VIA_LABEL_BY_CODE:
            return candidate
        if candidate in _TIPO_VIA_CODE_BY_ALIAS:
            return _TIPO_VIA_CODE_BY_ALIAS[candidate]
        # Regex mas fuerte para detectar tipo de via al inicio (abreviaturas incluidas).
        regex_rules = (
            (r"^(?:CARRER|CALLE|C/|CL|C)\b", "CA"),
            (r"^(?:AVENIDA|AVDA|AV)\b", "AV"),
            (r"^(?:PASEO|PS)\b", "PS"),
            (r"^(?:PLAZA)\b", "PZ"),
            (r"^(?:RONDA)\b", "RD"),
            (r"^(?:RAMBLA)\b", "RB"),
            (r"^(?:TRAVESIA)\b", "TR"),
            (r"^(?:TRAVESSERA)\b", "TRAVESSERA"),
            (r"^(?:VIA)\b", "VIA"),
        )
        for pattern, code in regex_rules:
            if re.match(pattern, candidate):
                return code
        for alias, code in _TIPO_VIA_CODE_BY_ALIAS.items():
            if candidate.startswith(alias + " "):
                return code
    return ""


_TIPO_VIA_EXTRA_LABELS: dict[str, list[str]] = {
    "CA": ["Calle", "Carrer", "CALLE", "CARRER", "C/"],
    "AV": ["Avenida", "Avinguda", "AVENIDA", "AVINGUDA"],
    "PS": ["Paseo", "Passeig", "PASEO", "PASSEIG"],
    "PZ": ["Plaza", "Plaça", "PLAZA", "PLAÇA"],
    "RD": ["Ronda", "RONDA"],
    "RB": ["Rambla", "RAMBLA"],
    "CM": ["Camino", "Camí", "CAMINO", "CAMÍ"],
    "TR": ["Travesia", "Travessia", "TRAVESIA", "TRAVESSIA"],
    "PJ": ["Pasaje", "Passatge", "PASAJE", "PASSATGE"],
}


def _tipo_via_candidates(raw_tipo_via: str, raw_street: str = "") -> list[str]:
    candidates: list[str] = []
    code = _infer_tipo_via_code(raw_tipo_via, raw_street)
    if code:
        candidates.append(code)
        label = _TIPO_VIA_LABEL_BY_CODE.get(code, "")
        if label:
            candidates.append(label)
        # Añadir variantes catalanas/castellanas del mismo codigo
        for extra in _TIPO_VIA_EXTRA_LABELS.get(code, []):
            candidates.append(extra)
    raw = _clean(raw_tipo_via)
    if raw:
        candidates.append(raw)
    # Fallback: si no se pudo inferir nada, usar "Calle/Carrer" como tipo por defecto
    # (es el tipo de via mas comun y evita que el campo quede vacio).
    if not candidates:
        candidates.extend(["CA", "Calle", "Carrer", "CALLE", "CARRER"])
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = _norm_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _documento_persona_label(document: str) -> str:
    doc = _sanitize_doc(document)
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", doc):
        return "NIE"
    if re.fullmatch(r"\d{8}[A-Z]", doc):
        return "DNI"
    return "Pasaporte"


def _pais_emisor_candidates(pais: str) -> list[str]:
    raw = _clean(pais)
    if not raw:
        return []
    candidates = [raw]
    aliases = {
        "MARRUECOS": ["Marruecos", "Marroc"],
        "MARROC": ["Marroc", "Marruecos"],
        "MOROCCO": ["Marruecos", "Marroc"],
    }
    for candidate in aliases.get(_norm_text(raw), []):
        candidates.append(candidate)

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _norm_text(candidate)
        if key and key not in seen:
            seen.add(key)
            out.append(candidate)
    return out


def _documento_empresa_label(document: str) -> str:
    doc = _sanitize_doc(document)
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", doc):
        return "NIF de empresa"
    return "Documento de identidad extranjero"


async def _safe_fill(page: "Page | Frame", selector: str, value: str) -> bool:
    await dismiss_cookie_banner_if_present(page)
    text = _clean(value)
    if not text:
        return False
    locator = page.locator(selector)
    count = await locator.count()
    if count <= 0:
        return False

    for idx in range(count):
        candidate = locator.nth(idx)
        try:
            if not await candidate.is_visible():
                continue
        except Exception:
            continue

        try:
            is_disabled = await candidate.is_disabled()
        except Exception:
            is_disabled = False

        try:
            is_readonly = bool(
                await candidate.evaluate(
                    "(el) => !!el.readOnly || el.hasAttribute('readonly') || el.getAttribute('aria-readonly') === 'true'"
                )
            )
        except Exception:
            is_readonly = False

        if is_disabled or is_readonly:
            continue

        try:
            await candidate.fill(text, timeout=FAST_ACTION_TIMEOUT_MS)
            return True
        except Exception:
            try:
                await candidate.evaluate(
                    """(el, val) => {
                        el.value = "";
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                        el.value = String(val || "");
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                    }""",
                    text,
                )
                return True
            except Exception:
                continue
    return False


async def _safe_check(page: "Page | Frame", selector: str) -> bool:
    await dismiss_cookie_banner_if_present(page)
    locator = page.locator(selector).first
    if await locator.count() <= 0:
        logger.warning(f"Selector no encontrado para check: {selector}")
        return False
    try:
        # Intentar check estandar
        await locator.check(timeout=FAST_ACTION_TIMEOUT_MS, force=True)
        return True
    except Exception:
        try:
            # Intentar click si check falla (a veces los radios estan ocultos bajo un label)
            await locator.click(timeout=FAST_ACTION_TIMEOUT_MS, force=True)
            return True
        except Exception:
            try:
                # Opcion nuclear: JS click
                await locator.evaluate("(el) => { el.checked = true; el.click(); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                return True
            except Exception as e:
                logger.error(f"Error fatal intentando marcar {selector}: {e}")
                return False


async def _safe_click(page: "Page | Frame", selector: str) -> bool:
    await dismiss_cookie_banner_if_present(page)
    locator = page.locator(selector).first
    if await locator.count() <= 0:
        return False
    try:
        await locator.click(timeout=FAST_ACTION_TIMEOUT_MS)
    except Exception:
        return False
    return True


async def _safe_select_label(page: "Page | Frame", selector: str, label: str) -> bool:
    await dismiss_cookie_banner_if_present(page)
    wanted = _clean(label)
    if not wanted:
        return False

    locator = page.locator(selector).first
    if await locator.count() <= 0:
        return False

    try:
        # Intentar selecciÃ³n directa Playwright
        await locator.select_option(label=wanted, timeout=FAST_SELECT_TIMEOUT_MS)
        return True
    except Exception:
        # Fallback: buscar valor por texto normalizado (ignora acentos y mayÃºsculas) y seleccionar por valor
        opt_value = await locator.evaluate(
            """(el, wantedLabel) => {
                const normalize = (txt) => String(txt || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/[^a-zA-Z0-9]+/g, " ")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();
                const tokenSet = (txt) =>
                    new Set(
                        normalize(txt)
                            .split(" ")
                            .filter((t) => t.length >= 3)
                    );
                const wanted = normalize(wantedLabel);
                const wantedTokens = tokenSet(wantedLabel);
                const options = Array.from(el.options || []);
                
                // 1. Coincidencia exacta normalizada
                let match = options.find((opt) => normalize(opt.textContent || "") === wanted);
                
                // 2. Fallback a valor si el label coincide con el valor (ej: "CA" -> "CA")
                if (!match) {
                    match = options.find((opt) => normalize(opt.value || "") === wanted);
                }

                // 3. Coincidencia parcial solo para etiquetas suficientemente largas
                if (!match && wanted.length >= 4) {
                    match = options.find((opt) => normalize(opt.textContent || "").includes(wanted));
                }

                // 4. Coincidencia por tokens significativos (ignora orden y puntuacion)
                if (!match && wantedTokens.size > 0) {
                    match = options.find((opt) => {
                        const optTokens = tokenSet(opt.textContent || "");
                        if (optTokens.size === 0) return false;
                        for (const token of wantedTokens) {
                            if (!optTokens.has(token)) return false;
                        }
                        return true;
                    });
                }
                
                return match ? String(match.value || "") : "";
            }""",
            wanted,
        )
        if opt_value:
            try:
                await locator.select_option(value=opt_value, timeout=FAST_SELECT_TIMEOUT_MS)
                return True
            except Exception:
                return False
    return False


async def _safe_select_tipo_via(
    page: "Page | Frame",
    *,
    selector: str,
    raw_tipo_via: str,
    raw_street: str = "",
) -> bool:
    # Esperar a que el select tenga opciones evita fallos intermitentes por cascada tardia.
    if selector.startswith("#") and " " not in selector and "[" not in selector and ":" not in selector:
        await _wait_select_options(page, selector[1:], timeout_ms=5000, min_options=2)
    candidates = _tipo_via_candidates(raw_tipo_via, raw_street)
    for candidate in candidates:
        if await _safe_select_label(page, selector, candidate):
            logger.info(
                "servei_cat_trans tipo-via selected selector=%s raw=%r street=%r candidate=%r",
                selector,
                _clean(raw_tipo_via),
                _clean(raw_street),
                candidate,
            )
            return True

    # Fallback duro: si no casa ninguna inferencia, forzar Calle (CA).
    hard_fallback = ["CA", "Calle", "Carrer", "CALLE", "CARRER"]
    for candidate in hard_fallback:
        if await _safe_select_label(page, selector, candidate):
            logger.warning(
                "servei_cat_trans tipo-via fallback-forzado selector=%s raw=%r street=%r candidate=%r",
                selector,
                _clean(raw_tipo_via),
                _clean(raw_street),
                candidate,
            )
            return True

    logger.warning(
        "servei_cat_trans tipo-via not-selected selector=%s raw=%r street=%r candidates=%s",
        selector,
        _clean(raw_tipo_via),
        _clean(raw_street),
        candidates,
    )
    return False


async def _safe_select_via_id(page: "Page | Frame", element_id: str, label: str) -> bool:
    await dismiss_cookie_banner_if_present(page)
    wanted = _clean(label)
    if not wanted:
        return False
    return bool(
        await page.evaluate(
            """({ elementId, wantedLabel }) => {
                const normalize = (txt) => String(txt || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/[^a-zA-Z0-9]+/g, " ")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();
                const tokenSet = (txt) =>
                    new Set(
                        normalize(txt)
                            .split(" ")
                            .filter((t) => t.length >= 3)
                    );
                const el = document.getElementById(elementId);
                if (!el || !el.options) return false;
                const wanted = normalize(wantedLabel);
                const wantedTokens = tokenSet(wantedLabel);
                const options = Array.from(el.options);
                let opt = options.find((item) => normalize(item.textContent || "") === wanted);
                if (!opt) opt = options.find((item) => normalize(item.textContent || "").includes(wanted));
                if (!opt && wantedTokens.size > 0) {
                    opt = options.find((item) => {
                        const optTokens = tokenSet(item.textContent || "");
                        if (optTokens.size === 0) return false;
                        for (const token of wantedTokens) {
                            if (!optTokens.has(token)) return false;
                        }
                        return true;
                    });
                }
                if (!opt) return false;
                el.value = String(opt.value || "");
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
            }""",
            {"elementId": element_id, "wantedLabel": wanted},
        )
    )


async def _auto_select_single_nonempty_option(page: "Page | Frame", element_id: str) -> bool:
    await dismiss_cookie_banner_if_present(page)
    return bool(
        await page.evaluate(
            """({ elementId }) => {
                const normalize = (txt) => String(txt || "").trim();
                const el = document.getElementById(elementId);
                if (!el || !el.options) return false;
                const options = Array.from(el.options).filter((opt) => {
                    const value = normalize(opt.value || "");
                    const text = normalize(opt.textContent || "");
                    if (!value || !text) return false;
                    if (/seleccion/i.test(text)) return false;
                    return true;
                });
                if (options.length !== 1) return false;
                el.value = String(options[0].value || "");
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
            }""",
            {"elementId": element_id},
        )
    )


async def _selected_option_matches(page: "Page | Frame", element_id: str, label: str) -> bool:
    wanted = _clean(label)
    if not wanted:
        return False
    try:
        return bool(
            await page.evaluate(
                """({ elementId, wantedLabel }) => {
                    const normalize = (txt) => String(txt || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/[^a-zA-Z0-9]+/g, " ")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                    const tokenSet = (txt) =>
                        new Set(
                            normalize(txt)
                                .split(" ")
                                .filter((t) => t.length >= 3)
                        );
                    const el = document.getElementById(elementId);
                    if (!el || !el.options) return false;
                    const current = Array.from(el.options).find((opt) => opt.selected);
                    if (!current) return false;
                    const currentText = normalize(current.textContent || "");
                    const wanted = normalize(wantedLabel);
                    if (currentText === wanted) return true;
                    if (wanted.length >= 4 && currentText.includes(wanted)) return true;
                    const currentTokens = tokenSet(current.textContent || "");
                    const wantedTokens = tokenSet(wantedLabel);
                    if (wantedTokens.size === 0 || currentTokens.size === 0) return false;
                    for (const token of wantedTokens) {
                        if (!currentTokens.has(token)) return false;
                    }
                    return true;
                }""",
                {"elementId": element_id, "wantedLabel": wanted},
            )
        )
    except Exception:
        return False


async def _retry_select_via_id(
    page: "Page | Frame",
    element_id: str,
    label: str,
    *,
    attempts: int = 3,
    wait_ms: int = 900,
) -> bool:
    wanted = _clean(label)
    if not wanted:
        return False
    for attempt in range(1, max(1, attempts) + 1):
        await _wait_select_options(page, element_id, timeout_ms=max(3000, wait_ms * 4))
        ok = await _safe_select_via_id(page, element_id, wanted)
        if ok:
            await page.wait_for_timeout(350)
            if await _selected_option_matches(page, element_id, wanted):
                return True
        if attempt < attempts:
            await page.wait_for_timeout(wait_ms)
    return await _selected_option_matches(page, element_id, wanted)


async def _stabilize_identificado_cascade(
    page: "Page | Frame",
    *,
    provincia_id: str,
    comarca_id: str,
    municipio_id: str,
    datos: "ServeiCatTransTarget",
) -> tuple[bool, bool, bool]:
    ok_provincia = True
    if _clean(datos.identificado_provincia):
        await _wait_select_options(page, provincia_id, timeout_ms=6000)
        ok_provincia = await _retry_select_via_id(page, provincia_id, datos.identificado_provincia, attempts=4, wait_ms=1100)
        if not ok_provincia:
            ok_provincia = await _auto_select_single_nonempty_option(page, provincia_id)
    await page.wait_for_timeout(1400)
    await _log_select_state(page, provincia_id, "identificado-provincia-stabilized")

    ok_comarca = True
    if _clean(datos.identificado_comarca):
        await _wait_select_options(page, comarca_id, timeout_ms=9000)
        ok_comarca = await _retry_select_via_id(page, comarca_id, datos.identificado_comarca, attempts=4, wait_ms=1200)
        if not ok_comarca:
            ok_comarca = await _auto_select_single_nonempty_option(page, comarca_id)
        await page.wait_for_timeout(1400)
        await _log_select_state(page, comarca_id, "identificado-comarca-stabilized")

    ok_municipio = True
    if _clean(datos.identificado_municipio):
        await _wait_select_options(page, municipio_id, timeout_ms=12000)
        ok_municipio = await _retry_select_via_id(page, municipio_id, datos.identificado_municipio, attempts=4, wait_ms=1400)
        if not ok_municipio and _clean(datos.identificado_comarca):
            await _retry_select_via_id(page, comarca_id, datos.identificado_comarca, attempts=2, wait_ms=900)
            await page.wait_for_timeout(1600)
            ok_municipio = await _retry_select_via_id(page, municipio_id, datos.identificado_municipio, attempts=3, wait_ms=1400)
        if not ok_municipio:
            ok_municipio = await _auto_select_single_nonempty_option(page, municipio_id)
        await _log_select_state(page, municipio_id, "identificado-municipio-stabilized")

    return ok_provincia, ok_comarca, ok_municipio


async def _fill_exact_input(page: "Page | Frame", selector: str, value: str) -> bool:
    await dismiss_cookie_banner_if_present(page)
    text = _clean(value)
    if not text:
        return False

    locator = page.locator(selector).first
    if await locator.count() <= 0:
        return False

    try:
        await locator.wait_for(state="visible", timeout=10000)
    except Exception:
        return False

    try:
        await locator.click(timeout=FAST_ACTION_TIMEOUT_MS)
    except Exception:
        pass

    # Prioridad al comportamiento real del smoke: foco + fill nativo + verificacion.
    try:
        await locator.fill(text, timeout=5000)
        current = _clean(await locator.input_value())
        if current == text:
            return True
    except Exception:
        pass

    # Si fill no persiste, forzar seleccion total + tecleo real conservando el foco.
    try:
        await locator.press("Control+A", timeout=FAST_ACTION_TIMEOUT_MS)
    except Exception:
        pass
    try:
        await locator.press("Meta+A", timeout=FAST_ACTION_TIMEOUT_MS)
    except Exception:
        pass
    try:
        await locator.type(text, delay=40, timeout=5000)
        current = _clean(await locator.input_value())
        if current == text:
            return True
    except Exception:
        pass

    # Ultimo recurso: set por JS + foco explicito + eventos, y verificar.
    try:
        await locator.evaluate(
            """(el, val) => {
                el.focus();
                el.value = "";
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                el.value = String(val || "");
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                el.focus();
            }""",
            text,
        )
        current = _clean(await locator.input_value())
        return current == text
    except Exception:
        return False


async def _log_input_state(page: "Page | Frame", selector: str, label: str) -> None:
    try:
        state = await page.locator(selector).first.evaluate(
            """(el) => ({
                id: el.id || "",
                name: el.getAttribute("name") || "",
                value: el.value || "",
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                disabled: !!el.disabled,
                readonly: !!el.readOnly || el.hasAttribute("readonly") || el.getAttribute("aria-readonly") === "true",
                ariaLabel: el.getAttribute("aria-label") || "",
                className: el.className || "",
            })"""
        )
        logger.info("servei_cat_trans field-state %s selector=%s state=%s", label, selector, state)
    except Exception as exc:
        logger.warning("servei_cat_trans field-state %s selector=%s error=%s", label, selector, exc)


async def _log_select_state(page: "Page | Frame", element_id: str, label: str) -> None:
    try:
        state = await page.evaluate(
            """({ elementId }) => {
                const el = document.getElementById(elementId);
                if (!el) return { exists: false };
                const options = Array.from(el.options || []).map((o) => ({
                    value: String(o.value || ""),
                    text: String(o.textContent || "").trim(),
                    selected: !!o.selected,
                }));
                return {
                    exists: true,
                    disabled: !!el.disabled,
                    value: String(el.value || ""),
                    selectedText: (options.find((o) => o.selected) || {}).text || "",
                    optionsCount: options.length,
                    firstOptions: options.slice(0, 10),
                };
            }""",
            {"elementId": element_id},
        )
        logger.info("servei_cat_trans select-state %s element_id=%s state=%s", label, element_id, state)
    except Exception as exc:
        logger.warning("servei_cat_trans select-state %s element_id=%s error=%s", label, element_id, exc)


async def _wait_select_options(
    page: "Page | Frame",
    element_id: str,
    *,
    timeout_ms: int = CASCADE_OPTIONS_TIMEOUT_MS,
    min_options: int = 2,
) -> None:
    waited = 0
    step = 300
    while waited <= timeout_ms:
        try:
            state = await page.evaluate(
                """({ elementId }) => {
                    const el = document.getElementById(elementId);
                    if (!el) return { exists: false, enabled: false, optionsCount: 0 };
                    const enabled = !el.disabled;
                    const optionsCount = Array.isArray(Array.from(el.options)) ? el.options.length : 0;
                    return { exists: true, enabled, optionsCount };
                }""",
                {"elementId": element_id},
            )
        except Exception:
            state = {"exists": False, "enabled": False, "optionsCount": 0}

        exists = bool(state.get("exists"))
        enabled = bool(state.get("enabled"))
        options_count = int(state.get("optionsCount") or 0)
        if exists and enabled and options_count >= min_options:
            return

        await page.wait_for_timeout(step)
        waited += step

    logger.warning(
        "Timeout esperando opciones en select #%s (%sms). Continuando con fallback.",
        element_id,
        timeout_ms,
    )


async def _fill_cp_comarca_municipio_smoke(
    page: "Page | Frame",
    cp_panel_id: str,
    codigo_postal: str,
    comarca: str,
    municipio: str,
) -> tuple[bool, bool, bool]:
    cp_selector = f"#{cp_panel_id}-guidetextbox___widget"
    logger.info(
        "servei_cat_trans representado-cascade start cp_panel_id=%s cp=%r comarca=%r municipio=%r",
        cp_panel_id,
        _clean(codigo_postal),
        _clean(comarca),
        _clean(municipio),
    )
    await _log_input_state(page, cp_selector, "representado-cp-before")
    ok_cp = await _fill_exact_input(page, cp_selector, codigo_postal)
    if ok_cp:
        try:
            current_cp = _clean(await page.locator(cp_selector).first.input_value())
        except Exception:
            current_cp = ""
        logger.info(
            "servei_cat_trans representado-cp selector=%s expected=%s actual=%s",
            cp_selector,
            _clean(codigo_postal),
            current_cp,
        )
    else:
        logger.warning(
            "servei_cat_trans representado-cp fill failed selector=%s expected=%s",
            cp_selector,
            _clean(codigo_postal),
        )
    await _log_input_state(page, cp_selector, "representado-cp-after-fill")
    if ok_cp and _clean(codigo_postal):
        try:
            await page.locator(cp_selector).first.press("Tab", timeout=5000)
        except Exception:
            try:
                await page.locator(cp_selector).first.focus()
                await page.keyboard.press("Tab")
            except Exception:
                pass
        await page.wait_for_timeout(1000)
    await _log_input_state(page, cp_selector, "representado-cp-after-tab")
    await _log_select_state(page, f"{cp_panel_id}-guidedropdownlist___widget", "representado-provincia-after-tab")

    comarca_id = f"{cp_panel_id}-guidedropdownlist_2056216251___widget"
    ok_comarca = True
    if _clean(comarca):
        await page.wait_for_timeout(800)
        await _wait_select_options(page, comarca_id)
        ok_comarca = await _retry_select_via_id(page, comarca_id, comarca)
        if not ok_comarca:
            ok_comarca = await _auto_select_single_nonempty_option(page, comarca_id)
        logger.info(
            "servei_cat_trans representado-comarca result element_id=%s wanted=%r ok=%s",
            comarca_id,
            _clean(comarca),
            ok_comarca,
        )
        await _log_select_state(page, comarca_id, "representado-comarca-after-select")
        await page.wait_for_timeout(900)

    municipio_id = f"{cp_panel_id}-guidedropdownlist_988023112___widget"
    ok_municipio = True
    if _clean(municipio):
        await page.wait_for_timeout(800)
        await _wait_select_options(page, municipio_id)
        ok_municipio = await _retry_select_via_id(page, municipio_id, municipio)
        if not ok_municipio:
            ok_municipio = await _auto_select_single_nonempty_option(page, municipio_id)
        logger.info(
            "servei_cat_trans representado-municipio result element_id=%s wanted=%r ok=%s",
            municipio_id,
            _clean(municipio),
            ok_municipio,
        )
        await _log_select_state(page, municipio_id, "representado-municipio-after-select")

    logger.info(
        "servei_cat_trans representado-cascade end cp_ok=%s comarca_ok=%s municipio_ok=%s",
        ok_cp,
        ok_comarca,
        ok_municipio,
    )

    return ok_cp, ok_comarca, ok_municipio


async def _fill_representado_direccion_fallback(
    page: "Page | Frame",
    datos: "ServeiCatTransTarget",
    *,
    preferred_panel_id: str = "",
    preferred_cp_panel_id: str = "",
) -> None:
    # Fallback seguro: solo IDs de bloques de direccion (nunca etiquetas genericas),
    # para evitar tocar por error campos de documento (DNI/NIE).
    panel_candidates: list[tuple[str, str]] = []
    if _clean(preferred_panel_id) and _clean(preferred_cp_panel_id):
        panel_candidates.append((_clean(preferred_panel_id), _clean(preferred_cp_panel_id)))
    panel_candidates.extend(
        [
            (
                "guideContainer-rootPanel-seccio_solicitant-personaFisica-PF-adreca-panel_298747259",
                "guideContainer-rootPanel-seccio_solicitant-personaFisica-PF-adreca-panel_1697806457",
            ),
            (
                "guideContainer-rootPanel-seccio_solicitant-personaFisica-adreca-panel_298747259",
                "guideContainer-rootPanel-seccio_solicitant-personaFisica-adreca-panel_1697806457",
            ),
            (
                "guideContainer-rootPanel-seccio_solicitant-personaJuridica-adreca-panel_298747259",
                "guideContainer-rootPanel-seccio_solicitant-personaJuridica-adreca-panel_1697806457",
            ),
        ]
    )

    seen: set[tuple[str, str]] = set()
    for panel_id, cp_panel_id in panel_candidates:
        key = (panel_id, cp_panel_id)
        if key in seen:
            continue
        seen.add(key)

        has_any = False
        cp_visible = False
        try:
            via_locator = page.locator(f"#{panel_id}-guidetextbox___widget")
            cp_locator = page.locator(f"#{cp_panel_id}-guidetextbox___widget")
            has_any = (await via_locator.count() > 0) or (await cp_locator.count() > 0)
            if await cp_locator.count() > 0:
                cp_visible = bool(await cp_locator.first.is_visible())
        except Exception:
            has_any = False
            cp_visible = False

        if not has_any or not cp_visible:
            logger.info(
                "servei_cat_trans representado fallback panel skipped panel_id=%s cp_panel_id=%s has_any=%s cp_visible=%s",
                panel_id,
                cp_panel_id,
                has_any,
                cp_visible,
            )
            continue

        logger.warning(
            "servei_cat_trans representado fallback panel selected panel_id=%s cp_panel_id=%s",
            panel_id,
            cp_panel_id,
        )

        await _safe_select_tipo_via(
            page,
            selector=f"#{panel_id}-guidedropdownlist___widget",
            raw_tipo_via=datos.representado_tipo_via,
            raw_street=datos.representado_nombre_via,
        )
        await _safe_fill(page, f"#{panel_id}-guidetextbox___widget", datos.representado_nombre_via)
        await _safe_fill(page, f"#{panel_id}-panel-guidetextbox___widget", datos.representado_numero)
        await _fill_cp_comarca_municipio_smoke(
            page,
            cp_panel_id,
            datos.representado_cp,
            datos.representado_comarca,
            datos.representado_municipio,
        )
        return

    logger.warning("Fallback direccion representado: no se localizaron paneles de direccion esperados.")


async def _find_field_id_by_label(
    page: "Page | Frame",
    section_selector: str,
    label_tokens: list[str],
    *,
    field_kind: str = "input",
) -> str:
    result = await page.evaluate(
        """({ sectionSelector, tokens, kind }) => {
            const normalize = (txt) => String(txt || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();
            const section = document.querySelector(sectionSelector) || document;
            const wanted = (tokens || []).map((t) => normalize(t)).filter(Boolean);
            const matchesToken = (txt) => {
                const n = normalize(txt);
                return wanted.some((w) => n.includes(w));
            };
            const selectorByKind = kind === "select" ? "select" : "input, textarea";
            
            // 1. Check for labels with 'for' or wrapping the input
            const labels = Array.from(section.querySelectorAll("label"));
            for (const lbl of labels) {
                if (!matchesToken(lbl.textContent || "")) continue;
                const forId = String(lbl.getAttribute("for") || "").trim();
                if (forId) {
                    const byFor = section.querySelector("#" + CSS.escape(forId));
                    if (byFor && byFor.matches(selectorByKind) && byFor.id) return String(byFor.id);
                }
                let container = lbl.closest("div");
                for (let i = 0; i < 6 && container; i++) {
                    const candidate = container.querySelector(selectorByKind);
                    if (candidate && candidate.id) return String(candidate.id);
                    container = container.parentElement;
                }
            }
            
            // 2. Check for aria-label or placeholder on the inputs themselves
            const inputs = Array.from(section.querySelectorAll(selectorByKind));
            for (const el of inputs) {
                const aria = el.getAttribute("aria-label") || "";
                const ph = el.getAttribute("placeholder") || "";
                const title = el.getAttribute("title") || "";
                if (matchesToken(aria) || matchesToken(ph) || matchesToken(title)) {
                    if (el.id) return String(el.id);
                }
            }
            return "";
        }""",
        {"sectionSelector": section_selector, "tokens": label_tokens, "kind": field_kind},
    )
    return str(result or "").strip()


async def _find_identificado_section_selector(page: "Page | Frame") -> str:
    result = await page.evaluate(
        """() => {
            const normalize = (txt) => String(txt || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();

            const targetTokens = [
                "datos de identificacion del conductor",
                "datos de identificacion del conductor / de la conductora",
                "dades d identificacio del conductor",
                "dades d identificacio del conductor / de la conductora",
            ];
            const hasInputs = (el) => (el?.querySelectorAll?.("input, select, textarea") || []).length >= 6;
            const all = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,legend,label,div,span,p"));

            for (const el of all) {
                const txt = normalize(el.textContent || "");
                if (!targetTokens.some((token) => txt.includes(token))) continue;

                let scope = el;
                for (let i = 0; i < 8 && scope; i++) {
                    if (hasInputs(scope)) {
                        if (scope.id) return "#" + CSS.escape(scope.id);
                        scope.setAttribute("data-xaloc-identificado-scope", "1");
                        return "[data-xaloc-identificado-scope='1']";
                    }
                    scope = scope.parentElement;
                }
            }
            return "";
        }"""
    )
    return str(result or "").strip()


async def _wait_expediente_verificado(
    page: "Page | Frame",
    *,
    tramite_tipo: str,
    timeout_ms: int = 15000,
) -> None:
    waited = 0
    step_ms = 500
    tramite = _clean(tramite_tipo).lower()
    identified_heading = re.compile(
        r"datos de identificacion del conductor|dades d identificacio del conductor",
        re.IGNORECASE,
    )
    pending_warning = re.compile(
        r"(confirmar|confirma).*(datos|dades).*(expedient|expediente)|"
        r"(datos|dades).*(expedient|expediente).*(correct|correctes|correctos)",
        re.IGNORECASE,
    )

    while waited <= timeout_ms:
        try:
            ok_text = page.get_by_text(
                re.compile(
                    r"los datos del expediente son correctos|dades de l'expedient.*correct",
                    re.IGNORECASE,
                )
            ).first
            if await ok_text.count() > 0:
                try:
                    await ok_text.wait_for(state="visible", timeout=500)
                    return
                except Exception:
                    pass
        except Exception:
            pass

        if tramite == "identificacion":
            try:
                conductor_heading = page.get_by_text(identified_heading).first
                if await conductor_heading.count() > 0:
                    try:
                        await conductor_heading.wait_for(state="visible", timeout=500)
                        warning_visible = False
                        try:
                            warning = page.get_by_text(pending_warning).first
                            if await warning.count() > 0:
                                warning_visible = await warning.is_visible()
                        except Exception:
                            warning_visible = False
                        if not warning_visible:
                            return
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                identificado_section = await _find_identificado_section_selector(page)
                if identificado_section:
                    section = page.locator(identificado_section).first
                    if await section.count() > 0 and await section.is_visible():
                        warning_visible = False
                        try:
                            warning = page.get_by_text(pending_warning).first
                            if await warning.count() > 0:
                                warning_visible = await warning.is_visible()
                        except Exception:
                            warning_visible = False
                        if not warning_visible:
                            return
            except Exception:
                pass

        await page.wait_for_timeout(step_ms)
        waited += step_ms

    raise PlaywrightTimeoutError(
        f"Timeout esperando validacion de expediente SCT (tramite={tramite or 'normal'})"
    )


async def _fill_input_by_label_in_section(
    page: "Page | Frame",
    section_selector: str,
    label_tokens: list[str],
    value: str,
) -> bool:
    if not _clean(section_selector):
        return False
    field_id = await _find_field_id_by_label(page, section_selector, label_tokens, field_kind="input")
    if not field_id:
        return False
    return await _fill_exact_input(page, f"#{field_id}", value)


async def _select_label_in_section(
    page: "Page | Frame",
    section_selector: str,
    label_tokens: list[str],
    value: str,
) -> bool:
    if not _clean(section_selector):
        return False
    field_id = await _find_field_id_by_label(page, section_selector, label_tokens, field_kind="select")
    if not field_id:
        return False
    return await _safe_select_label(page, f"#{field_id}", value)


async def _fill_identificado_pais_emisor(
    page: "Page | Frame",
    section_selector: str,
    pais_emisor: str,
) -> bool:
    candidates = _pais_emisor_candidates(pais_emisor)
    if not candidates:
        return False

    for attempt in range(8):
        for candidate in candidates:
            ok = await _select_label_in_section(
                page,
                section_selector,
                ["pais emisor", "pais expedidor", "pais d expedicio", "pais"],
                candidate,
            )
            if ok:
                logger.info(
                    "servei_cat_trans identificado pais emisor seleccionado candidate=%r attempt=%s",
                    candidate,
                    attempt + 1,
                )
                return True
        await page.wait_for_timeout(500)

    logger.warning(
        "servei_cat_trans identificado pais emisor no seleccionado pais=%r candidates=%s",
        _clean(pais_emisor),
        candidates,
    )
    return False


async def _fill_presentador_contacto_fallback(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    section = "[id^='guideContainer-rootPanel-seccio_presentador']"
    email_id = await _find_field_id_by_label(
        page,
        section,
        ["correo electronico", "correu electronic", "adreca electronica", "email"],
        field_kind="input",
    )
    if email_id:
        await _safe_fill(page, f"#{email_id}", datos.email)

    tel_id = await _find_field_id_by_label(
        page,
        section,
        ["telefono movil", "telefon mobil", "movil", "mobil", "telefono"],
        field_kind="input",
    )
    if tel_id:
        await _safe_fill(page, f"#{tel_id}", datos.telefono_movil)


async def _fill_presentador_direccion_fallback(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    section = "[id^='guideContainer-rootPanel-seccio_presentador']"
    tipo_via_id = await _find_field_id_by_label(
        page,
        section,
        ["tipo de via", "tipus de via", "via"],
        field_kind="select",
    )
    if tipo_via_id:
        await _safe_select_label(page, f"#{tipo_via_id}", datos.direccion_tipo_via)

    nombre_via_id = await _find_field_id_by_label(
        page,
        section,
        ["nombre de la via", "nom de la via", "via i numero", "adreca"],
        field_kind="input",
    )
    if nombre_via_id:
        await _safe_fill(page, f"#{nombre_via_id}", datos.direccion_nombre_via)

    numero_id = await _find_field_id_by_label(
        page,
        section,
        ["numero", "num."],
        field_kind="input",
    )
    if numero_id:
        await _safe_fill(page, f"#{numero_id}", datos.direccion_numero)

    cp_id = await _find_field_id_by_label(
        page,
        section,
        ["codigo postal", "codi postal", "cp"],
        field_kind="input",
    )
    if cp_id:
        await _safe_fill(page, f"#{cp_id}", datos.direccion_cp)

    provincia_id = await _find_field_id_by_label(page, section, ["provincia"], field_kind="select")
    if provincia_id:
        await _safe_select_label(page, f"#{provincia_id}", datos.direccion_provincia or "BARCELONA")
        await page.wait_for_timeout(2000)

    comarca_id = await _find_field_id_by_label(
        page,
        section,
        ["comarca"],
        field_kind="select",
    )
    if comarca_id:
        await _safe_select_label(page, f"#{comarca_id}", datos.direccion_comarca)

    municipio_id = await _find_field_id_by_label(
        page,
        section,
        ["municipio"],
        field_kind="select",
    )
    if municipio_id:
        await _safe_select_label(page, f"#{municipio_id}", datos.direccion_municipio)


async def _fill_direccion(page: "Page | Frame", panel_id: str, cp_panel_id: str, datos: "ServeiCatTransTarget") -> None:
    # Los panel_id de adreca son ESTABLES, usar selectores exactos con #id
    await _safe_select_label(page, f"#{panel_id}-guidedropdownlist___widget", datos.direccion_tipo_via)
    await _safe_fill(page, f"#{panel_id}-guidetextbox___widget", datos.direccion_nombre_via)
    await _safe_fill(page, f"#{panel_id}-panel-guidetextbox___widget", datos.direccion_numero)
    await _safe_fill(page, f"#{cp_panel_id}-guidetextbox___widget", datos.direccion_cp)

    # --- CASCADA: Provincia -> (espera) -> Comarca -> (espera) -> Municipio ---
    # 1. Seleccionar Provincia (ID estable: {cp_panel_id}-guidedropdownlist___widget)
    await _safe_select_via_id(
        page,
        f"{cp_panel_id}-guidedropdownlist___widget",
        datos.direccion_provincia or "Barcelona",
    )
    await page.wait_for_timeout(900)
    # 2. Esperar a que Comarca cargue opciones (dependiente de Provincia)
    comarca_id = f"{cp_panel_id}-guidedropdownlist_2056216251___widget"
    await _wait_select_options(page, comarca_id)
    ok_comarca = await _retry_select_via_id(
        page,
        comarca_id,
        datos.direccion_comarca,
    )
    if not ok_comarca:
        ok_comarca = await _auto_select_single_nonempty_option(page, comarca_id)
    if datos.direccion_comarca and not ok_comarca:
        raise RuntimeError(
            f"servei_cat_trans.formulario: no se pudo seleccionar comarca '{datos.direccion_comarca}' en presentador."
        )

    # 3. Esperar a que Municipio cargue opciones (dependiente de Comarca)
    municipio_id = f"{cp_panel_id}-guidedropdownlist_988023112___widget"
    await page.wait_for_timeout(900)
    await _wait_select_options(page, municipio_id)
    ok_municipio = await _retry_select_via_id(
        page,
        municipio_id,
        datos.direccion_municipio,
    )
    if not ok_municipio:
        ok_municipio = await _auto_select_single_nonempty_option(page, municipio_id)
    if datos.direccion_municipio and not ok_municipio:
        raise RuntimeError(
            f"servei_cat_trans.formulario: no se pudo seleccionar municipio '{datos.direccion_municipio}' en presentador."
        )


async def _fill_representado_direccion(page: "Page | Frame", panel_id: str, cp_panel_id: str, datos: "ServeiCatTransTarget") -> None:
    # Logica smoke exacta para representado:
    # tipo via -> calle -> numero -> CP -> Tab -> espera -> comarca -> espera -> municipio.
    logger.info(
        "servei_cat_trans representado-direccion start panel_id=%s cp_panel_id=%s via=%r calle=%r numero=%r cp=%r provincia=%r comarca=%r municipio=%r",
        panel_id,
        cp_panel_id,
        datos.representado_tipo_via,
        datos.representado_nombre_via,
        datos.representado_numero,
        datos.representado_cp,
        datos.representado_provincia,
        datos.representado_comarca,
        datos.representado_municipio,
    )
    await _log_input_state(page, f"#{panel_id}-guidetextbox___widget", "representado-calle-before")
    await _log_input_state(page, f"#{panel_id}-panel-guidetextbox___widget", "representado-numero-before")
    ok_tipo = await _safe_select_tipo_via(
        page,
        selector=f"#{panel_id}-guidedropdownlist___widget",
        raw_tipo_via=datos.representado_tipo_via,
        raw_street=datos.representado_nombre_via,
    )
    ok_calle = await _fill_exact_input(page, f"#{panel_id}-guidetextbox___widget", datos.representado_nombre_via)
    ok_num = await _fill_exact_input(page, f"#{panel_id}-panel-guidetextbox___widget", datos.representado_numero)
    await _log_input_state(page, f"#{panel_id}-guidetextbox___widget", "representado-calle-after")
    await _log_input_state(page, f"#{panel_id}-panel-guidetextbox___widget", "representado-numero-after")
    ok_cp, ok_comarca, ok_municipio = await _fill_cp_comarca_municipio_smoke(
        page,
        cp_panel_id,
        datos.representado_cp,
        datos.representado_comarca,
        datos.representado_municipio,
    )

    if not (ok_tipo and ok_calle and ok_num and ok_cp and ok_comarca and ok_municipio):
        logger.warning(
            "Representado direccion incompleta por IDs (via=%s calle=%s num=%s cp=%s comarca=%s municipio=%s). Fallback seguro por IDs.",
            ok_tipo,
            ok_calle,
            ok_num,
            ok_cp,
            ok_comarca,
            ok_municipio,
        )
        await _fill_representado_direccion_fallback(
            page,
            datos,
            preferred_panel_id=panel_id,
            preferred_cp_panel_id=cp_panel_id,
        )


async def _safe_fill_phone_by_label(
    page: "Page | Frame",
    *,
    section_selector: str,
    fallback_selector: str,
    phone: str,
) -> None:
    phone_value = _sanitize_phone(phone)
    if not phone_value:
        logger.warning("servei_cat_trans telefono vacio tras sanitizacion; no se rellena campo.")
        return

    if await _fill_phone_input(page, fallback_selector, phone_value):
        return
    tel_id = await _find_field_id_by_label(
        page,
        section_selector,
        ["telefono movil", "telefon mobil", "movil", "mobil", "telefono"],
        field_kind="input",
    )
    if tel_id:
        if await _fill_phone_input(page, f"#{tel_id}", phone_value):
            logger.info("servei_cat_trans telefono rellenado por label en #%s", tel_id)
            return

    # Ultimo fallback: buscar input visible de telefono en la seccion.
    generic_phone_id = await page.evaluate(
        """({ sectionSelector }) => {
            const section = document.querySelector(sectionSelector) || document;
            const normalize = (txt) => String(txt || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .toLowerCase();
            const candidates = Array.from(section.querySelectorAll("input"));
            for (const el of candidates) {
                const aria = normalize(el.getAttribute("aria-label") || "");
                const type = normalize(el.getAttribute("type") || "");
                const inputmode = normalize(el.getAttribute("inputmode") || "");
                if (aria.includes("telefon") || aria.includes("telefono") || type === "tel" || inputmode === "tel") {
                    if (el.id && !el.disabled && !el.readOnly) return el.id;
                }
            }
            return "";
        }""",
        {"sectionSelector": section_selector},
    )
    generic_phone_id = str(generic_phone_id or "").strip()
    if generic_phone_id:
        ok = await _fill_phone_input(page, f"#{generic_phone_id}", phone_value)
        logger.info(
            "servei_cat_trans telefono fallback generico id=%s ok=%s value=%s",
            generic_phone_id,
            ok,
            phone_value,
        )
    else:
        logger.warning("servei_cat_trans no se encontro input de telefono en seccion=%s", section_selector)


async def _fill_presentador_contacto(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    prefix = "guideContainer-rootPanel-seccio_presentador-personaJuridica-PJ"
    
    # Prioridad absoluta a aria-label exacta para evitar confusiones con otros campos similares
    await _safe_fill_phone_by_label(
        page,
        section_selector="[id^='guideContainer-rootPanel-seccio_presentador']",
        fallback_selector=f"input[id^='{prefix}'][aria-label='TelÃ©fono mÃ³vil'], input[id^='{prefix}'][aria-label='TelÃ¨fon mÃ²bil']",
        phone=datos.telefono_movil,
    )

    if not await _safe_fill(page, f"input[id^='{prefix}'][aria-label='Correo electrÃ³nico'], input[id^='{prefix}'][aria-label='AdreÃ§a electrÃ²nica'], input[id^='{prefix}'][aria-label='Correu electrÃ²nic']", datos.email):
         await _safe_fill(page, f"input[id^='{prefix}-panel_'][id$='-guidetextbox_31092572___widget']", datos.email)

    await _fill_direccion(
        page,
        panel_id="guideContainer-rootPanel-seccio_presentador-personaJuridica-adreca-panel_298747259",
        cp_panel_id="guideContainer-rootPanel-seccio_presentador-personaJuridica-adreca-panel_1697806457",
        datos=datos,
    )
    await _fill_presentador_contacto_fallback(page, datos)
    await _fill_presentador_direccion_fallback(page, datos)


async def _fill_solicitante_fisica(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    base = "guideContainer-rootPanel-seccio_solicitant-personaFisica-PF"
    prefix = f"{base}-panel_"

    await _safe_fill(page, f"#{base}-panel-guidetextbox_897852897___widget", datos.nombre)
    await _safe_fill(page, f"#{base}-panel-guidetextbox_1197861190___widget", datos.apellido1)
    await _safe_fill(page, f"#{base}-panel-guidetextbox___widget", datos.apellido2)
    await _safe_select_label(page, f"#{base}-panel_1244233668-guidedropdownlist___widget", _documento_persona_label(datos.nif))
    await _safe_fill(page, f"#{base}-panel_1244233668-guidetextbox___widget", _sanitize_doc(datos.nif))

    # Email y Movil (panel_XXXXX dinamico, usar aria-label)
    prefix = f"{base}-panel_"
    if not await _safe_fill(page, f"input[id^='{prefix}'][aria-label='Correo electr\u00f3nico'], input[id^='{prefix}'][aria-label='Adre\u00e7a electr\u00f2nica'], input[id^='{prefix}'][aria-label='Correu electr\u00f2nic']", datos.email):
        await _safe_fill(page, f"input[id^='{prefix}'][id$='-guidetextbox_31092572___widget']", datos.email)

    await _safe_fill_phone_by_label(
        page,
        section_selector="[id^='guideContainer-rootPanel-seccio_solicitant-personaFisica']",
        fallback_selector=f"input[id^='{prefix}'][aria-label='TelÃ©fono mÃ³vil'], input[id^='{prefix}'][aria-label='TelÃ¨fon mÃ²bil']",
        phone=datos.telefono_movil,
    )

    # DirecciÃ³n del solicitante (persona fÃ­sica)
    # Probar con prefijo -PF (segun md) y sin Ã©l (por si acaso es como PJ)
    await page.wait_for_timeout(1000) # Esperar a que se despliegue
    panel_id = f"{base}-adreca-panel_298747259"
    cp_panel_id = f"{base}-adreca-panel_1697806457"
    
    # Verificar si el panel existe, si no, probar sin el sufijo -PF del base
    if await page.locator(f"#{panel_id}-guidetextbox___widget").count() == 0:
        base_short = base.replace("-PF", "")
        panel_id = f"{base_short}-adreca-panel_298747259"
        cp_panel_id = f"{base_short}-adreca-panel_1697806457"

    logger.info(
        "servei_cat_trans solicitante_fisica direccion panel chosen panel_id=%s cp_panel_id=%s",
        panel_id,
        cp_panel_id,
    )

    await _fill_representado_direccion(
        page,
        panel_id=panel_id,
        cp_panel_id=cp_panel_id,
        datos=datos,
    )



async def _fill_solicitante_juridica(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    pj = "guideContainer-rootPanel-seccio_solicitant-personaJuridica-PJ"

    # --- Datos de la empresa (panel raiz de PJ) ---
    await _safe_fill(page, f"#{pj}-panel-guidetextbox___widget", datos.razon_social)
    # Tipo doc empresa + NIF empresa  (panel_1552294135 es ESTABLE)
    await _safe_select_label(page, f"#{pj}-panel_1552294135-guidedropdownlist___widget", _documento_empresa_label(datos.nif_empresa))
    await _safe_fill(page, f"#{pj}-panel_1552294135-guidetextbox___widget", _sanitize_doc(datos.nif_empresa))

    # --- Datos del representante legal (panel_21004007 es ESTABLE) ---
    rep = f"{pj}-panel_21004007"
    await _safe_fill(page, f"#{rep}-guidetextbox_8978528___widget", datos.nombre)
    await _safe_fill(page, f"#{rep}-guidetextbox_1197861___widget", datos.apellido1)
    await _safe_fill(page, f"#{rep}-guidetextbox_1958877719___widget", datos.apellido2)
    # Tipo doc representante + NIF representante (sub-panel 'panel' dentro de panel_21004007)
    await _safe_select_label(page, f"#{pj}-panel_21004007-panel-guidedropdownlist___widget", _documento_persona_label(datos.nif))
    await _safe_fill(page, f"#{pj}-panel_21004007-panel-guidetextbox___widget", _sanitize_doc(datos.nif))

    # Email y Movil del representante (panel_XXXXX dinamico DENTRO de panel_21004007)
    # Prioridad aria-label exacta, fallback a prefijo panel_21004007
    rep_prefix = f"{rep}-panel_"
    await _safe_fill_phone_by_label(
        page,
        section_selector=f"#{rep}",
        fallback_selector=f"input[id^='{rep_prefix}'][aria-label='TelÃ©fono mÃ³vil'], input[id^='{rep_prefix}'][aria-label='TelÃ¨fon mÃ²bil']",
        phone=datos.telefono_movil,
    )

    if not await _safe_fill(page, f"input[id^='{rep_prefix}'][aria-label='Correo electrÃ³nico'], input[id^='{rep_prefix}'][aria-label='AdreÃ§a electrÃ²nica'], input[id^='{rep_prefix}'][aria-label='Correu electrÃ²nic']", datos.email):
        await _safe_fill(page, f"input[id^='{rep_prefix}'][id$='-guidetextbox_31092572___widget']", datos.email)

    # DirecciÃ³n del representante (de la persona jurÃ­dica solicitante)
    logger.info(
        "servei_cat_trans solicitante_juridica direccion panel chosen panel_id=%s cp_panel_id=%s",
        "guideContainer-rootPanel-seccio_solicitant-personaJuridica-adreca-panel_298747259",
        "guideContainer-rootPanel-seccio_solicitant-personaJuridica-adreca-panel_1697806457",
    )
    await _fill_representado_direccion(
        page,
        panel_id="guideContainer-rootPanel-seccio_solicitant-personaJuridica-adreca-panel_298747259",
        cp_panel_id="guideContainer-rootPanel-seccio_solicitant-personaJuridica-adreca-panel_1697806457",
        datos=datos,
    )


async def _fill_notificaciones(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    copy_btn = page.get_by_role("button", name=re.compile(r"de la persona solicitante", re.IGNORECASE)).first
    if await copy_btn.count() > 0:
        try:
            await copy_btn.click(timeout=FAST_ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(120)
        except Exception:
            pass

    await _fill_exact_input(
        page,
        "#guideContainer-rootPanel-seccio_declaracions-declaracionsText-guidetextbox_6143511_740763653___widget",
        datos.email,
    )
    phone_value = _sanitize_phone(datos.telefono_movil)
    ok_phone = await _fill_phone_input(
        page,
        (
            "input[id^='guideContainer-rootPanel-seccio_notificacions-notificacio-panel_']"
            "[id$='-guidetextbox_copy_17___widget']"
        ),
        phone_value,
    )
    if not ok_phone:
        ok_phone = await _fill_phone_input(
            page,
            (
                "input[id^='guideContainer-rootPanel-seccio_notificacions-notificacio-panel_']"
                "[aria-label='TelÃ©fono mÃ³vil'], "
                "input[id^='guideContainer-rootPanel-seccio_notificacions-notificacio-panel_']"
                "[aria-label='Teléfono móvil'], "
                "input[id^='guideContainer-rootPanel-seccio_notificacions-notificacio-panel_']"
                "[aria-label='TelÃ¨fon mÃ²bil'], "
                "input[id^='guideContainer-rootPanel-seccio_notificacions-notificacio-panel_']"
                "[aria-label='Telèfon mòbil']"
            ),
            phone_value,
        )
    if not ok_phone:
        tel_id = await _find_field_id_by_label(
            page,
            "[id^='guideContainer-rootPanel-seccio_notificacions']",
            ["telefono", "telefon", "movil", "mobil"],
            field_kind="input",
        )
        if tel_id:
            ok_phone = await _fill_phone_input(page, f"#{tel_id}", phone_value)
            logger.info("servei_cat_trans notificaciones telefono fallback id=%s ok=%s", tel_id, ok_phone)
    logger.info("servei_cat_trans notificaciones telefono final ok=%s value=%s", ok_phone, phone_value)


async def _fill_phone_input(page: "Page | Frame", selector: str, value: str) -> bool:
    phone = _sanitize_phone(value)
    if not phone:
        return False

    locator = page.locator(selector)
    count = await locator.count()
    if count <= 0:
        return False

    for idx in range(count):
        candidate = locator.nth(idx)
        try:
            if not await candidate.is_visible():
                continue
        except Exception:
            continue
        try:
            if await candidate.is_disabled():
                continue
        except Exception:
            pass

        async def _matches_now() -> bool:
            try:
                current = await candidate.input_value()
            except Exception:
                current = ""
            return _phone_matches(phone, current)

        try:
            await candidate.fill(phone, timeout=FAST_ACTION_TIMEOUT_MS)
            if await _matches_now():
                return True
        except Exception:
            pass

        try:
            await candidate.click(timeout=FAST_ACTION_TIMEOUT_MS)
        except Exception:
            pass
        for key in ("Control+A", "Meta+A"):
            try:
                await candidate.press(key, timeout=FAST_ACTION_TIMEOUT_MS)
            except Exception:
                pass
        try:
            await candidate.type(phone, delay=25, timeout=FAST_ACTION_TIMEOUT_MS)
            if await _matches_now():
                return True
        except Exception:
            pass

        try:
            await candidate.evaluate(
                """(el, val) => {
                    el.focus();
                    el.value = String(val || "");
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                    el.blur();
                }""",
                phone,
            )
            if await _matches_now():
                return True
        except Exception:
            pass

    return False


async def _fill_expediente(page: "Page | Frame", datos: "ServeiCatTransTarget", config: "ServeiCatTransConfig") -> None:
    base = "guideContainer-rootPanel-seccio_dadesParticulars"
    # Selectores robustos para datos del expediente
    await _safe_fill(page, f"div[id^='{base}'] [id$='-guidetextbox___widget']", datos.servicio_territorial)
    await _safe_fill(page, f"div[id^='{base}'] [id$='-guidetextbox_5569220___widget']", datos.expediente_numero)
    await _safe_fill(page, f"div[id^='{base}'] [id$='-guidetextbox_1768694___widget']", datos.digito_control)

    clicked = await _safe_click(page, "button:has-text('Comprobar datos expediente')")
    if not clicked:
        clicked = await _safe_click(page, "button:has-text('Comparar dades expedient')")
    if not clicked:
        fallback_btn = page.get_by_role("button", name=re.compile(r"comprobar|comprovar|comparar", re.IGNORECASE)).first
        if await fallback_btn.count() > 0:
            await fallback_btn.click(timeout=FAST_ACTION_TIMEOUT_MS)
            clicked = True
    if clicked:
        await _wait_expediente_verificado(page, tramite_tipo=_clean(datos.tramite_tipo))
        if _clean(datos.tramite_tipo).lower() == "identificacion":
            await _fill_identificacion_conductor(page, datos)


async def _fill_identificacion_conductor_direccion(
    page: "Page | Frame",
    *,
    section_selector: str,
    tipo_via_id: str,
    nombre_via_id: str,
    numero_id: str,
    cp_id: str,
    provincia_id: str,
    comarca_id: str,
    municipio_id: str,
    datos: "ServeiCatTransTarget",
) -> None:
    ok_tipo = await _safe_select_tipo_via(
        page,
        selector=f"#{tipo_via_id}",
        raw_tipo_via=datos.identificado_tipo_via,
        raw_street=datos.identificado_nombre_via,
    )
    ok_calle = await _fill_exact_input(page, f"#{nombre_via_id}", datos.identificado_nombre_via)
    ok_num = await _fill_exact_input(page, f"#{numero_id}", datos.identificado_numero)

    ok_provincia = True
    if _clean(datos.identificado_provincia):
        await _wait_select_options(page, provincia_id, timeout_ms=5000)
        ok_provincia = await _retry_select_via_id(page, provincia_id, datos.identificado_provincia)
        if not ok_provincia:
            ok_provincia = await _auto_select_single_nonempty_option(page, provincia_id)
    if not ok_provincia:
        ok_provincia = await _select_label_in_section(
            page,
            section_selector,
            ["provincia"],
            datos.identificado_provincia,
        )
    if ok_provincia and _clean(datos.identificado_provincia):
        await page.wait_for_timeout(1200)

    ok_cp = await _fill_exact_input(page, f"#{cp_id}", datos.identificado_cp)
    if not ok_cp:
        ok_cp = await _fill_input_by_label_in_section(
            page,
            section_selector,
            ["codigo postal", "codi postal"],
            datos.identificado_cp,
        )
    if ok_cp and _clean(datos.identificado_cp):
        try:
            await page.locator(f"#{cp_id}").first.press("Tab", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2200)
        await _log_input_state(page, f"#{cp_id}", "identificado-cp-after-tab")
        restabilized_prov, restabilized_comarca, restabilized_municipio = await _stabilize_identificado_cascade(
            page,
            provincia_id=provincia_id,
            comarca_id=comarca_id,
            municipio_id=municipio_id,
            datos=datos,
        )
        ok_provincia = ok_provincia and restabilized_prov
    else:
        restabilized_comarca = True
        restabilized_municipio = True

    ok_comarca = True
    if _clean(datos.identificado_comarca):
        await page.wait_for_timeout(1000)
        await _wait_select_options(page, comarca_id)
        ok_comarca = await _retry_select_via_id(page, comarca_id, datos.identificado_comarca)
        if not ok_comarca:
            ok_comarca = await _auto_select_single_nonempty_option(page, comarca_id)
        if not ok_comarca:
            ok_comarca = await _select_label_in_section(
                page,
                section_selector,
                ["comarca"],
                datos.identificado_comarca,
            )
        await page.wait_for_timeout(1000)
        ok_comarca = ok_comarca or restabilized_comarca

    ok_municipio = True
    if _clean(datos.identificado_municipio):
        await page.wait_for_timeout(1000)
        await _wait_select_options(page, municipio_id)
        ok_municipio = await _retry_select_via_id(page, municipio_id, datos.identificado_municipio)
        if not ok_municipio:
            ok_municipio = await _auto_select_single_nonempty_option(page, municipio_id)
        if not ok_municipio:
            ok_municipio = await _select_label_in_section(
                page,
                section_selector,
                ["municipio", "municipi"],
                datos.identificado_municipio,
            )
        ok_municipio = ok_municipio or restabilized_municipio

    if not ok_tipo:
        ok_tipo = await _select_label_in_section(
            page,
            section_selector,
            ["tipo de via", "tipus de via"],
            _tipo_via_candidates(datos.identificado_tipo_via, datos.identificado_nombre_via)[0],
        )
    if not ok_calle:
        ok_calle = await _fill_input_by_label_in_section(
            page,
            section_selector,
            ["nombre de la via", "nom de la via"],
            datos.identificado_nombre_via,
        )
    if not ok_num:
        ok_num = await _fill_input_by_label_in_section(
            page,
            section_selector,
            ["numero"],
            datos.identificado_numero,
        )

    if not (ok_tipo and ok_calle and ok_num and ok_cp and ok_provincia and ok_comarca and ok_municipio):
        logger.warning(
            "Identificado direccion parcial via=%s calle=%s num=%s cp=%s provincia=%s comarca=%s municipio=%s",
            ok_tipo,
            ok_calle,
            ok_num,
            ok_cp,
            ok_provincia,
            ok_comarca,
            ok_municipio,
        )


async def _select_identificado_tipo_persona(page: "Page | Frame", *, is_juridica: bool) -> None:
    input_id = (
        "guideContainer-rootPanel-seccio_dadesParticulars-panel-panel1662017961273-guideradiobutton__-2_widget"
        if is_juridica
        else "guideContainer-rootPanel-seccio_dadesParticulars-panel-panel1662017961273-guideradiobutton__-1_widget"
    )
    panel_wait_selector = (
        "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica___guide-item"
        if is_juridica
        else "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica___guide-item"
    )
    label_text = "Persona jurídica" if is_juridica else "Persona física"

    ok = await _safe_check(page, f"#{input_id}")
    if not ok:
        await _safe_click(
            page,
            f"div.guideRadioButtonItem:has(input#{input_id})",
        )

    try:
        await page.evaluate(
            """({ inputId }) => {
                const input = document.getElementById(inputId);
                if (!input) return false;
                input.checked = true;
                input.setAttribute("aria-checked", "true");
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
                input.dispatchEvent(new MouseEvent("click", { bubbles: true }));
                const item = input.closest(".guideRadioButtonItem");
                if (item) {
                    for (const sib of item.parentElement?.querySelectorAll(".guideRadioButtonItem") || []) {
                        sib.classList.remove("guideItemSelected");
                    }
                    item.classList.add("guideItemSelected");
                }
                return true;
            }""",
            {"inputId": input_id},
        )
    except Exception:
        pass

    radio_group = page.locator("#guideContainer-rootPanel-seccio_dadesParticulars-panel-panel1662017961273___guide-item").first
    try:
        alt_label = radio_group.get_by_text(label_text, exact=False).first
        if await alt_label.count() > 0:
            await alt_label.click(timeout=FAST_ACTION_TIMEOUT_MS, force=True)
    except Exception:
        pass

    try:
        await page.locator(panel_wait_selector).first.wait_for(state="visible", timeout=8000)
    except Exception:
        logger.warning("No se hizo visible el panel del identificado tras seleccionar tipo persona: %s", label_text)

    await page.wait_for_timeout(800)


async def _fill_identificacion_conductor(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    logger.info("servei_cat_trans rellenando bloque identificado tras comprobar expediente")
    persona = _clean(datos.identificado_tipo_persona).lower() or "fisica"
    is_juridica = persona == "juridica"
    await _select_identificado_tipo_persona(page, is_juridica=is_juridica)
    identificado_section = await _find_identificado_section_selector(page)
    logger.info(
        "servei_cat_trans identificado section selector=%r persona=%s",
        identificado_section,
        "juridica" if is_juridica else "fisica",
    )

    if is_juridica:
        razon_id = "guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-PJ-panel-guidetextbox___widget"
        tipo_doc_id = "guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-PJ-panel_1552294135-guidedropdownlist___widget"
        doc_id = "guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-PJ-panel_1552294135-guidetextbox___widget"
        ok_razon = await _fill_exact_input(page, f"#{razon_id}", datos.identificado_razon_social)
        ok_tipo_doc = await _safe_select_label(
            page,
            f"#{tipo_doc_id}",
            _documento_empresa_label(datos.identificado_nif_empresa),
        )
        ok_doc = await _fill_exact_input(
            page,
            f"#{doc_id}",
            _sanitize_doc(datos.identificado_nif_empresa),
        )
        if not ok_razon:
            fallback_razon_id = await _find_field_id_by_label(
                page,
                "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-PJ__",
                ["razon social"],
                field_kind="input",
            )
            if fallback_razon_id:
                await _fill_exact_input(page, f"#{fallback_razon_id}", datos.identificado_razon_social)
        if not ok_razon:
            ok_razon = await _fill_input_by_label_in_section(
                page,
                identificado_section,
                ["razon social"],
                datos.identificado_razon_social,
            )
        if not ok_tipo_doc:
            fallback_tipo_id = await _find_field_id_by_label(
                page,
                "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-PJ__",
                ["tipo de documento de identificacion"],
                field_kind="select",
            )
            if fallback_tipo_id:
                await _safe_select_label(page, f"#{fallback_tipo_id}", _documento_empresa_label(datos.identificado_nif_empresa))
        if not ok_tipo_doc:
            ok_tipo_doc = await _select_label_in_section(
                page,
                identificado_section,
                ["tipo de documento de identificacion"],
                _documento_empresa_label(datos.identificado_nif_empresa),
            )
        if not ok_doc:
            fallback_doc_id = await _find_field_id_by_label(
                page,
                "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-PJ__",
                ["numero de identificacion"],
                field_kind="input",
            )
            if fallback_doc_id:
                await _fill_exact_input(page, f"#{fallback_doc_id}", _sanitize_doc(datos.identificado_nif_empresa))
        if not ok_doc:
            ok_doc = await _fill_input_by_label_in_section(
                page,
                identificado_section,
                ["numero de identificacion"],
                _sanitize_doc(datos.identificado_nif_empresa),
            )
        await _fill_identificacion_conductor_direccion(
            page,
            section_selector=identificado_section,
            tipo_via_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-ADRECA_PJ_PANEL-ADRECA_LOCALITAT_PJ_PANEL-panel_298747259-guidedropdownlist___widget",
            nombre_via_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-ADRECA_PJ_PANEL-ADRECA_LOCALITAT_PJ_PANEL-panel_298747259-guidetextbox___widget",
            numero_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-ADRECA_PJ_PANEL-ADRECA_LOCALITAT_PJ_PANEL-panel_298747259-panel-guidetextbox___widget",
            cp_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-ADRECA_PJ_PANEL-ADRECA_LOCALITAT_PJ_PANEL-panel_1697806457-guidetextbox___widget",
            provincia_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-ADRECA_PJ_PANEL-ADRECA_LOCALITAT_PJ_PANEL-panel_1697806457-guidedropdownlist___widget",
            comarca_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-ADRECA_PJ_PANEL-ADRECA_LOCALITAT_PJ_PANEL-panel_1697806457-guidedropdownlist_2056216251___widget",
            municipio_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaJuridica-ADRECA_PJ_PANEL-ADRECA_LOCALITAT_PJ_PANEL-panel_1697806457-guidedropdownlist_988023112___widget",
            datos=datos,
        )
    else:
        nombre_id = "guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-PF-panel-guidetextbox_897852897___widget"
        apellido1_id = "guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-PF-panel-guidetextbox_1197861190___widget"
        tipo_doc_id = "guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-PF-panel_1244233668-guidedropdownlist___widget"
        doc_id = "guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-PF-panel_1244233668-guidetextbox___widget"
        documento_label = _documento_persona_label(datos.identificado_nif)
        ok_nombre = await _fill_exact_input(page, f"#{nombre_id}", datos.identificado_nombre)
        ok_ap1 = await _fill_exact_input(page, f"#{apellido1_id}", datos.identificado_apellido1)
        ok_tipo_doc = await _safe_select_label(
            page,
            f"#{tipo_doc_id}",
            documento_label,
        )
        ok_doc = await _fill_exact_input(page, f"#{doc_id}", _sanitize_doc(datos.identificado_nif))
        if not ok_nombre:
            fallback_nombre_id = await _find_field_id_by_label(
                page,
                "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-PF__",
                ["nombre"],
                field_kind="input",
            )
            if fallback_nombre_id:
                await _fill_exact_input(page, f"#{fallback_nombre_id}", datos.identificado_nombre)
        if not ok_nombre:
            ok_nombre = await _fill_input_by_label_in_section(
                page,
                identificado_section,
                ["nombre"],
                datos.identificado_nombre,
            )
        if not ok_ap1:
            fallback_ap1_id = await _find_field_id_by_label(
                page,
                "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-PF__",
                ["primer apellido", "primer cognom"],
                field_kind="input",
            )
            if fallback_ap1_id:
                await _fill_exact_input(page, f"#{fallback_ap1_id}", datos.identificado_apellido1)
        if not ok_ap1:
            ok_ap1 = await _fill_input_by_label_in_section(
                page,
                identificado_section,
                ["primer apellido", "primer cognom"],
                datos.identificado_apellido1,
            )
        await _fill_input_by_label_in_section(
            page,
            identificado_section,
            ["segundo apellido", "segon cognom"],
            datos.identificado_apellido2,
        )
        if not ok_tipo_doc:
            fallback_tipo_id = await _find_field_id_by_label(
                page,
                "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-PF__",
                ["tipo de documento de identificacion"],
                field_kind="select",
            )
            if fallback_tipo_id:
                await _safe_select_label(page, f"#{fallback_tipo_id}", documento_label)
        if not ok_tipo_doc:
            ok_tipo_doc = await _select_label_in_section(
                page,
                identificado_section,
                ["tipo de documento de identificacion"],
                documento_label,
            )
        if documento_label == "Pasaporte":
            ok_pais = await _fill_identificado_pais_emisor(
                page,
                identificado_section,
                datos.identificado_pais_emisor,
            )
            if not ok_pais:
                raise RuntimeError(
                    f"servei_cat_trans.identificacion: no se pudo seleccionar pais emisor para pasaporte ({datos.identificado_pais_emisor!r})."
                )
        if not ok_doc:
            fallback_doc_id = await _find_field_id_by_label(
                page,
                "#guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-PF__",
                ["numero de identificacion"],
                field_kind="input",
            )
            if fallback_doc_id:
                await _fill_exact_input(page, f"#{fallback_doc_id}", _sanitize_doc(datos.identificado_nif))
        if not ok_doc:
            ok_doc = await _fill_input_by_label_in_section(
                page,
                identificado_section,
                ["numero de identificacion"],
                _sanitize_doc(datos.identificado_nif),
            )
        await _fill_identificacion_conductor_direccion(
            page,
            section_selector=identificado_section,
            tipo_via_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-ADRECA_PF-panel1662104193616-panel_298747259-guidedropdownlist___widget",
            nombre_via_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-ADRECA_PF-panel1662104193616-panel_298747259-guidetextbox___widget",
            numero_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-ADRECA_PF-panel1662104193616-panel_298747259-panel-guidetextbox___widget",
            cp_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-ADRECA_PF-panel1662104193616-panel_1697806457-guidetextbox___widget",
            provincia_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-ADRECA_PF-panel1662104193616-panel_1697806457-guidedropdownlist___widget",
            comarca_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-ADRECA_PF-panel1662104193616-panel_1697806457-guidedropdownlist_2056216251___widget",
            municipio_id="guideContainer-rootPanel-seccio_dadesParticulars-panel-personaFisica-ADRECA_PF-panel1662104193616-panel_1697806457-guidedropdownlist_988023112___widget",
            datos=datos,
        )


async def _fill_contenido(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    base = "guideContainer-rootPanel-seccio_dadesParticulars"
    radio_map = {
        "alegaciones": "input[id*='seccio_dadesParticulars'][id$='-1_widget']",
        "reposicion": "input[id*='seccio_dadesParticulars'][id$='-2_widget']",
        "revision": "input[id*='seccio_dadesParticulars'][id$='-3_widget']",
    }
    radio_sel = radio_map.get(datos.tipo_escrito, radio_map["alegaciones"])
    await _safe_check(page, radio_sel)

    # Expongo / Solicito
    content_section = "#guideContainer-rootPanel-seccio_dadesParticulars___guide-item"
    expongo_id = await _find_field_id_by_label(
        page,
        content_section,
        ["expongo", "exposo"],
        field_kind="input",
    )
    if expongo_id:
        await _fill_exact_input(page, f"#{expongo_id}", datos.expongo)
    else:
        logger.warning("servei_cat_trans contenido: no se localizo campo expongo/exposo por etiqueta.")

    solicito_id = await _find_field_id_by_label(
        page,
        content_section,
        ["solicito", "sol licito", "solicitud", "sol.licito"],
        field_kind="input",
    )
    if solicito_id:
        await _fill_exact_input(page, f"#{solicito_id}", datos.solicito)
    else:
        logger.warning("servei_cat_trans contenido: no se localizo campo solicito por etiqueta.")


async def _aceptar_proteccion_datos(page: "Page | Frame") -> None:
    await _safe_check(page, "input[id*='seccio_protecciodade-GDPR'][id$='_widget']")


async def _wait_form_ready(page: "Page", timeout_ms: int) -> "Page | Frame":
    waited = 0
    step_ms = 1000
    while waited <= timeout_ms:
        try:
            state = await page.evaluate(
                """() => {
                    const normalize = (txt) => String(txt || "")
                        .normalize("NFD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                    const loadingTokens = ["carregant", "cargando", "loading"];
                    const bodyText = normalize(document.body?.innerText || "");
                    const stillLoadingByText = loadingTokens.some((token) => bodyText.includes(token));
                    const codi = document.querySelector("#codiPersonal-input");
                    const isVisible = (el) => {
                        if (!el) return false;
                        const st = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return !!st && st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                    };
                    return {
                        has_form_anchor: !!codi && isVisible(codi),
                        still_loading_by_text: stillLoadingByText,
                    };
                }"""
            )
        except Exception:
            state = {"has_form_anchor": False, "still_loading_by_text": True}

        if bool(state.get("has_form_anchor")):
            return await wait_form_scope(page, timeout_ms=timeout_ms)

        await page.wait_for_timeout(step_ms)
        waited += step_ms

    # Fallback blando: a veces el texto "cargando" queda en zonas no activas del DOM.
    anchor = page.locator("#codiPersonal-input").first
    if await anchor.count() > 0:
        await anchor.wait_for(state="visible", timeout=5000)
        return await wait_form_scope(page, timeout_ms=10000)
    raise RuntimeError("servei_cat_trans.formulario: el formulario no quedo listo dentro del timeout.")


async def run_formulario(page: "Page", config: "ServeiCatTransConfig", datos: "ServeiCatTransTarget") -> "Page":
    await page.wait_for_load_state("domcontentloaded")
    form_scope = await _wait_form_ready(page, timeout_ms=config.form_ready_timeout_ms)

    await _safe_fill(page, "#codiPersonal-input", datos.codigo_personal)
    await _fill_presentador_contacto(form_scope, datos)

    # Esperar a que el formulario se estabilice tras rellenar el municipio del representante
    await page.wait_for_timeout(1000)

    # El siguiente paso ES seleccionar el tipo de persona para que se despliegue el formulario
    # Usamos directament el ID exacto proporcionado por el usuario
    if datos.tipo_persona == "juridica":
        logger.info("Seleccionando Persona Juridica...")
        checked = await _safe_check(form_scope, "#guideContainer-rootPanel-seccio_solicitant-tipusPersona-guideradiobutton__-2_widget")
        if not checked:
            # Intento desesperado con selector mas amplio si el ID exacto fallara (aunque no deberia)
            await _safe_check(form_scope, "input[value='entitat_privada']")
        
        await page.wait_for_timeout(1500) # Mas tiempo para que se desplieguen los campos
        await _fill_solicitante_juridica(form_scope, datos)
    else:
        logger.info("Seleccionando Persona Fisica...")
        checked = await _safe_check(form_scope, "#guideContainer-rootPanel-seccio_solicitant-tipusPersona-guideradiobutton__-1_widget")
        if not checked:
            await _safe_check(form_scope, "input[id*='seccio_solicitant-tipusPersona'][id$='-1_widget']")
            
        await page.wait_for_timeout(1500)
        await _fill_solicitante_fisica(form_scope, datos)

    await _fill_notificaciones(form_scope, datos)
    await _fill_expediente(form_scope, datos, config)
    await _fill_contenido(form_scope, datos)
    await _aceptar_proteccion_datos(form_scope)
    return page

