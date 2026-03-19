from __future__ import annotations

import asyncio
from datetime import datetime
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from playwright.async_api import Download
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from core.autofirma_shared import (
    prewarm_autofirma_process,
    reset_afirma_uri_capture_file,
    stop_autofirma_prewarm,
    wait_autofirma_prewarm_ready,
    wait_for_afirma_uri_trigger,
)
from core.address_defaults import get_default_country_es_ascii
from core.client_documentation import client_identity_from_payload
from core.client_paths import get_ruta_recursos_telematicos, resolve_client_docs_base_path
from core.worker_execution.utils import extract_expediente_number, sanitize_filename_component
from sites.redsara.config import RedsaraConfig
from sites.redsara.data_models import RedsaraTarget
from sites.redsara.flows.firma_proxy import sign_with_proxy_and_download
from sites.redsara.flows.select_heuristic import (
    HEURISTIC_MIN_SCORE,
    normalize_city_alias,
    normalize_province_alias,
    select_option_heuristic_js,
    verify_selected_input_js,
)

FIELD_SETTLE_DELAY_MS = 180
REDSARA_STREET_TYPE_SELECT_IDS = {"represented.streetType", "streetType"}
REDSARA_STREET_TYPE_OPTIONS = [
    "Alameda",
    "Avenida",
    "Avinguda",
    "Barrio",
    "Bulevar",
    "Calle",
    "Calleja",
    "Camí",
    "Camino",
    "Campo",
    "Carrer",
    "Carrera",
    "Carretera",
    "Cuesta",
    "Edificio",
    "Enparantza",
    "Estrada",
    "Glorieta",
    "Jardines",
    "Jardins",
    "Kalea",
    "Otros",
    "Parque",
    "Pasaje",
    "Paseo",
    "Passatge",
    "Passeig",
    "Plaça",
    "Placeta",
    "Plaza",
    "Plazuela",
    "Poblado",
    "Polígono",
    "Praza",
    "Rambla",
    "Ronda",
    "Rúa",
    "Sector",
    "Travesía",
    "Travessera",
    "Urbanización",
    "Via",
]
REDSARA_STREET_TYPE_ALIASES = {
    "cl": "Calle",
    "c": "Calle",
    "c/": "Calle",
    "av": "Avenida",
    "avda": "Avenida",
    "rda": "Ronda",
    "ctra": "Carretera",
    "pl": "Plaza",
    "pg": "Paseo",
    "ps": "Paseo",
    "trav": "Travesía",
    "trv": "Travesía",
    "urb": "Urbanización",
    "pol": "Polígono",
}


def _normalize_street_type_key(raw: str | None) -> str:
    value = unicodedata.normalize("NFD", str(raw or "").strip().lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[\s\.,;:/_\\-]+", " ", value).strip()
    return value


def _canonical_street_type(option_text: str | None) -> str:
    by_key = {_normalize_street_type_key(v): v for v in REDSARA_STREET_TYPE_OPTIONS}
    by_key.update({k: v for k, v in REDSARA_STREET_TYPE_ALIASES.items()})
    key = _normalize_street_type_key(option_text)
    if key and key in by_key:
        return by_key[key]
    return "Otros"


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "si", "sí"}


def _classify_sign_result_from_text(*, step4_present: bool, detail_loaded: bool, modal_visible: bool, modal_text: str) -> str | None:
    if detail_loaded or not step4_present:
        return "success"
    if not modal_visible:
        return None

    txt = (modal_text or "").lower()
    # Redsara puede mostrar modal "other_error" con texto de éxito.
    if "se ha firmado correctamente" in txt:
        return "success"
    if ("unmarshalling" in txt) or ("read timed out" in txt) or ("timed out" in txt):
        return "unmarshalling_timeout"
    if ("applicationnotfoundexception" in txt) or ("no se ha podido conectar" in txt):
        return "autofirma_not_found"
    return "other_error"


async def _wait_until_interactive(page: Page) -> None:
    """
    Wait until loading overlays/spinners are gone to avoid click interception.
    """
    for selector in [
        ".fullScreen",
        "dnt-spinner[title-text='Cargando...']",
    ]:
        try:
            await page.locator(selector).first.wait_for(state="hidden", timeout=8000)
        except Exception:
            pass


async def _fill_input(page: Page, selector: str, value: str) -> None:
    loc = page.locator(selector).first
    await loc.wait_for(state="visible", timeout=10000)
    await loc.click()
    await loc.fill(value)
    await page.wait_for_timeout(FIELD_SETTLE_DELAY_MS)


