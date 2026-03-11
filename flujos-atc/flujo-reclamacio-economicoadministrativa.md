  Mapa del formulario ATC Gencat - Reclamació Econòmicoadministrativa (REA)
  Flujo completo
  1. https://atc.gencat.cat/ca/gestions/impugnacions/
     └─ click link "Reclamació economicoadministrativa" → /ca/gestions/impugnacions/reclamacio/

  2. https://atc.gencat.cat/ca/gestions/impugnacions/reclamacio/
     └─ click link "Inicia el tràmit" (se abre en pestaña nueva, target="_blank")
        href=https://seu2.atc.gencat.cat/ca/secured/reas/identificacio
        class="tit"

  3. https://valid.aoc.cat/ (portal VALId - login)
     └─ click [data-testid="certificate-btn"] / id="btnContinuaCert"
        → redirige a https://seu2.atc.gencat.cat/ca/secured/reas/identificacio

  4. https://seu2.atc.gencat.cat/ca/secured/reas/identificacio
     ├─ radio "En nom d'una tercera persona" → click
     ├─ input #thirdPresenterNif   → fill <NIF/CIF del sujeto pasivo>
     ├─ input #thirdPresenterName  → fill <Raó social / Nom i cognoms>
     ├─ button "Validar"           → click (valida NIF contra censo ATC)
     ├─ checkbox declaració responsable → check
     └─ button "Continuar"         → click (habilitado tras validación + checkbox)
        → /ca/secured/reas/actes-impugnables

  5. https://seu2.atc.gencat.cat/ca/secured/reas/actes-impugnables
     ├─ (!) Modal informativo "Informació sobre la presentació d'una REA" aparece automàticament
     │    → button "Tancar" para cerrarlo
     ├─ textbox[placeholder="Introduïu el codi CSV​"] → fill <CSV del acto a reclamar>
     │    Formato: 20 chars alfanuméricos, CSV real y vigente
     ├─ button "Cercar" → click (se habilita al escribir en el campo)
     │    Si el CSV es válido: tarjeta con tipo acto, órgano y fecha notificación
     │    Si ya existe una REA previa sobre el mismo acto:
     │      → Modal "Atenció: Sobre l'acte seleccionat hi ha pendent la resolució..."
     │        button "Continuar" → click (confirmar igualmente)
     └─ button "Continuar" → click (habilitado tras CSV válido)
        → /ca/secured/reas/allegacions

  6. https://seu2.atc.gencat.cat/ca/secured/reas/allegacions
     Sección: "Al·legacions"
     ├─ textbox id="se-recurs-allegations-textarea" (maxlength=1000)
     │    → fill <texto de las alegaciones, obligatorio, máx 1.000 carácteres>
     │
     Sección: "Documentació que es presenta"
     ├─ Subida de hasta 10 documentos (máx 10 MB/doc, 25 MB total, PDF/DOC/DOCX/JPG)
     │    Para cada documento:
     │    a. click link "feu clic aquí" → abre file chooser
     │         input#se_upload_file_input (hidden)
     │    b. set_input_files(<ruta_archivo>)
     │    c. Modal "Documents adjunts":
     │         - combobox "IBAN (opc.)" → click button "dropdown trigger" → seleccionar opción:
     │             · "Al·legacions"
     │             · "Documentació acreditativa"
     │         - textbox "IBAN (opc.)" → fill <descripción libre> (opcional)
     │         - button "Adjuntar" → click (habilitado tras seleccionar tipo)
     │
     Sección: "Dades bancàries" → IGNORAR
     │
     └─ button "Continuar" (type="button") → click
        → /ca/secured/reas/tramitacio-notificacions

  7. https://seu2.atc.gencat.cat/ca/secured/reas/tramitacio-notificacions
     ├─ Muestra tribunal competente: Junta de Tributs de Catalunya
     ├─ Muestra dirección postal de notificación (la que consta a l'ATC)
     │    Opción: button "Modificar adreça postal" si se quiere cambiar
     └─ button "Continuar" (type="submit") → click
        → /ca/secured/reas/resum

  8. https://seu2.atc.gencat.cat/ca/secured/reas/resum
     ├─ Muestra resumen: acto impugnat, al·legacions, documentació, tribunal, notificació
     └─ button "Presentar" → ⛔ PARADA — NO clicar (requiere confirmación humana)


---
Diferències clau respecte al Recurs de Reposició

  · URL base del tràmit: /ca/secured/reas/  (REA)  vs  /ca/secured/recurs/  (Recurs)
  · El link "Inicia el tràmit" s'obre en pestanya nova (target="_blank") → cal canviar de tab
  · La pàgina d'actes-impugnables mostra un modal informatiu automàtic en entrar → tancar amb "Tancar"
  · La pàgina d'al·legacions té un camp de text obligatori d'al·legacions (1.000 caràcters màx)
    en lloc dels checkboxes de motiu del recurs
  · El dropdown de tipus de document té dues opcions: "Al·legacions" i "Documentació acreditativa"
    (el recurs de reposició solo tenia una: "Documentació acreditativa si escau")
  · Màxim 10 documents (vs 1 en el recurs)
  · La pàgina de tramitació/notificació informa del tribunal destinatari (Junta de Tributs)
    i mostra l'adreça postal de notificació (amb opció de modificar-la)


---
Código Playwright Python completo

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

ENTRY_URL  = "https://atc.gencat.cat/ca/gestions/impugnacions/"
TRAMIT_URL = "https://seu2.atc.gencat.cat/ca/secured/reas/"

# Datos del sujeto pasivo (tercera persona en cuyo nombre se actúa)
NIF_SUJETO_PASIVO  = "<NIF_CIF_del_obligado_tributario>"
RAZO_SOCIAL        = "<Razón social o nombre completo>"

# CSV del acto a reclamar (20 caracteres alfanuméricos, real y vigente)
CSV_ACTO           = "<CSV_ACTO_A_RECLAMAR>"

# Texto de las alegaciones (obligatorio, máx 1.000 carácteres)
ALLEGACIONS        = "<Motivos de la reclamación economicoadministrativa...>"

# Documentos a adjuntar: lista de (ruta, tipo, descripcion)
# tipo: "Al·legacions" | "Documentació acreditativa"
DOCUMENTS = [
    (Path("doc1.pdf"), "Al·legacions",            "Document principal d'al·legacions"),
    (Path("doc2.pdf"), "Documentació acreditativa", "Justificants de pagament"),
    (Path("doc3.pdf"), "Al·legacions",              "Annexos"),
]


# ─── HELPERS ──────────────────────────────────────────────────────────────────

async def login_certificat_digital(page: Page) -> None:
    """Hace clic en certificado digital en el portal VALId."""
    await page.wait_for_selector('[data-testid="certificate-btn"]', timeout=15000)
    await page.locator('[data-testid="certificate-btn"]').click()
    await page.wait_for_url("**/seu2.atc.gencat.cat/**", timeout=30000)


async def identificar_tercera_persona(page: Page, nif: str, razo_social: str) -> None:
    """Selecciona 'En nom d'una tercera persona', valida NIF y confirma."""
    await page.wait_for_url("**/identificacio**", timeout=15000)
    await page.get_by_role("radio", name="En nom d'una tercera persona").click()
    await page.locator("#thirdPresenterNif").fill(nif)
    await page.locator("#thirdPresenterName").fill(razo_social)
    await page.get_by_role("button", name="Validar").click()
    await page.wait_for_selector('button:has-text("Validat")', timeout=10000)
    await page.get_by_role("checkbox", name="Declaro sota la meva").check()
    await page.get_by_role("button", name="Continuar").click()
    await page.wait_for_url("**/actes-impugnables**", timeout=15000)


async def cercar_acte_per_csv(page: Page, csv: str) -> None:
    """
    Cierra el modal informativo automático, introduce el CSV y continúa.
    Acepta el modal de advertencia si ya existe una REA previa.
    """
    # Modal informativo automático → cerrar
    try:
        await page.wait_for_selector('button:has-text("Tancar")', timeout=5000)
        await page.get_by_role("button", name="Tancar").click()
    except Exception:
        pass  # No apareció modal informativo

    await page.get_by_placeholder("Introduïu el codi CSV").fill(csv)
    await page.get_by_role("button", name="Cercar").click()

    # Modal de advertencia REA previa → confirmar con "Continuar"
    try:
        await page.wait_for_selector('button[role="button"]:has-text("Continuar")', timeout=5000)
        # Hay dos botones Continuar posibles: el del modal y el de la página
        # El del modal está dentro del dialog
        dialog = page.locator('dialog, [role="dialog"]')
        await dialog.get_by_role("button", name="Continuar").click()
    except Exception:
        pass  # No apareció modal de advertencia

    # Esperar tarjeta del acto encontrado y clicar Continuar de la página
    await page.wait_for_selector('button:has-text("Continuar"):not([disabled])', timeout=10000)
    # Usar el último botón Continuar visible (el de la página, no modal)
    await page.get_by_role("button", name="Continuar").last.click()
    await page.wait_for_url("**/allegacions**", timeout=15000)


async def adjuntar_document(
    page: Page,
    doc_path: Path,
    tipus: str,
    descripcio: str = "",
) -> None:
    """
    Abre el file chooser, sube el documento y completa el modal de tipus+descripció.
    tipus: "Al·legacions" | "Documentació acreditativa"
    """
    async with page.expect_file_chooser() as fc_info:
        await page.get_by_role("link", name="feu clic aquí").click()
    file_chooser = await fc_info.value
    await file_chooser.set_files(str(doc_path))

    # Modal "Documents adjunts"
    await page.wait_for_selector('dialog', timeout=5000)
    await page.get_by_role("button", name="dropdown trigger").click()
    await page.get_by_role("option", name=tipus).click()
    if descripcio:
        await page.get_by_role("textbox", name="IBAN (opc.)").fill(descripcio)
    await page.get_by_role("button", name="Adjuntar").click()


async def omplir_allegacions_i_docs(
    page: Page,
    allegacions: str,
    documents: list[tuple[Path, str, str]],
) -> None:
    """
    Rellena el textarea de alegaciones, adjunta documentos e ignora datos bancarios.
    """
    # Textarea de alegaciones (obligatorio)
    await page.locator("#se-recurs-allegations-textarea").fill(allegacions)

    # Adjuntar documentos (máx 10)
    for doc_path, tipus, descripcio in documents[:10]:
        await adjuntar_document(page, doc_path, tipus, descripcio)

    # Ignorar "Dades bancàries"
    await page.get_by_role("button", name="Continuar").click()
    await page.wait_for_url("**/tramitacio-notificacions**", timeout=15000)


async def continuar_tramitacio(page: Page) -> None:
    """Página de tramitació/notificació → solo continuar."""
    await page.get_by_role("button", name="Continuar").click()
    await page.wait_for_url("**/resum**", timeout=15000)


# ─── FLUJO PRINCIPAL ──────────────────────────────────────────────────────────

async def presentar_reclamacio_economicoadministrativa(page: Page) -> None:
    """
    Flujo completo de la REA.
    Para justo antes del botón 'Presentar' (NO lo clica).
    El link "Inicia el tràmit" abre una pestaña nueva → usar context.expect_page().
    """

    # ── PASO 1: Navegar hasta "Inicia el tràmit" ──────────────────────────────
    await page.goto(ENTRY_URL)
    await page.get_by_role("link", name="Reclamació economicoadministrativa").click()

    # El link abre nueva pestaña
    context = page.context
    async with context.expect_page() as new_page_info:
        await page.get_by_role("link", name="Inicia el tràmit").click()
    new_page = await new_page_info.value
    await new_page.wait_for_load_state("networkidle")

    # ── PASO 2: Login VALId ───────────────────────────────────────────────────
    await login_certificat_digital(new_page)

    # ── PASO 3: Identificació tercera persona ─────────────────────────────────
    await identificar_tercera_persona(new_page, NIF_SUJETO_PASIVO, RAZO_SOCIAL)

    # ── PASO 4: CSV del acto ──────────────────────────────────────────────────
    await cercar_acte_per_csv(new_page, CSV_ACTO)

    # ── PASO 5: Al·legacions + documentació ──────────────────────────────────
    await omplir_allegacions_i_docs(new_page, ALLEGACIONS, DOCUMENTS)

    # ── PASO 6: Tramitació / notificacions ────────────────────────────────────
    await continuar_tramitacio(new_page)

    # ── PARADA: Resum amb botó "Presentar" ────────────────────────────────────
    # URL final: https://seu2.atc.gencat.cat/ca/secured/reas/resum
    # Botó present: role=button name="Presentar" (NO clicar)
    print("✓ REA llesta per presentar. Botó 'Presentar' visible. Revisió manual requerida.")
    print(f"  Tribunal destinatari: Junta de Tributs de Catalunya")


async def main():
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            "/ruta/al/perfil/chrome",
            headless=False,
            args=["--start-maximized"],
        )
        page = await context.new_page()
        await presentar_reclamacio_economicoadministrativa(page)
        input("Pulsa Enter para cerrar el navegador...")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())


