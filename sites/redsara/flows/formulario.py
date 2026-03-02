from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.redsara.config import RedsaraConfig
from sites.redsara.data_models import RedsaraTarget
from sites.redsara.flows.select_heuristic import (
    HEURISTIC_MIN_SCORE,
    normalize_province_alias,
    select_option_heuristic_js,
    verify_selected_input_js,
)

FIELD_SETTLE_DELAY_MS = 180


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


def _ensure_test_pdf(path: Path) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 54>>stream\nBT /F1 14 Tf 40 80 Td (REDSARA TEST PDF) Tj ET\nendstream endobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000056 00000 n \n0000000113 00000 n \n0000000242 00000 n \n0000000346 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n416\n%%EOF\n"
    )
    path.write_bytes(pdf_bytes)
    return path


async def _upload_test_pdf(page: Page, config: RedsaraConfig) -> None:
    upload_path = _ensure_test_pdf(config.dir_screenshots / "redsara_test_upload.pdf")
    file_input = page.locator(config.selectors.attachments_input).first
    await file_input.wait_for(state="attached", timeout=15000)
    await file_input.set_input_files(str(upload_path))
    print(f"[REDSARA] PDF de prueba subido: {upload_path}")


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


async def rellenar_formulario_redsara(page: Page, config: RedsaraConfig, data: RedsaraTarget) -> None:
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

    # Step 3 - adjuntos (prueba)
    await _click_next_step2(page, config)
    await _upload_test_pdf(page, config)


async def rellenar_paso1_datos_solicitante_redsara(page: Page, config: RedsaraConfig, data: RedsaraTarget) -> None:
    await _wait_until_interactive(page)
    await _select_representante(page)

    # 1) Representative postal address
    await _select_dnt_option_by_id(page, select_id=config.selectors.represented_street_type_id, option_text=data.represented_street_type)
    await _fill_dnt_input(page, "represented", "streetName", data.represented_address)
    await _select_dnt_option_by_id(page, select_id=config.selectors.represented_country_id, option_text="ESPANA")
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.represented_province_id,
        option_text=normalize_province_alias(data.represented_province),
    )
    await _select_dnt_option_by_id(
        page, select_id=config.selectors.represented_city_id, option_text=data.represented_city, wait_for_options=True
    )
    await _fill_dnt_input(page, "represented", "zipCode", data.represented_zip)
    await _fill_dnt_input(page, "represented", "phone", data.represented_phone)
    await _fill_dnt_input(page, "represented", "email", data.represented_email)

    # 3) Interested identification
    await _select_dnt_option_by_id(page, select_id=config.selectors.interested_doc_type_id, option_text=data.interested_doc_type)
    await _fill_dnt_input(page, "interested", "docNumber", data.interested_doc_number)
    await _fill_dnt_input(page, "interested", "name", data.interested_name)
    await _fill_dnt_input(page, "interested", "surname", data.interested_surname1)
    await _fill_dnt_input(page, "interested", "lastName", data.interested_surname2)

    # 4) Interested postal address
    await _select_dnt_option_by_id(page, select_id=config.selectors.interested_street_type_id, option_text=data.interested_street_type)
    await _fill_dnt_input(page, "interested", "streetName", data.interested_address)
    await _select_dnt_option_by_id(
        page,
        select_id=config.selectors.interested_province_id,
        option_text=normalize_province_alias(data.interested_province),
    )
    await _select_dnt_option_by_id(
        page, select_id=config.selectors.interested_city_id, option_text=data.interested_city, wait_for_options=True
    )
    await _fill_dnt_input(page, "interested", "zipCode", data.interested_zip)
    await _fill_dnt_input(page, "interested", "phone", data.interested_phone)
    await _fill_dnt_input(page, "interested", "email", data.interested_email)

    # Communication preference checkbox (último punto antes de "Siguiente")
    await _set_checkbox(page, "emailAlert", data.email_alert)