async def _click_next_step1(page: Page, config: RedsaraConfig) -> None:
    btn = page.locator(config.selectors.step1_next_button).first
    await btn.wait_for(state="visible", timeout=15000)

    for attempt in range(1, 6):
        await _wait_until_interactive(page)

        state = await page.evaluate(
            """() => {
                const host = Array.from(document.querySelectorAll('app-create-registry-step1 dnt-button'))
                  .find((el) => ((el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase().includes('siguiente')))
                if (!host) return { found: false, disabled: true, detail: 'not-found' }

                const attr = (host.getAttribute('is-disabled') || '').trim().toLowerCase()
                const cssDisabled =
                  host.classList.contains('is-disabled') ||
                  host.classList.contains('dnt-button--disabled') ||
                  host.classList.contains('disabled')
                const btn = host.shadowRoot?.querySelector('button')
                const disabled = cssDisabled || attr === 'true' || attr === '' || !!btn?.disabled
                return { found: true, disabled, detail: { attr, cssDisabled, btnDisabled: !!btn?.disabled } }
            }"""
        )
        print(f"[REDSARA] Step1 'Siguiente' estado intento {attempt}: {state}")
        await btn.click(force=True)

        try:
            await page.locator(config.selectors.step2_heading).first.wait_for(state="visible", timeout=4000)
            print("[REDSARA] Paso 2 detectado tras pulsar 'Siguiente'.")
            return
        except Exception:
            pass

        await page.wait_for_timeout(1000)

    missing = await page.evaluate(
        """() => {
            const root = document.querySelector('app-create-registry-step1')
            if (!root) return ['No se encontro app-create-registry-step1']
            const out = []

            const reqInputs = Array.from(root.querySelectorAll("input[required]:not([type='hidden']), textarea[required]"))
            for (const el of reqInputs) {
                const value = (el.value || '').trim()
                if (!value) {
                    out.push(`Campo requerido vacio: ${el.getAttribute('placeholder') || el.getAttribute('id') || el.getAttribute('aria-labelledby') || el.tagName}`)
                }
            }

            const reqSelects = Array.from(root.querySelectorAll('dnt-select[required]'))
            for (const sel of reqSelects) {
                const value = (sel.getAttribute('value') || sel.value || '').trim()
                if (!value) {
                    out.push(`Select requerido vacio: ${sel.getAttribute('id') || sel.getAttribute('name') || 'dnt-select'}`)
                }
            }

            return out
        }"""
    )
    raise RuntimeError(f"No se pudo avanzar a Paso 2 tras pulsar 'Siguiente'. Requeridos pendientes: {missing}")


async def _click_next_step2(page: Page, config: RedsaraConfig) -> None:
    btn = page.locator(config.selectors.step2_next_button).first
    await btn.wait_for(state="visible", timeout=15000)
    await _wait_until_interactive(page)
    await btn.click(force=True)
    await page.locator(config.selectors.attachments_input).first.wait_for(state="attached", timeout=20000)
    print("[REDSARA] Paso 3 detectado tras pulsar 'Siguiente' en paso 2.")


async def _upload_files(page: Page, config: RedsaraConfig, archivos: list[str | Path] | None) -> None:
    paths: list[Path] = []
    for item in list(archivos or []):
        p = Path(item).expanduser().resolve()
        if p.exists() and p.is_file():
            paths.append(p)
    if not paths:
        raise RuntimeError("REDSARA: no hay archivos reales para adjuntar en paso 3.")
    file_input = page.locator(config.selectors.attachments_input).first
    await file_input.wait_for(state="attached", timeout=15000)
    await file_input.set_input_files([str(p) for p in paths])
    expected_names = [p.name for p in paths]
    await _wait_until_uploaded_files_visible(page, expected_names=expected_names, timeout_ms=60000)
    print(f"[REDSARA] Adjuntos subidos: {len(paths)} archivo(s).")


async def _wait_until_uploaded_files_visible(page: Page, *, expected_names: list[str], timeout_ms: int = 60000) -> None:
    """
    Espera a que los ficheros subidos sean visibles en el resumen de adjuntos
    antes de permitir avanzar al siguiente paso.
    """
    expected = [str(x or "").strip() for x in expected_names if str(x or "").strip()]
    if not expected:
        return

    await page.wait_for_function(
        """({ names }) => {
            const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase()
            const expected = names.map(norm).filter(Boolean)
            if (!expected.length) return true

            const sections = Array.from(document.querySelectorAll('section'))
            const summarySection = sections.find((sec) => {
                const h2 = sec.querySelector('h2')
                const t = norm(h2?.textContent || '')
                return t.includes('resumen de los documentos adjuntos')
            }) || document

            const spans = Array.from(summarySection.querySelectorAll('ul li span'))
            const listed = spans
                .map((el) => norm(el.textContent || ''))
                .filter((txt) => txt && txt.includes('.'))

            return expected.every((name) => listed.some((item) => item.includes(name)))
        }""",
        arg={"names": expected},
        timeout=timeout_ms,
    )


async def _wait_until_next_button_enabled(page: Page, timeout_ms: int = 15000) -> None:
    """
    Espera a que el botón Siguiente del paso 3 esté habilitado en host + shadow DOM.
    """
    await page.wait_for_function(
        """() => {
            const step3 = document.querySelector('app-create-registry-step3')
            if (!step3) return false
            const host = step3.querySelector('dnt-button[type="primary-light"]')
            if (!host) return false

            const hostState = host.getAttribute('is-disabled')
            const hostDisabled = hostState === 'true' || hostState === ''
            if (hostDisabled || host.getAttribute('aria-disabled') === 'true') return false

            const btn = host.shadowRoot?.querySelector('button')
            if (!btn) return false
            if (btn.disabled) return false
            if (btn.getAttribute('aria-disabled') === 'true') return false
            if (btn.classList.contains('is-disabled')) return false
            return true
        }""",
        timeout=timeout_ms,
    )


async def _click_next_after_attachments(page: Page) -> None:
    await _wait_until_interactive(page)
    await _wait_until_next_button_enabled(page)
    next_host = page.locator("app-create-registry-step3 dnt-button[type='primary-light']").first
    await next_host.wait_for(state="visible", timeout=8000)

    clicked = await next_host.evaluate(
        """host => {
            const btn =
                host.shadowRoot?.querySelector('button[data-name="DntButton"]')
                || host.shadowRoot?.querySelector('button[part="dnt-button"]')
                || host.shadowRoot?.querySelector('button')
            if (!btn) return false
            const hostState = host.getAttribute('is-disabled')
            const hostDisabled = hostState === 'true' || hostState === '' || host.getAttribute('aria-disabled') === 'true'
            if (hostDisabled || !!btn.disabled || btn.getAttribute('aria-disabled') === 'true' || btn.classList.contains('is-disabled')) return false
            btn.click()
            return true
        }"""
    )
    if not clicked:
        raise RuntimeError("REDSARA: no se pudo clicar 'Siguiente' tras adjuntos (shadow button).")
    print("[REDSARA] Click shadow button 'Siguiente' tras adjuntos OK.")


