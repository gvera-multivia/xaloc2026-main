"""
Script de investigación del flujo de Diputació de Barcelona (ORGT).
Navega headless=False para permitir autenticación con certificado digital.
Investiga los elementos de formulario en cada paso problemático.

Uso:
    python scripts/investigate_diputacio_bcn.py

El script se pausa en la pantalla de login de valid.aoc.cat para que puedas
autenticarte con tu certificado. Después continúa automáticamente.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# ─── headless SIEMPRE False ────────────────────────────────────────────────────
HEADLESS = False  # NUNCA cambiar a True
# ───────────────────────────────────────────────────────────────────────────────

BASE_URL = "https://orgt.diba.cat/es/TramitsPagaments/Presentmul/presentmul?NouTramit=True"
SCREENSHOTS_DIR = Path(__file__).parent.parent / ".tmp" / "investigate_diputacio_bcn"


def _banner(msg: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {msg}")
    print(f"{'='*70}")


async def _dump_form_elements(page, label: str) -> None:
    """Imprime todos los campos de formulario encontrados en la página."""
    _banner(f"ELEMENTOS DE FORMULARIO — {label}")
    result = await page.evaluate("""() => {
        const fields = [];

        // inputs
        document.querySelectorAll('input').forEach(el => {
            fields.push({
                tag: 'input',
                type: el.type || '?',
                id: el.id || '',
                name: el.name || '',
                placeholder: el.placeholder || '',
                value: el.value || '',
                disabled: el.disabled,
                hidden: el.style.display === 'none' || el.type === 'hidden',
                classes: el.className || '',
            });
        });

        // textareas
        document.querySelectorAll('textarea').forEach(el => {
            fields.push({
                tag: 'textarea',
                type: 'textarea',
                id: el.id || '',
                name: el.name || '',
                placeholder: el.placeholder || '',
                value: el.value || '',
                disabled: el.disabled,
                hidden: el.style.display === 'none',
                classes: el.className || '',
            });
        });

        // buttons & submits
        document.querySelectorAll('button, input[type="submit"], input[type="button"]').forEach(el => {
            fields.push({
                tag: el.tagName.toLowerCase(),
                type: el.type || '?',
                id: el.id || '',
                name: el.name || '',
                text: (el.textContent || el.value || '').trim().slice(0, 80),
                disabled: el.disabled,
                classes: el.className || '',
            });
        });

        // labels
        document.querySelectorAll('label').forEach(el => {
            fields.push({
                tag: 'label',
                forAttr: el.htmlFor || '',
                text: (el.textContent || '').trim().slice(0, 60),
            });
        });

        // divs/spans con IDs relevantes
        document.querySelectorAll('[id*="Browse"], [id*="browse"], [id*="upload"], [id*="file"], [id*="File"], [id*="Coment"], [id*="coment"]').forEach(el => {
            fields.push({
                tag: el.tagName.toLowerCase(),
                id: el.id || '',
                classes: el.className || '',
                text: (el.textContent || '').trim().slice(0, 60),
                role: el.getAttribute('role') || '',
            });
        });

        return fields;
    }""")

    for f in result:
        print(json.dumps(f, ensure_ascii=False))


async def _screenshot(page, name: str) -> None:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOTS_DIR / f"{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"  [screenshot] {path}")


async def _wait_for_url_contains(page, fragments: list[str], timeout_ms: int = 300000) -> str:
    """Espera hasta que la URL contenga alguno de los fragmentos dados."""
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        url = page.url
        for frag in fragments:
            if frag in url:
                return url
        await page.wait_for_timeout(500)
    raise TimeoutError(f"Timeout esperando URL con {fragments}. URL actual: {page.url}")


async def investigate() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,  # SIEMPRE False
            args=["--start-maximized"],
        )
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()

        # ── 1. Navegar al tramit ────────────────────────────────────────────────
        _banner("PASO 1: Navegando al tramit")
        await page.goto(BASE_URL, wait_until="domcontentloaded")
        print(f"  URL actual: {page.url}")

        # Cerrar cookies si aparece
        try:
            cookie_btn = page.locator("button.cc-dismiss, button[aria-label='dismiss cookie message'], button:has-text('De acuerdo')")
            if await cookie_btn.count() > 0:
                await cookie_btn.first.click()
                print("  [ok] Cookies dismissadas")
        except Exception:
            pass

        # Click Acceder / Accedir
        try:
            trigger = page.locator(
                "a.btn.btn-info.pull-left[value='Accedir'], "
                "a.btn.btn-info.pull-left:has-text('Acceder'), "
                "a.btn.btn-info.pull-left:has-text('Accedir')"
            ).first
            if await trigger.count() > 0:
                await trigger.wait_for(state="visible", timeout=10000)
                await trigger.click()
                print("  [ok] Click en botón Acceder/Accedir (btn-info)")
            else:
                # Alternativa: botón genérico de Acceder
                btn = page.get_by_text("Acceder", exact=True).first
                if await btn.count() == 0:
                    btn = page.get_by_text("Accedir", exact=True).first
                await btn.wait_for(state="visible", timeout=10000)
                await btn.click()
                print("  [ok] Click en Acceder/Accedir (texto)")
        except Exception as e:
            print(f"  [warn] No se encontró botón Acceder: {e}")

        # ── 2. Esperar que el usuario navegue a la página con #ComentFile ─────────
        _banner("PASO 2: NAVEGA A LA PÁGINA CON #ComentFile")
        print("  El navegador está abierto.")
        print("  Navega manualmente hasta llegar a la página con el campo 'Descripció'.")
        print("  Cuando estés en esa página, pulsa ENTER aquí en el terminal.")
        print()
        await asyncio.get_event_loop().run_in_executor(None, input, "  >>> Pulsa ENTER cuando estés en la página con #ComentFile: ")
        print(f"  [ok] Continuando — URL: {page.url}")

        # ── 3. Investigar directamente la página actual ────────────────────────
        _banner(f"PASO 3: INVESTIGANDO PÁGINA ACTUAL — {page.url}")
        await _dump_form_elements(page, "Página actual")
        await _screenshot(page, "03_pagina_actual")

        # ── Investigación específica de #ComentFile ───────────────────────────
        print("\n--- INVESTIGACIÓN: #ComentFile ---")
        coment_info = await page.evaluate("""() => {
            const el = document.querySelector('#ComentFile') || document.querySelector('input[name="ComentFile"]');
            if (!el) return { found: false };
            return {
                found: true,
                tag: el.tagName,
                type: el.type || '',
                id: el.id,
                name: el.name,
                value: el.value,
                disabled: el.disabled,
                readOnly: el.readOnly,
                maxLength: el.maxLength,
                display: window.getComputedStyle(el).display,
                visibility: window.getComputedStyle(el).visibility,
                offsetParent: el.offsetParent !== null,
                parentId: el.parentElement?.id || '',
                parentClass: el.parentElement?.className || '',
                attrs: Array.from(el.attributes).map(a => a.name + '=' + a.value),
            };
        }""")
        print(f"  #ComentFile info: {json.dumps(coment_info, ensure_ascii=False)}")

        if coment_info.get("found"):
            test_text = "Poder de representacion"
            coment_loc = page.locator("#ComentFile").first

            # Método 1: fill()
            try:
                await coment_loc.fill(test_text)
                val = await coment_loc.input_value()
                print(f"  [MÉTODO 1 fill()] valor tras fill: '{val}'")
            except Exception as e:
                print(f"  [MÉTODO 1 fill()] ERROR: {e}")

            # Método 2: triple-click + type
            try:
                await coment_loc.click(click_count=3)
                await coment_loc.press_sequentially(test_text, delay=30)
                val = await coment_loc.input_value()
                print(f"  [MÉTODO 2 press_sequentially()] valor: '{val}'")
            except Exception as e:
                print(f"  [MÉTODO 2 press_sequentially()] ERROR: {e}")

            # Método 3: native setter JS
            try:
                await page.evaluate("""(txt) => {
                    const el = document.querySelector('#ComentFile');
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(el, txt);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""", test_text)
                val = await coment_loc.input_value()
                print(f"  [MÉTODO 3 native setter] valor: '{val}'")
            except Exception as e:
                print(f"  [MÉTODO 3 native setter] ERROR: {e}")

            await _screenshot(page, "04_despues_fill")
            print("\n  >>> MIRA EL NAVEGADOR: ¿aparece el texto en el campo Descripció?")
        else:
            print("  [WARN] #ComentFile NO encontrado en esta página")

        # ── Pausa para observar ───────────────────────────────────────────────
        await asyncio.get_event_loop().run_in_executor(None, input, "\n  >>> Pulsa ENTER para cerrar el navegador: ")

        if False and "representacioPas1juridica" in page.url or "representacio" in page.url:
            _banner("PASO 3: representacioPas1juridica")
            await _screenshot(page, "01_pas1juridica")
            await _dump_form_elements(page, "Pas1Juridica")

            # Hacer click en "Representante legal"
            try:
                radio = page.get_by_role("radio", name="Representante legal")
                if await radio.count() > 0:
                    await radio.click()
                    print("  [ok] Radio 'Representante legal' seleccionado")
                    btn = page.get_by_role("button", name="La entidad es representante de otra persona interesada")
                    await btn.wait_for(state="visible", timeout=10000)
                    await btn.click()
                    print("  [ok] Botón 'La entidad es representante...' pulsado")
                else:
                    print("  [warn] No encontrado radio 'Representante legal'")
            except Exception as e:
                print(f"  [warn] Paso1 error: {e}")

        # ── 4. Paso representacioPas2juridica ──────────────────────────────────
        try:
            await _wait_for_url_contains(page, ["representacioPas2juridica"], timeout_ms=30000)
            _banner("PASO 4: representacioPas2juridica")
            await _screenshot(page, "02_pas2juridica")
            await _dump_form_elements(page, "Pas2Juridica")

            # Seleccionar persona física (default)
            try:
                link_fisica = page.get_by_role("link", name="La entidad actúa en representación de una persona física")
                if await link_fisica.count() > 0:
                    await link_fisica.click()
                    print("  [ok] Seleccionada representación de persona física")
                    # Rellenar NIF/nom/cognom con datos de prueba
                    await page.locator("#nifcr4c").fill("00000000T")
                    await page.locator("#nomcr4c").fill("NomTest")
                    await page.locator("#cognom1cr4c").fill("Cognom1Test")
                    await page.locator("#cognom2cr4c").fill("Cognom2Test")
                    await page.locator("#collapseFour").get_by_role("button", name="Continuar").click()
                    print("  [ok] Formulario física rellenado y Continuar pulsado")
                else:
                    print("  [warn] No encontrado link de persona física")
            except Exception as e:
                print(f"  [warn] Paso2 error: {e}")
        except TimeoutError:
            print("  [skip] representacioPas2juridica no apareció, continuando...")

        # ── 5. Paso representacioPas3juridica ─────────────────────────────────
        try:
            await _wait_for_url_contains(page, ["representacioPas3juridica"], timeout_ms=30000)
            _banner("PASO 5: representacioPas3juridica *** PASO PROBLEMÁTICO ***")
            await page.wait_for_load_state("networkidle", timeout=10000)
            await _screenshot(page, "03_pas3juridica_BEFORE")
            await _dump_form_elements(page, "Pas3Juridica — ANTES de interacción")

            # ── Investigación detallada del campo texto ─────────────────────
            print("\n--- INVESTIGACIÓN: campo de texto ---")
            text_fields = await page.evaluate("""() => {
                const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type]), textarea'));
                return inputs.map(el => ({
                    tag: el.tagName,
                    id: el.id,
                    name: el.name,
                    class: el.className,
                    placeholder: el.placeholder || '',
                    value: el.value,
                    visible: el.offsetParent !== null,
                    disabled: el.disabled,
                    readonly: el.readOnly,
                    parentId: el.parentElement?.id || '',
                    parentClass: el.parentElement?.className || '',
                }));
            }""")
            for f in text_fields:
                print(f"  TEXT FIELD: {json.dumps(f, ensure_ascii=False)}")

            # ── Investigación detallada del botón de subida ─────────────────
            print("\n--- INVESTIGACIÓN: botones de subida de archivo ---")
            upload_btns = await page.evaluate("""() => {
                const results = [];
                // Botones/links con texto de subida
                document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]').forEach(el => {
                    const txt = (el.textContent || el.value || '').trim();
                    if (txt) results.push({
                        tag: el.tagName,
                        id: el.id || '',
                        text: txt.slice(0, 80),
                        class: el.className || '',
                        type: el.type || '',
                    });
                });
                // Inputs file
                document.querySelectorAll('input[type="file"]').forEach(el => {
                    results.push({
                        tag: 'INPUT[file]',
                        id: el.id || '',
                        name: el.name || '',
                        accept: el.accept || '',
                        class: el.className || '',
                        display: window.getComputedStyle(el).display,
                        visibility: window.getComputedStyle(el).visibility,
                    });
                });
                return results;
            }""")
            for f in upload_btns:
                print(f"  UPLOAD/BTN: {json.dumps(f, ensure_ascii=False)}")

            # ── Intentar rellenar el texto ──────────────────────────────────
            print("\n--- INTENTO: rellenar campo texto ---")
            test_text = "Poder de representacion test"
            # Intento 1: locator genérico
            txt_input = page.locator("input[type='text']").first
            count = await txt_input.count()
            print(f"  input[type='text'] count: {count}")
            if count > 0:
                try:
                    await txt_input.fill(test_text)
                    val = await txt_input.input_value()
                    print(f"  [ok] fill() → valor actual: '{val}'")
                except Exception as e:
                    print(f"  [error] fill() falló: {e}")

            await _screenshot(page, "04_pas3juridica_AFTER_fill")

            # ── Investigar botón de subida archivo ─────────────────────────
            print("\n--- INTENTO: detectar botón Navega.../Examinar/Seleccionar ---")
            for name_candidate in ["Navega...", "Navegar...", "Examinar", "Seleccionar archivo", "Browse", "Adjuntar"]:
                btn = page.get_by_role("button", name=name_candidate)
                c = await btn.count()
                if c > 0:
                    print(f"  [ENCONTRADO] get_by_role('button', name='{name_candidate}') → count={c}")
                else:
                    print(f"  [no encontrado] '{name_candidate}'")

            # Buscar por texto parcial en cualquier elemento clickable
            partial_matches = await page.evaluate("""() => {
                const clickable = Array.from(document.querySelectorAll('button, a, label, [role="button"]'));
                return clickable
                    .filter(el => /naveg|examin|selecci|browse|adjunt/i.test(el.textContent || ''))
                    .map(el => ({
                        tag: el.tagName,
                        id: el.id || '',
                        text: (el.textContent || '').trim().slice(0, 80),
                        class: el.className || '',
                        for: el.htmlFor || '',
                    }));
            }""")
            print("  Coincidencias parciales (naveg/examin/selecci/browse/adjunt):")
            for m in partial_matches:
                print(f"    {json.dumps(m, ensure_ascii=False)}")

        except TimeoutError:
            print("  [skip] representacioPas3juridica no apareció")

        # ── 6. Página de documentos ────────────────────────────────────────────
        try:
            await _wait_for_url_contains(
                page,
                ["Presentmul", "documentos", "Document", "fakeBrowse", "ComentFile"],
                timeout_ms=60000,
            )
        except TimeoutError:
            pass

        # Esperar que aparezca #fakeBrowse o #ComentFile
        try:
            await page.locator("#fakeBrowse, #ComentFile").first.wait_for(state="visible", timeout=30000)
            _banner("PASO 6: PÁGINA DE DOCUMENTOS *** PASO PROBLEMÁTICO ***")
            await page.wait_for_load_state("networkidle", timeout=10000)
            await _screenshot(page, "05_documentos_BEFORE")
            await _dump_form_elements(page, "Documentos — ANTES de interacción")

            # ── Investigación #ComentFile ───────────────────────────────────
            print("\n--- INVESTIGACIÓN: #ComentFile ---")
            coment_info = await page.evaluate("""() => {
                const el = document.querySelector('#ComentFile') || document.querySelector('input[name="ComentFile"]');
                if (!el) return { found: false };
                return {
                    found: true,
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id,
                    name: el.name,
                    value: el.value,
                    disabled: el.disabled,
                    readOnly: el.readOnly,
                    maxLength: el.maxLength,
                    display: window.getComputedStyle(el).display,
                    visibility: window.getComputedStyle(el).visibility,
                    offsetParent: el.offsetParent !== null,
                    hasNgModel: el.hasAttribute('ng-model') || el.hasAttribute('[(ngModel)]') || el.hasAttribute('formControlName'),
                    attrs: Array.from(el.attributes).map(a => `${a.name}="${a.value}"`),
                };
            }""")
            print(f"  #ComentFile: {json.dumps(coment_info, ensure_ascii=False)}")

            # Intentar fill
            coment = page.locator("#ComentFile, input[name='ComentFile']").first
            test_comment = "Presentacio documentacio expedient TEST"
            try:
                await coment.fill(test_comment)
                val_after = await coment.input_value()
                print(f"  [ok] fill() → valor: '{val_after}'")
                # Disparar eventos
                await page.evaluate("""(val) => {
                    const el = document.querySelector('#ComentFile') || document.querySelector('input[name="ComentFile"]');
                    if (!el) return;
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }""", test_comment)
                val_after_events = await coment.input_value()
                print(f"  [ok] después de events → valor: '{val_after_events}'")
                if not val_after_events.strip():
                    print("  [PROBLEMA] El valor se borró tras los eventos — framework sobreescribe el campo")
            except Exception as e:
                print(f"  [error] fill() ComentFile falló: {e}")

            # ── Investigación #fakeBrowse ───────────────────────────────────
            print("\n--- INVESTIGACIÓN: #fakeBrowse ---")
            browse_info = await page.evaluate("""() => {
                const el = document.querySelector('#fakeBrowse');
                if (!el) return { found: false };
                return {
                    found: true,
                    tag: el.tagName,
                    id: el.id,
                    type: el.type || '',
                    text: (el.textContent || el.value || '').trim().slice(0, 80),
                    class: el.className,
                    onclick: el.getAttribute('onclick') || '',
                    href: el.getAttribute('href') || '',
                    display: window.getComputedStyle(el).display,
                    cursor: window.getComputedStyle(el).cursor,
                    // buscar el input file asociado
                    relatedFile: (() => {
                        const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
                        return inputs.map(f => ({
                            id: f.id, name: f.name, display: window.getComputedStyle(f).display,
                            visibility: window.getComputedStyle(f).visibility, accept: f.accept,
                        }));
                    })(),
                };
            }""")
            print(f"  #fakeBrowse: {json.dumps(browse_info, ensure_ascii=False)}")

            # Verificar si hay input file oculto y si tiene display:none
            file_inputs = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('input[type="file"]')).map(el => ({
                    id: el.id, name: el.name,
                    display: window.getComputedStyle(el).display,
                    visibility: window.getComputedStyle(el).visibility,
                    opacity: window.getComputedStyle(el).opacity,
                    width: window.getComputedStyle(el).width,
                    height: window.getComputedStyle(el).height,
                    position: window.getComputedStyle(el).position,
                    accept: el.accept || '',
                    multiple: el.multiple,
                }));
            }""")
            print("\n  Input[type=file] encontrados:")
            for fi in file_inputs:
                print(f"    {json.dumps(fi, ensure_ascii=False)}")

            # Intentar click en #fakeBrowse y ver si abre file chooser
            print("\n--- INTENTO: click en #fakeBrowse con expect_file_chooser ---")
            browse_el = page.locator("#fakeBrowse").first
            if await browse_el.count() > 0:
                try:
                    async with page.expect_file_chooser(timeout=5000) as fc_info:
                        await browse_el.click(force=True)
                    fc = await fc_info.value
                    print(f"  [FUNCIONA] expect_file_chooser capturado → isMultiple={fc.is_multiple}")
                except Exception as e:
                    print(f"  [PROBLEMA] expect_file_chooser falló: {e}")
                    # Intentar set_input_files directamente en el input[type='file']
                    print("  Probando set_input_files en input[type='file'] oculto...")
                    for fi in file_inputs:
                        fi_el = page.locator(f"input[type='file']#{fi['id']}" if fi['id'] else "input[type='file']").first
                        try:
                            await fi_el.set_input_files([], timeout=3000)  # vaciar para probar
                            print(f"    [ok] set_input_files funciona en #{fi['id']}")
                        except Exception as e2:
                            print(f"    [error] set_input_files falló en #{fi['id']}: {e2}")

            await _screenshot(page, "06_documentos_AFTER_investigation")

            # ── Botón Continuar ─────────────────────────────────────────────
            print("\n--- INVESTIGACIÓN: botón Continuar ---")
            submit_info = await page.evaluate("""() => {
                const candidates = [
                    ...Array.from(document.querySelectorAll('input[type="submit"]')),
                    ...Array.from(document.querySelectorAll('button[type="submit"]')),
                    ...Array.from(document.querySelectorAll('button')),
                ];
                return candidates
                    .filter(el => /continu/i.test(el.value || el.textContent || ''))
                    .map(el => ({
                        tag: el.tagName, type: el.type, id: el.id,
                        value: el.value || '', text: (el.textContent || '').trim().slice(0, 60),
                        disabled: el.disabled, class: el.className,
                    }));
            }""")
            print(f"  Botones 'Continuar': {json.dumps(submit_info, ensure_ascii=False)}")

        except Exception as e:
            print(f"  [skip] Página documentos no apareció o error: {e}")
            await _screenshot(page, "06_documentos_error")

        # ── Final ──────────────────────────────────────────────────────────────
        _banner("INVESTIGACIÓN COMPLETA")
        print("  Screenshots guardados en:", SCREENSHOTS_DIR)
        print("  El navegador permanece abierto para inspección manual.")
        print("  Pulsa ENTER aquí para cerrarlo...")
        input()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(investigate())
