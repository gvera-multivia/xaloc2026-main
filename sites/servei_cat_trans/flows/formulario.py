from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import Frame, Page
    from ..config import ServeiCatTransConfig
    from ..data_models import ServeiCatTransTarget

from .form_scope import wait_form_scope

FAST_ACTION_TIMEOUT_MS = 1200
FAST_SELECT_TIMEOUT_MS = 1500


def _clean(v: object) -> str:
    return str(v or "").strip()


def _sanitize_doc(v: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", _clean(v).upper())


def _documento_persona_label(document: str) -> str:
    doc = _sanitize_doc(document)
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", doc):
        return "NIE"
    if re.fullmatch(r"\d{8}[A-Z]", doc):
        return "DNI"
    return "Pasaporte"


def _documento_empresa_label(document: str) -> str:
    doc = _sanitize_doc(document)
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", doc):
        return "NIF de empresa"
    return "Documento de identidad extranjero"


async def _safe_fill(page: "Page | Frame", selector: str, value: str) -> bool:
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
    locator = page.locator(selector).first
    if await locator.count() <= 0:
        return False
    try:
        await locator.click(timeout=FAST_ACTION_TIMEOUT_MS)
    except Exception:
        return False
    return True


async def _safe_select_label(page: "Page | Frame", selector: str, label: str) -> bool:
    wanted = _clean(label)
    if not wanted:
        return False

    locator = page.locator(selector).first
    if await locator.count() <= 0:
        return False

    try:
        # Intentar selección directa Playwright
        await locator.select_option(label=wanted, timeout=FAST_SELECT_TIMEOUT_MS)
        return True
    except Exception:
        # Fallback: buscar valor por texto normalizado (ignora acentos y mayúsculas) y seleccionar por valor
        opt_value = await locator.evaluate(
            """(el, wantedLabel) => {
                const normalize = (txt) => String(txt || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();
                const wanted = normalize(wantedLabel);
                const options = Array.from(el.options || []);
                
                // 1. Coincidencia exacta normalizada
                let match = options.find((opt) => normalize(opt.textContent || "") === wanted);
                
                // 2. Coincidencia parcial si no hay exacta
                if (!match) {
                    match = options.find((opt) => normalize(opt.textContent || "").includes(wanted));
                }
                
                // 3. Fallback a valor si el label coincide con el valor (ej: "CA" -> "CA")
                if (!match) {
                    match = options.find((opt) => normalize(opt.value || "") === wanted);
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


async def _safe_select_via_id(page: "Page | Frame", element_id: str, label: str) -> bool:
    wanted = _clean(label)
    if not wanted:
        return False
    return bool(
        await page.evaluate(
            """({ elementId, wantedLabel }) => {
                const normalize = (txt) => String(txt || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();
                const el = document.getElementById(elementId);
                if (!el || !el.options) return false;
                const wanted = normalize(wantedLabel);
                const options = Array.from(el.options);
                let opt = options.find((item) => normalize(item.textContent || "") === wanted);
                if (!opt) opt = options.find((item) => normalize(item.textContent || "").includes(wanted));
                if (!opt) return false;
                el.value = String(opt.value || "");
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
            }""",
            {"elementId": element_id, "wantedLabel": wanted},
        )
    )


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
    # 2. ESPERAR a que Comarca cargue sus opciones (depende de Provincia)
    await page.wait_for_timeout(2500)
    await _safe_select_via_id(
        page,
        f"{cp_panel_id}-guidedropdownlist_2056216251___widget",
        datos.direccion_comarca,
    )
    # 3. ESPERAR a que Municipio cargue sus opciones (depende de Comarca)
    await page.wait_for_timeout(2500)
    await _safe_select_via_id(
        page,
        f"{cp_panel_id}-guidedropdownlist_988023112___widget",
        datos.direccion_municipio,
    )


async def _fill_representado_direccion(page: "Page | Frame", panel_id: str, cp_panel_id: str, datos: "ServeiCatTransTarget") -> None:
    # Lógica idéntica a _fill_direccion pero usando los campos de representado_*
    await _safe_select_label(page, f"#{panel_id}-guidedropdownlist___widget", datos.representado_tipo_via)
    await _safe_fill(page, f"#{panel_id}-guidetextbox___widget", datos.representado_nombre_via)
    await _safe_fill(page, f"#{panel_id}-panel-guidetextbox___widget", datos.representado_numero)
    await _safe_fill(page, f"#{cp_panel_id}-guidetextbox___widget", datos.representado_cp)

    # CASCADA: Provincia -> Comarca -> Municipio para Representado
    await _safe_select_via_id(
        page,
        f"{cp_panel_id}-guidedropdownlist___widget",
        datos.representado_provincia or "Barcelona",
    )
    await page.wait_for_timeout(2500)
    if datos.representado_comarca:
        await _safe_select_via_id(
            page,
            f"{cp_panel_id}-guidedropdownlist_2056216251___widget",
            datos.representado_comarca,
        )
        await page.wait_for_timeout(2500)
    if datos.representado_municipio:
        await _safe_select_via_id(
            page,
            f"{cp_panel_id}-guidedropdownlist_988023112___widget",
            datos.representado_municipio,
        )


async def _fill_presentador_contacto(page: "Page | Frame", datos: "ServeiCatTransTarget") -> None:
    prefix = "guideContainer-rootPanel-seccio_presentador-personaJuridica-PJ"
    
    # Prioridad absoluta a aria-label exacta para evitar confusiones con otros campos similares
    if not await _safe_fill(page, f"input[id^='{prefix}'][aria-label='Teléfono móvil'], input[id^='{prefix}'][aria-label='Telèfon mòbil']", datos.telefono_movil):
         await _safe_fill(page, f"input[id^='{prefix}-panel_'][id$='-guidetextbox___widget']", datos.telefono_movil)

    if not await _safe_fill(page, f"input[id^='{prefix}'][aria-label='Correo electrónico'], input[id^='{prefix}'][aria-label='Adreça electrònica'], input[id^='{prefix}'][aria-label='Correu electrònic']", datos.email):
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

    if not await _safe_fill(page, f"input[id^='{prefix}'][aria-label='Teléfono móvil'], input[id^='{prefix}'][aria-label='Telèfon mòbil']", datos.telefono_movil):
        await _safe_fill(page, f"input[id^='{prefix}'][id$='-guidetextbox___widget']", datos.telefono_movil)

    # Dirección del solicitante (persona física)
    # Probar con prefijo -PF (segun md) y sin él (por si acaso es como PJ)
    await page.wait_for_timeout(1000) # Esperar a que se despliegue
    panel_id = f"{base}-adreca-panel_298747259"
    cp_panel_id = f"{base}-adreca-panel_1697806457"
    
    # Verificar si el panel existe, si no, probar sin el sufijo -PF del base
    if await page.locator(f"#{panel_id}-guidetextbox___widget").count() == 0:
        base_short = base.replace("-PF", "")
        panel_id = f"{base_short}-adreca-panel_298747259"
        cp_panel_id = f"{base_short}-adreca-panel_1697806457"

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
    if not await _safe_fill(page, f"input[id^='{rep_prefix}'][aria-label='Teléfono móvil'], input[id^='{rep_prefix}'][aria-label='Telèfon mòbil']", datos.telefono_movil):
        await _safe_fill(page, f"input[id^='{rep_prefix}'][id$='-guidetextbox___widget']", datos.telefono_movil)

    if not await _safe_fill(page, f"input[id^='{rep_prefix}'][aria-label='Correo electrónico'], input[id^='{rep_prefix}'][aria-label='Adreça electrònica'], input[id^='{rep_prefix}'][aria-label='Correu electrònic']", datos.email):
        await _safe_fill(page, f"input[id^='{rep_prefix}'][id$='-guidetextbox_31092572___widget']", datos.email)

    # Dirección del representante (de la persona jurídica solicitante)
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

    await _safe_fill(
        page,
        "#guideContainer-rootPanel-seccio_declaracions-declaracionsText-guidetextbox_6143511_740763653___widget",
        datos.email,
    )
    await _safe_fill(
        page,
        "#guideContainer-rootPanel-seccio_declaracions-declaracionsText-guidetextbox_6143511___widget",
        datos.telefono_movil,
    )


async def _fill_expediente(page: "Page | Frame", datos: "ServeiCatTransTarget", config: "ServeiCatTransConfig") -> None:
    base = "guideContainer-rootPanel-seccio_dadesParticulars"
    # Selectores robustos para datos del expediente
    await _safe_fill(page, f"div[id^='{base}'] [id$='-guidetextbox___widget']", datos.servicio_territorial)
    await _safe_fill(page, f"div[id^='{base}'] [id$='-guidetextbox_5569220___widget']", datos.expediente_numero)
    await _safe_fill(page, f"div[id^='{base}'] [id$='-guidetextbox_1768694___widget']", datos.digito_control)

    clicked = await _safe_click(page, "button:has-text('Comprobar datos expediente')")
    if not clicked:
        fallback_btn = page.get_by_role("button", name=re.compile(r"comprobar|comprovar", re.IGNORECASE)).first
        if await fallback_btn.count() > 0:
            await fallback_btn.click(timeout=FAST_ACTION_TIMEOUT_MS)
            clicked = True
    if clicked:
        ok_text = page.get_by_text(
            re.compile(
                rf"{re.escape(config.expediente_ok_pattern)}|dades de l'expedient.*correct",
                re.IGNORECASE,
            )
        ).first
        await ok_text.wait_for(timeout=15000)


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
    await _safe_fill(page, f"div[id^='{base}'] [id$='-guidetextbox___widget']", datos.expongo)
    await _safe_fill(page, f"div[id^='{base}'] [id$='-guidetextbox_641545334___widget']", datos.solicito)


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