async def _check_terms_checkbox(page: Page) -> None:
    await page.wait_for_function(
        """() => !!(
            document.querySelector('dnt-checkbox[name="checkTerms"]')
            || document.querySelector('input[name="checkTerms"]')
        )""",
        timeout=20000,
    )
    changed = await page.evaluate(
        """() => {
            const host = document.querySelector('dnt-checkbox[name="checkTerms"]')
            if (host) {
                const input = host.shadowRoot?.querySelector('input[type="checkbox"]')
                const label = host.shadowRoot?.querySelector('label')
                if (input?.checked) return true
                if (label) {
                    label.click()
                } else if (input) {
                    input.click()
                }
                return !!(input && input.checked)
            }
            const plain = document.querySelector('input[name="checkTerms"]')
            if (!plain) return false
            if (!plain.checked) plain.click()
            return !!plain.checked
        }"""
    )
    if not changed:
        raise RuntimeError("REDSARA: no se pudo marcar checkbox checkTerms.")
    print("[REDSARA] Checkbox checkTerms marcado.")


async def _select_sign_with_certificate_option(page: Page) -> None:
    await page.wait_for_function("""() => !!document.querySelector('app-create-registry-step4 dnt-split-button#btnSignature')""", timeout=15000)
    opened = False
    for _ in range(30):  # ~6s
        opened = await page.evaluate(
            """() => {
                const split = document.querySelector('app-create-registry-step4 dnt-split-button#btnSignature')
                if (!split) return false
                const sr = split.shadowRoot

                // 1) Camino ideal: botón dropdown dentro de shadow root.
                if (sr) {
                    const dropdownHost =
                        sr.querySelector('dnt-button.dnt-split-button__dropdown-button')
                        || sr.querySelector('dnt-button[aria-controls]')
                        || sr.querySelectorAll('dnt-button')[1]
                    if (dropdownHost) {
                        const btn =
                            dropdownHost.shadowRoot?.querySelector('button')
                            || dropdownHost.shadowRoot?.querySelector('button[part="dnt-button"]')
                            || dropdownHost.shadowRoot?.querySelector('button[data-name="DntButton"]')
                        if (btn && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true') {
                            btn.click()
                        } else {
                            dropdownHost.click()
                        }
                    }
                }

                // 2) Fallback: click host split-button (algunas versiones lo abren así).
                if (!document.querySelector('dnt-dropdown-item')) {
                    split.click()
                }

                // 3) Verificación de apertura por presencia de items.
                return !!(
                    document.querySelector('dnt-dropdown-item')
                    || split.shadowRoot?.querySelector('dnt-dropdown-item')
                )
            }"""
        )
        if opened:
            break
        await page.wait_for_timeout(200)
    if not opened:
        raise RuntimeError("REDSARA: no se pudo abrir dropdown de firma.")

    # Polling robusto: algunos builds renderizan dnt-dropdown-item fuera del light DOM
    # o con retardo tras abrir el split-button.
    selected = False
    for _ in range(60):  # ~12s (60 * 200ms)
        selected = await page.evaluate(
            """() => {
                const split = document.querySelector('app-create-registry-step4 dnt-split-button#btnSignature')
                if (!split) return false

                const fromDoc = Array.from(document.querySelectorAll('dnt-dropdown-item.dnt-split-button__dropdown-item'))
                const fromSplitShadow = Array.from(split.shadowRoot?.querySelectorAll('dnt-dropdown-item.dnt-split-button__dropdown-item') || [])
                const genericDoc = fromDoc.length ? [] : Array.from(document.querySelectorAll('dnt-dropdown-item'))
                const genericShadow = fromSplitShadow.length ? [] : Array.from(split.shadowRoot?.querySelectorAll('dnt-dropdown-item') || [])

                const merged = [...fromDoc, ...fromSplitShadow, ...genericDoc, ...genericShadow]
                const unique = []
                const seen = new Set()
                for (const el of merged) {
                    if (!el || seen.has(el)) continue
                    seen.add(el)
                    unique.push(el)
                }

                if (!unique.length) return false
                // Preferir item por texto, fallback a indice 2.
                const norm = (s) => String(s || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().replace(/\\s+/g, ' ').trim()
                const byText = unique.find((el) => {
                    const t = norm(el.shadowRoot?.textContent || el.textContent || '')
                    return t.includes('firmar con certificado') || t.includes('certificado electronico') || t.includes('certificado electr') || t.includes('certificate')
                })
                const target = byText || unique[1] || unique[0]
                const clickable =
                    target.shadowRoot?.querySelector('div.item[role="menuitem"]')
                    || target.shadowRoot?.querySelector('[role="menuitem"]')
                    || target.shadowRoot?.querySelector('button,[part]')
                    || target.shadowRoot?.querySelector('*')
                if (clickable) clickable.click()
                else target.click()
                return true
            }"""
        )
        if selected:
            break
        await page.wait_for_timeout(200)

    if not selected:
        raise RuntimeError("REDSARA: no se pudo seleccionar opcion de firma con certificado (dropdown item index 2).")
    print("[REDSARA] Opcion de firma con certificado seleccionada (indice 2 del menu).")