---
Resumen de selectores y URLs

┌──────────────────────────────┬──────────────────────────────────────────────────────────────────┬──────────────┐
│           Campo              │                         Selector / URL                            │    Tipo      │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Pàgina d'impugnacions        │ https://atc.gencat.cat/ca/gestions/impugnacions/                  │ URL          │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Link "Reclamació..."         │ role=link name="Reclamació economicoadministrativa"               │ <a>          │
│                              │ class="distribuidora-item-link atc"                               │              │
│                              │ href=/ca/gestions/impugnacions/reclamacio/                        │              │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Link "Inicia el tràmit"      │ role=link name="Inicia el tràmit"  class="tit"  target="_blank"  │ <a>          │
│                              │ href=https://seu2.atc.gencat.cat/ca/secured/reas/identificacio    │              │
│                              │ ⚠ S'obre en PESTANYA NOVA → cal gestionar la nova pàgina         │              │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn certificat digital       │ [data-testid="certificate-btn"] / id="btnContinuaCert"            │ <button>     │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Radio tercera persona        │ role=radio name="En nom d'una tercera persona"                    │ <input radio>│
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ NIF sujeto pasivo            │ #thirdPresenterNif                                                │ <input text> │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Razón social                 │ #thirdPresenterName                                               │ <input text> │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Validar NIF              │ role=button name="Validar"                                        │ <button>     │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Checkbox declaració resp.    │ role=checkbox name="Declaro sota la meva responsabilitat..."      │ <input>      │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Modal info REA (automàtic)   │ role=button name="Tancar" (dins el dialog)                        │ <button>     │
│                              │ Apareix en entrar a actes-impugnables per 1a vegada               │              │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Input CSV                    │ placeholder="Introduïu el codi CSV​" / role=textbox               │ <input text> │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Cercar CSV               │ role=button name="Cercar"                                         │ <button>     │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Modal REA previa (opcional)  │ role=button name="Continuar" (dins el dialog d'"Atenció")         │ <button>     │
│                              │ Apareix si l'acte ja té una REA pendent                           │              │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Continuar (general)      │ role=button name="Continuar"                                      │ <button>     │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Textarea al·legacions        │ id="se-recurs-allegations-textarea" (maxlength=1000, obligatori)  │ <textarea>   │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Link subida doc.             │ role=link name="feu clic aquí"                                    │ <a>          │
│                              │ → abre file chooser; input#se_upload_file_input (hidden)          │              │
│                              │ Màxim 10 documents                                                │              │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Dropdown tipus document      │ role=button name="dropdown trigger" (dins el modal)               │ Angular sel. │
│                              │ Opcions: "Al·legacions" | "Documentació acreditativa"             │              │
│                              │ (2 opcions vs 1 en el recurs de reposició)                        │              │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Input descripció doc.        │ role=textbox name="IBAN (opc.)" (dins el modal, opcional)         │ <input text> │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Adjuntar                 │ role=button name="Adjuntar" (en modal)                            │ <button>     │
├──────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Presentar                │ role=button name="Presentar"  ⛔ NO CLICAR                        │ <button>     │
└──────────────────────────────┴──────────────────────────────────────────────────────────────────┴──────────────┘


Notas importantes

- El link "Inicia el tràmit" obre en PESTANYA NOVA (target="_blank"). Cal gestionar
  la nova pàgina amb context.expect_page() i treballar amb l'objecte new_page.

- En entrar a actes-impugnables s'obre AUTOMÀTICAMENT un modal informatiu sobre la REA.
  Cal tancar-lo amb button "Tancar" ABANS d'intentar escriure el CSV.

- Si l'acte ja té una REA pendent, apareix un modal d'"Atenció" que cal confirmar
  amb button "Continuar" (dins el dialog) per poder continuar igualment.

- El textarea d'al·legacions (id="se-recurs-allegations-textarea") és OBLIGATORI.
  Màxim 1.000 caràcters. Sense text, el botó "Continuar" no s'habilita.

- El dropdown de tipus de document té DUES opcions (diferència respecte al Recurs):
    · "Al·legacions"
    · "Documentació acreditativa"

- La descripció del document és OPCIONAL (el camp porta placeholder "IBAN (opc.)").
  Tot i que el label visible és "Descripció", el role és textbox name="IBAN (opc.)".

- La pàgina de tramitació/notificació informa que el tribunal destinatari és la
  "Junta de Tributs de Catalunya" i mostra l'adreça postal de notificació.

- URLs del flux:
    /ca/gestions/impugnacions/               → Entrada
    /ca/gestions/impugnacions/reclamacio/    → Info REA
    /ca/secured/reas/identificacio           → Identificació representat
    /ca/secured/reas/actes-impugnables       → CSV de l'acte
    /ca/secured/reas/allegacions             → Al·legacions + documentació
    /ca/secured/reas/tramitacio-notificacions → Tribunal + notificació postal
    /ca/secured/reas/resum                   → Resum + botó Presentar ⛔