async def _click_split_main_signature_button(page: Page) -> None:
    clicked = False
    for _ in range(40):  # ~8s
        clicked = await page.evaluate(
            """() => {
                const split = document.querySelector('app-create-registry-step4 dnt-split-button#btnSignature')
                if (!split || !split.shadowRoot) return false
                const mainHost =
                    split.shadowRoot.querySelector('dnt-button.dnt-split-button__main-button')
                    || split.shadowRoot.querySelector('dnt-button[title-text]')
                    || split.shadowRoot.querySelector('dnt-button')
                if (!mainHost) return false
                const btn =
                    mainHost.shadowRoot?.querySelector('button[data-name="DntButton"]')
                    || mainHost.shadowRoot?.querySelector('button[part="dnt-button"]')
                    || mainHost.shadowRoot?.querySelector('button')
                if (!btn) return false
                const hostState = mainHost.getAttribute('is-disabled')
                const hostDisabled = hostState === 'true' || hostState === '' || mainHost.getAttribute('aria-disabled') === 'true'
                if (hostDisabled || btn.disabled || btn.getAttribute('aria-disabled') === 'true' || btn.classList.contains('is-disabled')) {
                    return false
                }
                btn.click()
                return true
            }"""
        )
        if clicked:
            break
        await page.wait_for_timeout(200)
    if not clicked:
        raise RuntimeError("REDSARA: no se pudo clicar el boton principal 'Firmar con certificado electrónico'.")
    print("[REDSARA] Click en boton principal de firma con certificado OK.")


async def _configure_autoscript_timeouts(page: Page) -> None:
    launch_ms = _env_int("XALOC_REDSARA_AUTOSCRIPT_LAUNCH_MS", 8000)
    retries = _env_int("XALOC_REDSARA_AUTOSCRIPT_RETRIES", 30)
    await page.evaluate(
        """({ launchMs, retries }) => {
            const autoscript = window.AutoScript
            if (!autoscript) return false
            autoscript.AUTOFIRMA_LAUNCHING_TIME = launchMs
            autoscript.AUTOFIRMA_CONNECTION_RETRIES = retries
            return true
        }""",
        {"launchMs": launch_ms, "retries": retries},
    )
    print(f"[REDSARA] AutoScript tuned: launch={launch_ms} retries={retries}")


async def _close_sign_error_modal(page: Page) -> None:
    await page.evaluate(
        """() => {
            const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase()
            const modals = Array.from(document.querySelectorAll('dnt-modal'))
            const visible = modals.find((m) => {
                const vis = m.getAttribute('visible')
                if (vis === null || vis === 'false') return false
                const txt = norm(m.textContent || '')
                return txt.includes('mensaje de error') || txt.includes('error')
            })
            if (!visible) return false

            const hosts = Array.from(visible.querySelectorAll('dnt-button'))
            for (const host of hosts) {
                const txt = norm(host.textContent || host.getAttribute('title-text') || '')
                if (!(txt.includes('cerrar') || txt.includes('aceptar') || txt.includes('entendido') || txt.includes('ok'))) continue
                const btn = host.shadowRoot?.querySelector('button') || host.shadowRoot?.querySelector('button[part="dnt-button"]')
                if (btn) {
                    btn.click()
                    return true
                }
                host.click()
                return true
            }
            visible.click()
            return true
        }"""
    )


async def _wait_sign_result(page: Page, timeout_ms: int) -> str:
    result = await page.wait_for_function(
        """() => {
            const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase()
            const step4Present = !!document.querySelector('app-create-registry-step4')
            const detailLoaded = !!document.querySelector('app-detail-registry-view') || norm(location.href).includes('/detalle-registro/')

            const modals = Array.from(document.querySelectorAll('dnt-modal'))
            const modal = modals.find((m) => {
                const vis = m.getAttribute('visible')
                return !(vis === null || vis === 'false')
            })
            const modalVisible = !!modal
            const modalText = modal ? norm(modal.textContent || '') : ''

            if (detailLoaded || !step4Present) return 'success'
            if (!modalVisible) return null

            if (modalText.includes('unmarshalling') || modalText.includes('read timed out') || modalText.includes('timed out')) return 'unmarshalling_timeout'
            if (modalText.includes('applicationnotfoundexception') || modalText.includes('no se ha podido conectar')) return 'autofirma_not_found'
            return 'other_error'
        }""",
        timeout=timeout_ms,
    )
    if not isinstance(result, str):
        raise RuntimeError("REDSARA: resultado de firma invalido.")
    return result


async def _wait_detail_page(page: Page, timeout_ms: int = 30000) -> str | None:
    await page.wait_for_selector(
        "app-detail-registry-view dnt-button[title-text='Descargar justificante']",
        state="attached",
        timeout=timeout_ms,
    )
    match = re.search(r"detalle-registro/([a-f0-9-]+)", page.url or "", re.IGNORECASE)
    return match.group(1) if match else None


async def _download_justificante(page: Page, save_path: Path) -> Path:
    if save_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = save_path.with_name(f"{save_path.stem} {ts}{save_path.suffix}")

    await page.wait_for_function(
        """() => {
            const host = document.querySelector('app-detail-registry-view dnt-button[title-text="Descargar justificante"]')
            if (!host) return false
            const isDisabled = host.getAttribute('is-disabled')
            if (isDisabled === 'true' || isDisabled === '') return false
            const rect = host.getBoundingClientRect()
            return rect.width > 0 && rect.height > 0
        }""",
        timeout=15000,
    )

    async with page.expect_download(timeout=30000) as download_info:
        clicked = await page.evaluate(
            """() => {
                const host = document.querySelector('app-detail-registry-view dnt-button[title-text="Descargar justificante"]')
                if (!host) return false
                host.click()
                return true
            }"""
        )
        if not clicked:
            raise RuntimeError("REDSARA: no se encontró el botón 'Descargar justificante'.")

    download: Download = await download_info.value
    save_path.parent.mkdir(parents=True, exist_ok=True)
    await download.save_as(str(save_path))
    if not save_path.exists() or save_path.stat().st_size == 0:
        raise RuntimeError(f"REDSARA: justificante descargado vacío: {save_path}")
    return save_path


def _resolve_client_justificante_path(data: RedsaraTarget, file_name: str) -> Path | None:
    payload = dict(data.payload or {})
    if not payload:
        return None
    try:
        client = client_identity_from_payload(payload)
        client_dir = get_ruta_recursos_telematicos(
            client=client,
            base_path=resolve_client_docs_base_path(),
            fase_procedimiento=payload.get("FaseProcedimiento"),
        )
        return client_dir / file_name
    except Exception:
        return None


def _resolve_non_overwrite_path(path: Path) -> Path:
    if not path.exists():
        return path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = path.with_name(f"{path.stem} {ts}{path.suffix}")
    if not candidate.exists():
        return candidate
    for idx in range(1, 1000):
        alt = path.with_name(f"{path.stem} {ts}_{idx}{path.suffix}")
        if not alt.exists():
            return alt
    return path.with_name(f"{path.stem} {datetime.now().timestamp():.0f}{path.suffix}")


def _justificante_filename(data: RedsaraTarget) -> str:
    payload = dict(data.payload or {})
    expediente = sanitize_filename_component(extract_expediente_number(payload))
    if expediente == "UNKNOWN":
        expediente = sanitize_filename_component(str(payload.get("idRecurso") or "UNKNOWN"))
    return f"JUSTIFICANTE - {expediente}.pdf"


async def _sign_with_retry_and_download(page: Page, data: RedsaraTarget, prewarm_proc: subprocess.Popen | None = None) -> dict:
    retries = _env_int("XALOC_REDSARA_SIGN_RETRIES", 3)
    timeout_ms = _env_int("XALOC_REDSARA_SIGN_TIMEOUT_MS", 120000)
    own_prewarm = prewarm_proc is None
    if prewarm_proc is None:
        prewarm_proc = prewarm_autofirma_process()
    if prewarm_proc:
        ready_ms = _env_int("XALOC_REDSARA_AUTOFIRMA_READY_WAIT_MS", 5000)
        await wait_autofirma_prewarm_ready(prewarm_proc, timeout_ms=ready_ms)

    try:
        await _configure_autoscript_timeouts(page)
        for attempt in range(1, retries + 1):
            print(f"[REDSARA] Firma intento {attempt}/{retries}")
            reset_afirma_uri_capture_file()
            await _click_split_main_signature_button(page)
            uri = await wait_for_afirma_uri_trigger(timeout_ms=_env_int("XALOC_REDSARA_URI_TRIGGER_WAIT_MS", 12000))
            if uri:
                print(f"[REDSARA] Trigger AutoFirma detectado: {uri[:90]}...")
            else:
                print("[REDSARA] Aviso: no se detectó URI de AutoFirma tras clicar firmar (seguimos esperando resultado).")
            result = await _wait_sign_result(page, timeout_ms=timeout_ms)
            if result == "success":
                registry_uuid = await _wait_detail_page(page, timeout_ms=30000)
                file_name = _justificante_filename(data)
                artifact_path = Path("tmp") / "redsara" / "justificantes" / file_name
                downloaded = await _download_justificante(page, artifact_path)

                client_target = _resolve_client_justificante_path(data, file_name)
                client_saved = None
                if client_target is not None:
                    client_target = _resolve_non_overwrite_path(client_target)
                    client_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(downloaded, client_target)
                    client_saved = client_target

                return {
                    "redsara_signed": True,
                    "redsara_registry_uuid": registry_uuid,
                    "redsara_justificante_artifact_path": str(downloaded),
                    "redsara_justificante_client_path": str(client_saved) if client_saved else None,
                    "redsara_sign_attempts": attempt,
                    "redsara_sign_error_code": None,
                }

            await _close_sign_error_modal(page)
            if result == "unmarshalling_timeout":
                await page.wait_for_timeout(2000)
                continue

            raise RuntimeError(f"REDSARA: fallo firma no recuperable ({result}).")

        raise RuntimeError(f"REDSARA: firma fallida tras {retries} intentos.")
    finally:
        if own_prewarm:
            stop_autofirma_prewarm(prewarm_proc)


async def _fill_dnt_input(page: Page, form_group_name: str, form_control_name: str, value: str) -> None:
    """
    Fill dnt-input by scoping to formgroupname and dispatching events expected by web component + Angular.
    """
    filled = await page.evaluate(
        """({ groupName, controlName, val }) => new Promise((resolve) => {
            const groups = document.querySelectorAll(`[formgroupname="${groupName}"]`)
            for (const group of groups) {
                const dntInput = group.querySelector(`dnt-input[formcontrolname="${controlName}"]`)
                if (!dntInput) continue
                const innerInput = dntInput.shadowRoot?.querySelector('input:not([type="hidden"])')
                if (!innerInput) continue

                const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
                if (!nativeSetter) { resolve(false); return }

                innerInput.scrollIntoView({ block: 'nearest' })
                innerInput.click()
                innerInput.focus()

                setTimeout(() => {
                    nativeSetter.call(innerInput, val)

                    innerInput.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        composed: true,
                        inputType: 'insertText',
                        data: (val || '').charAt((val || '').length - 1) || val
                    }))

                    innerInput.dispatchEvent(new FocusEvent('blur', {
                        bubbles: true,
                        composed: true
                    }))

                    setTimeout(() => {
                        const finalValue = (dntInput.value || innerInput.value || '').trim()
                        resolve(finalValue === (val || '').trim())
                    }, 50)
                }, 50)
                return
            }
            resolve(false)
        })""",
        {"groupName": form_group_name, "controlName": form_control_name, "val": value},
    )
    if not filled:
        raise RuntimeError(
            f"No se pudo rellenar dnt-input[formgroupname='{form_group_name}'][formcontrolname='{form_control_name}']"
        )
    print(f"[REDSARA] fill_dnt_input OK: {form_group_name}.{form_control_name}='{value}'")


async def _select_dnt_option_by_id(
    page: Page, *, select_id: str, option_text: str, wait_for_options: bool = False
) -> None:
    """
    Selects an option in REG dnt-select web-components traversing shadow roots.
    """
    escaped_id = select_id.replace(".", "\\.")
    select_root = page.locator(f"dnt-select#{escaped_id}").first
    await select_root.wait_for(state="visible", timeout=10000)

    if wait_for_options:
        await page.wait_for_function(
            """({ sid }) => {
                const escaped = sid.replace(/\\./g, '\\\\.')
                const el = document.querySelector(`dnt-select#${escaped}`)
                return !!el && el.querySelectorAll('dnt-option').length > 0
            }""",
            arg={"sid": select_id},
            timeout=8000,
        )

    opened = await page.evaluate(
        """({ sid }) => {
            const escaped = sid.replace(/\\./g, '\\\\.')
            const selectEl = document.querySelector(`dnt-select#${escaped}`)
            if (!selectEl || !selectEl.shadowRoot) return false
            const dntInput = selectEl.shadowRoot.querySelector('dnt-input')
            const input = dntInput?.shadowRoot?.querySelector('input.dnt-input__inner')
            if (!input) return false
            input.click()
            return true
        }""",
        {"sid": select_id},
    )
    if not opened:
        raise RuntimeError(f"No se pudo abrir dnt-select#{select_id}")

    await page.wait_for_function(
        """({ sid }) => {
            const escaped = sid.replace(/\\./g, '\\\\.')
            const selectEl = document.querySelector(`dnt-select#${escaped}`)
            const dropdown = selectEl?.shadowRoot?.querySelector('dnt-select-dropdown')
            const popper = dropdown?.shadowRoot?.querySelector('dnt-popover .dnt-popover__popper')
            return !!popper && !popper.classList.contains('is-hidden')
        }""",
        arg={"sid": select_id},
        timeout=5000,
    )

    # Campo sensible: tipo de documento. Forzar selección exacta para no caer
    # en fallback de "primera opción" (NIF) cuando el objetivo es NIE/CIF/etc.
    if select_id == "tipoDoc":
        clicked_exact = await page.evaluate(
            """({ sid, text }) => {
                const norm = (s) => String(s || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().replace(/\\s+/g, ' ').trim()
                const escaped = sid.replace(/\\./g, '\\\\.')
                const selectEl = document.querySelector(`dnt-select#${escaped}`)
                if (!selectEl) return false
                const target = norm(text)
                const options = Array.from(selectEl.querySelectorAll('dnt-option'))
                const getLabel = (opt) => norm(opt.shadowRoot?.querySelector('[role="option"]')?.textContent || opt.textContent || '')
                const exact = options.find((opt) => getLabel(opt) === target)
                if (!exact) return false
                const optionDiv = exact.shadowRoot?.querySelector('[role="option"]')
                if (!optionDiv) return false
                optionDiv.click()
                return true
            }""",
            {"sid": select_id, "text": option_text},
        )
        if not clicked_exact:
            raise RuntimeError(
                f"No se encontró opción exacta para dnt-select#{select_id} con valor '{option_text}'."
            )
        await page.wait_for_timeout(FIELD_SETTLE_DELAY_MS)
        return

    if select_id in REDSARA_STREET_TYPE_SELECT_IDS:
        resolved_option = _canonical_street_type(option_text)
        clicked_street_type = await page.evaluate(
            """({ sid, text }) => {
                const norm = (s) => String(s || '')
                    .normalize('NFD')
                    .replace(/[\\u0300-\\u036f]/g, '')
                    .toLowerCase()
                    .replace(/[\\s\\.,;:/_\\-]+/g, ' ')
                    .trim()
                const escaped = sid.replace(/\\./g, '\\\\.')
                const selectEl = document.querySelector(`dnt-select#${escaped}`)
                if (!selectEl) return ''
                const target = norm(text)
                const options = Array.from(selectEl.querySelectorAll('dnt-option'))
                const getOption = (opt) => opt?.shadowRoot?.querySelector('[role="option"]')
                const getLabel = (opt) => norm(getOption(opt)?.textContent || opt?.textContent || '')
                const exact = options.find((opt) => getLabel(opt) === target)
                const fallbackOtros = options.find((opt) => getLabel(opt) === 'otros')
                const chosen = exact || fallbackOtros
                if (!chosen) return ''
                const optionDiv = getOption(chosen)
                if (!optionDiv) return ''
                optionDiv.click()
                return (optionDiv.textContent || '').replace(/\\s+/g, ' ').trim()
            }""",
            {"sid": select_id, "text": resolved_option},
        )
        if not str(clicked_street_type or "").strip():
            raise RuntimeError(
                f"No se encontró opción válida para dnt-select#{select_id} con valor '{resolved_option}'."
            )
        await page.wait_for_timeout(FIELD_SETTLE_DELAY_MS)
        return

    selection = await page.evaluate(select_option_heuristic_js(HEURISTIC_MIN_SCORE), {"sid": select_id, "text": option_text})

    clicked = bool(selection and selection.get("clicked"))
    best_score = int(selection.get("bestScore", -1)) if isinstance(selection, dict) else -1
    used_fallback = False
    if not clicked:
        used_fallback = True
        print(
            f"[REDSARA] Heuristica sin click para #{select_id} (score={best_score}). "
            "Aplicando fallback teclado."
        )
        typed = await page.evaluate(
            """({ sid, text }) => {
                const escaped = sid.replace(/\\./g, '\\\\.')
                const selectEl = document.querySelector(`dnt-select#${escaped}`)
                const input = selectEl?.shadowRoot
                    ?.querySelector('dnt-input')
                    ?.shadowRoot
                    ?.querySelector('input.dnt-input__inner')
                if (!input) return false
                input.focus()
                input.value = ''
                input.dispatchEvent(new Event('input', { bubbles: true }))
                input.value = text
                input.dispatchEvent(new Event('input', { bubbles: true }))
                return true
            }""",
            {"sid": select_id, "text": option_text},
        )
        if not typed:
            raise RuntimeError(f"No se pudo preparar fallback en dnt-select#{select_id}")

        input_loc = (
            page.locator(f"dnt-select#{escaped_id}")
            .first
            .locator("dnt-input")
            .first
            .locator("input.dnt-input__inner")
            .first
        )
        await input_loc.press("ArrowDown")
        await input_loc.press("Enter")
        await page.wait_for_timeout(FIELD_SETTLE_DELAY_MS)

    try:
        await page.wait_for_function(
            verify_selected_input_js(HEURISTIC_MIN_SCORE),
            arg={"sid": select_id, "text": option_text},
            timeout=3000,
        )
    except PlaywrightTimeoutError:
        current = await page.evaluate(
            """({ sid }) => {
                const escaped = sid.replace(/\\./g, '\\\\.')
                const selectEl = document.querySelector(`dnt-select#${escaped}`)
                const input = selectEl?.shadowRoot
                    ?.querySelector('dnt-input')
                    ?.shadowRoot
                    ?.querySelector('input.dnt-input__inner')
                return (input?.value || '').trim()
            }""",
            {"sid": select_id},
        )
        mode = "fallback" if used_fallback else "heuristica"
        raise RuntimeError(
            f"Seleccion no valida en dnt-select#{select_id} via {mode}. "
            f"Objetivo='{option_text}' valor_actual='{current}'"
        ) from None
    await page.wait_for_timeout(FIELD_SETTLE_DELAY_MS)


async def _select_destination_organism(page: Page, organism_code: str, select_id: str) -> None:
    print(f"[REDSARA] Seleccionando organismo {organism_code} en #{select_id}...")
    focused = await page.evaluate(
        """({ sid }) => {
            const el = document.querySelector(`dnt-select#${sid}`)
            const input = el?.shadowRoot?.querySelector('dnt-input')
                ?.shadowRoot?.querySelector('input.dnt-input__inner')
            if (!input) return false
            input.click()
            input.focus()
            return true
        }""",
        {"sid": select_id},
    )
    if not focused:
        raise RuntimeError(f"No se pudo enfocar dnt-select#{select_id}")

    await page.wait_for_timeout(300)

    typed = await page.evaluate(
        """({ sid, code }) => {
            const el = document.querySelector(`dnt-select#${sid}`)
            const input = el?.shadowRoot?.querySelector('dnt-input')
                ?.shadowRoot?.querySelector('input.dnt-input__inner')
            if (!input) return false

            const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
            if (!nativeSetter) return false
            nativeSetter.call(input, code)

            input.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                composed: true,
                inputType: 'insertText',
                data: code
            }))
            input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, composed: true }))
            input.dispatchEvent(new Event('change', { bubbles: true, composed: true }))
            return true
        }""",
        {"sid": select_id, "code": organism_code},
    )
    if not typed:
        raise RuntimeError(f"No se pudo escribir en dnt-select#{select_id}")

    found = False
    for _ in range(40):
        found = await page.evaluate(
            """({ sid }) => {
                const el = document.querySelector(`dnt-select#${sid}`)
                const opts = el?.querySelectorAll('dnt-option')
                return (opts?.length ?? 0) > 0
            }""",
            {"sid": select_id},
        )
        if found:
            break
        await page.wait_for_timeout(250)

    if not found:
        raise RuntimeError(f"No aparecieron opciones en dnt-select#{select_id} tras escribir '{organism_code}'")

    clicked = await page.evaluate(
        """({ sid, code }) => {
            const el = document.querySelector(`dnt-select#${sid}`)
            let opt = el?.querySelector(`dnt-option[value="${code}"]`)
            if (!opt) opt = el?.querySelector('dnt-option')
            const div = opt?.shadowRoot?.querySelector('[role="option"]')
            if (!div) return false
            div.click()
            return true
        }""",
        {"sid": select_id, "code": organism_code},
    )
    if not clicked:
        raise RuntimeError(f"No se pudo clicar la opcion para organismo {organism_code}")

    await page.wait_for_function(
        """({ sid, code }) => {
            const el = document.querySelector(`dnt-select#${sid}`)
            return el?.value === code
        }""",
        arg={"sid": select_id, "code": organism_code},
        timeout=4000,
    )
    print(f"[REDSARA] Organismo {organism_code} seleccionado.")
    await page.wait_for_timeout(FIELD_SETTLE_DELAY_MS)


async def _select_representante(page: Page) -> None:
    print("[REDSARA] Seleccionando radio 'Representante'...")
    clicked = await page.evaluate(
        """() => {
            const radios = document.querySelectorAll('dnt-radio[name="typeRepresented"]')
            for (const radio of radios) {
                const label = radio.shadowRoot?.querySelector('label')
                const input = radio.shadowRoot?.querySelector('input[type="radio"]')
                if ((input?.value || '').toLowerCase() !== 'representante') continue
                if (!label || !input) continue
                label.click()
                input.dispatchEvent(new Event('input', { bubbles: true }))
                input.dispatchEvent(new Event('change', { bubbles: true }))
                return !!input.checked
            }
            return false
        }"""
    )
    if not clicked:
        raise RuntimeError("No se pudo marcar radio 'Representante'.")
    await page.wait_for_timeout(300)
    print("[REDSARA] Radio 'Representante' marcado.")


async def _set_checkbox(page: Page, form_control_name: str, should_check: bool) -> None:
    changed = await page.evaluate(
        """({ controlName, check }) => {
            const cb = document.querySelector(`dnt-checkbox[formcontrolname="${controlName}"]`)
            if (!cb) return false
            const input = cb.shadowRoot?.querySelector('input[type="checkbox"]')
            const label = cb.shadowRoot?.querySelector('label')
            if (!input || !label) return false
            if (input.checked === check) return true
            label.click()
            input.dispatchEvent(new Event('input', { bubbles: true }))
            input.dispatchEvent(new Event('change', { bubbles: true }))
            return input.checked === check
        }""",
        {"controlName": form_control_name, "check": should_check},
    )
    if not changed:
        raise RuntimeError(f"No se pudo cambiar checkbox formcontrolname='{form_control_name}'")
    print(f"[REDSARA] Checkbox {form_control_name}={should_check} OK.")
    await page.wait_for_timeout(FIELD_SETTLE_DELAY_MS)


async def rellenar_formulario_redsara(
    page: Page,
    config: RedsaraConfig,
    data: RedsaraTarget,
    *,
    prewarm_proc: subprocess.Popen | None = None,
) -> dict:
    await rellenar_paso1_datos_solicitante_redsara(page, config, data)

    # Next -> Step 2
    await _click_next_step1(page, config)

    # Step 2 - Organismo y datos de solicitud
    await _select_destination_organism(
        page,
        organism_code=data.destination_organism_code,
        select_id=config.selectors.destination_organism_id,
    )
    await _fill_input(page, config.selectors.subject_input, data.subject)
    await _fill_input(page, config.selectors.exposes_textarea, data.exposes)
    await _fill_input(page, config.selectors.solicit_textarea, data.solicit)

    # Step 3 - adjuntos reales
    await _click_next_step2(page, config)
    await _upload_files(page, config, data.archivos)

    # Paso final: avanzar, aceptar terminos y elegir firma con certificado.
    await _click_next_after_attachments(page)
    await _check_terms_checkbox(page)
    await _select_sign_with_certificate_option(page)
    if _env_flag("XALOC_REDSARA_PAUSE_BEFORE_SIGN", False):
        print("[REDSARA] Pausa antes de firma activada (XALOC_REDSARA_PAUSE_BEFORE_SIGN=1).")
        return {
            "redsara_paused_before_sign": True,
            "redsara_pause_url": page.url,
        }
    return await sign_with_proxy_and_download(
        page=page,
        data=data,
        download_fn=_download_justificante,
        resolve_path_fn=_resolve_client_justificante_path,
    )


async def rellenar_paso1_datos_solicitante_redsara(page: Page, config: RedsaraConfig, data: RedsaraTarget) -> None:
    await _wait_until_interactive(page)
    await _select_representante(page)

    # 1) Representative postal address
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.represented_street_type_id,
        option_text=data.represented_street_type,
        wait_for_options=True,
    )
    await _fill_dnt_input(page, "represented", "streetName", data.represented_address)
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.represented_country_id,
        option_text=get_default_country_es_ascii(),
    )
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.represented_province_id,
        option_text=normalize_province_alias(data.represented_province),
    )
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.represented_city_id,
        option_text=normalize_city_alias(data.represented_city),
        wait_for_options=True,
    )
    await _fill_dnt_input(page, "represented", "zipCode", data.represented_zip)
    await _fill_dnt_input(page, "represented", "phone", data.represented_phone)
    await _fill_dnt_input(page, "represented", "email", data.represented_email)

    # 3) Interested identification
    await _select_dnt_option_by_id(page, select_id=config.selectors.interested_doc_type_id, option_text=data.interested_doc_type)
    await _fill_dnt_input(page, "interested", "docNumber", data.interested_doc_number)

    is_empresa = bool(getattr(data, "interested_is_company", False)) or (
        (data.interested_doc_type or "").strip().upper() == "CIF"
    )

    if is_empresa:
        # Para empresas: razón social en businessName (name/surname/lastName no existen en DOM).
        await _fill_dnt_input(page, "interested", "businessName", data.interested_name)
    else:
        # Para personas físicas: nombre (solo pila), apellido1 y opcional apellido2.
        await _fill_dnt_input(page, "interested", "name", data.interested_name)
        await _fill_dnt_input(page, "interested", "surname", data.interested_surname1)
        # Nunca inventar apellido2: si no viene, no se rellena.
        if (data.interested_surname2 or "").strip():
            await _fill_dnt_input(page, "interested", "lastName", data.interested_surname2)

    # 4) Interested postal address
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.interested_street_type_id,
        option_text=data.interested_street_type,
        wait_for_options=True,
    )
    await _fill_dnt_input(page, "interested", "streetName", data.interested_address)
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.interested_province_id,
        option_text=normalize_province_alias(data.interested_province),
    )
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.interested_city_id,
        option_text=normalize_city_alias(data.interested_city),
        wait_for_options=True,
    )
    await _fill_dnt_input(page, "interested", "zipCode", data.interested_zip)
    await _fill_dnt_input(page, "interested", "phone", data.interested_phone)
    await _fill_dnt_input(page, "interested", "email", data.interested_email)

    # Communication preference checkbox (último punto antes de "Siguiente")
    await _set_checkbox(page, "emailAlert", data.email_alert)


