  Mapa del formulario ATC Gencat - Recurs de Reposició
  Flujo completo
  1. https://atc.gencat.cat/ca/gestions/impugnacions/
     └─ click link "Recurs de reposició" → /ca/gestions/impugnacions/recurs/

  2. https://atc.gencat.cat/ca/gestions/impugnacions/recurs/
     └─ click link "Presentar recurs de reposició"
        → /ca/gestions/impugnacions/recurs/index.html?moda=1&detallId=<uuid>

  3. https://atc.gencat.cat/ca/gestions/impugnacions/recurs/index.html?moda=1&detallId=<uuid>
     ├─ click link "Per internet" (desplegable hiperDesple)
     └─ click link "Recurs de reposició. Inicia el tràmit"
        → https://seu2.atc.gencat.cat/ca/secured/recurs/

  4. https://valid.aoc.cat/ (portal VALId - login)
     └─ click button[data-testid="certificate-btn"] / id="btnContinuaCert"
        → redirige a https://seu2.atc.gencat.cat/ca/secured/recurs/identificacio

  5. https://seu2.atc.gencat.cat/ca/secured/recurs/identificacio
     ├─ radio "En nom d'una tercera persona" → click
     ├─ input #thirdPresenterNif   → fill <NIF/CIF del sujeto pasivo>
     ├─ input #thirdPresenterName  → fill <Raó social / Nom i cognoms>
     ├─ button "Validar"           → click (valida NIF contra censo; requiere dígito de control correcto)
     ├─ checkbox declaració responsable → check
     └─ button "Continuar"         → click (habilitado solo tras validación + checkbox)
        → /ca/secured/recurs/actes-impugnables

  6. https://seu2.atc.gencat.cat/ca/secured/recurs/actes-impugnables
     ├─ textbox[aria-label="CSV input"] → fill <CSV del acto a recurrir>
     │    Formato: 20 chars alfanuméricos (ej. XXXXXXXXXXXXXXXXXX20)
     │    Debe ser un CSV real y vigente; el sistema lo valida contra BD
     ├─ button "Cercar"   → click (se habilita al escribir en el campo)
     │    Si el CSV es válido: aparece tarjeta con tipo de acto, órgano y fecha de notificación
     │    Si el CSV no existe: se muestra modal de error → aceptar y reintentar
     └─ button "Continuar" → click (habilitado solo tras CSV válido encontrado)
        → /ca/secured/recurs/allegacions

  7. https://seu2.atc.gencat.cat/ca/secured/recurs/allegacions
     Sección: "Motiu de presentació del recurs"
     ├─ checkbox del motivo aplicable → check  (solo se puede marcar uno a la vez con expansión)
     │    Opciones disponibles:
     │      · Ha prescrit el dret a exigir el pagament.
     │      · He pagat el deute en període voluntari.
     │      · El procediment de recaptació ja estava suspès...
     │      · He presentat una sol·licitud d'ajornament o fraccionament...
     │      · No se m'ha notificat el deute en període de pagament voluntari.
     │      · No hi ha deute pendent, perquè s'ha anul·lat la liquidació...
     │      · Hi ha errors o manquen dades en la provisió de constrenyiment...
     │      · He presentat una sol·licitud de compensació...
     │      · Altres motius diferents dels anteriors.
     │
     ├─ (opcional) Subida de documento acreditativo:
     │    a. click link "feu clic aquí" → abre file chooser
     │    b. set_input_files(<ruta_pdf>)  → acepta PDF/DOC/DOCX/JPG, máx 10 MB, máx 1 doc
     │    c. Modal "Documents adjunts":
     │         - combobox "Tipus de document" → seleccionar opción
     │             (única opción visible: "Documentació acreditativa si escau")
     │         - textbox "Descripció" → fill <descripcion libre>
     │         - button "Adjuntar" → click (habilitado tras seleccionar tipo)
     │
     Sección: "Sol·licitud de suspensió"  → IGNORAR (no marcar)
     Sección: "Dades bancàries"           → IGNORAR (no rellenar)
     │
     └─ button "Continuar" → click
        → /ca/secured/recurs/notificacions

  8. https://seu2.atc.gencat.cat/ca/secured/recurs/notificacions
     ├─ Muestra aviso informativo (notificaciones via datos ATC)
     └─ button "Continuar" → click
        → /ca/secured/recurs/resum

  9. https://seu2.atc.gencat.cat/ca/secured/recurs/resum
     ├─ Muestra resumen completo: acto impugnado, motivo, documentación, notificaciones
     └─ button "Presentar" → ⛔ PARADA — NO clicar (requiere confirmación humana)


---
Código Playwright Python completo

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

ENTRY_URL   = "https://atc.gencat.cat/ca/gestions/impugnacions/"
TRAMIT_URL  = "https://seu2.atc.gencat.cat/ca/secured/recurs/"

# Datos del sujeto pasivo (tercera persona en cuyo nombre se actúa)
NIF_SUJETO_PASIVO  = "<NIF_CIF_del_obligado_tributario>"   # Con dígito de control válido
RAZO_SOCIAL        = "<Razón social o nombre completo>"

# CSV del acto a recurrir (20 caracteres alfanuméricos, real y vigente)
CSV_ACTO           = "<CSV_ACTO_A_RECURRIR>"

# Motivo del recurso (texto exacto del checkbox)
MOTIVO_RECURS      = "No se m'ha notificat el deute en període de pagament voluntari."

# Documento a adjuntar (opcional)
DOC_PATH           = Path("ruta/al/documento.pdf")
DOC_DESCRIPCION    = "<Descripción del documento>"


# ─── HELPERS ──────────────────────────────────────────────────────────────────

async def login_certificat_digital(page: Page) -> None:
    """
    Hace clic en el botón de certificado digital en el portal VALId.
    Asume que el certificado está instalado en el perfil del navegador.
    """
    await page.wait_for_selector('[data-testid="certificate-btn"]', timeout=15000)
    await page.locator('[data-testid="certificate-btn"]').click()
    await page.wait_for_url("**/seu2.atc.gencat.cat/**", timeout=30000)


async def identificar_tercera_persona(page: Page, nif: str, razo_social: str) -> None:
    """
    Selecciona 'En nom d'una tercera persona', rellena NIF y razón social,
    valida y confirma la declaración responsable.
    """
    await page.wait_for_url("**/identificacio**", timeout=15000)

    # Seleccionar radio "En nom d'una tercera persona"
    await page.get_by_role("radio", name="En nom d'una tercera persona").click()

    # Rellenar NIF y razón social
    await page.locator("#thirdPresenterNif").fill(nif)
    await page.locator("#thirdPresenterName").fill(razo_social)

    # Validar (el sistema comprueba el NIF contra censo)
    await page.get_by_role("button", name="Validar").click()
    await page.wait_for_selector('button:has-text("Validat")', timeout=10000)

    # Marcar declaración responsable
    await page.get_by_role("checkbox", name="Declaro sota la meva").check()

    # Continuar
    await page.get_by_role("button", name="Continuar").click()
    await page.wait_for_url("**/actes-impugnables**", timeout=15000)


async def cercar_acte_per_csv(page: Page, csv: str) -> None:
    """
    Introduce el CSV del acto a recurrir, lo busca y continúa.
    Lanza excepción si el CSV no es válido.
    """
    await page.get_by_role("textbox", name="CSV input").fill(csv)
    await page.get_by_role("button", name="Cercar").click()

    # Detectar si aparece modal de error
    try:
        await page.wait_for_selector('button:has-text("Acceptar")', timeout=5000)
        raise ValueError(f"CSV '{csv}' no encontrado o inválido en el sistema ATC.")
    except Exception as e:
        if "CSV" in str(e):
            raise
        # Sin modal de error → CSV válido, tarjeta mostrada

    await page.get_by_role("button", name="Continuar").click()
    await page.wait_for_url("**/allegacions**", timeout=15000)


async def seleccionar_motiu_i_adjuntar(
    page: Page,
    motivo: str,
    doc_path: Path | None = None,
    doc_descripcio: str = "",
) -> None:
    """
    Marca el motivo del recurso, adjunta documentación si se proporciona,
    ignora suspensión y datos bancarios, y continúa.
    """
    # Seleccionar motivo
    await page.get_by_role("checkbox", name=motivo).check()

    # Adjuntar documento (opcional)
    if doc_path and doc_path.exists():
        async with page.expect_file_chooser() as fc_info:
            await page.get_by_role("link", name="feu clic aquí").click()
        file_chooser = await fc_info.value
        await file_chooser.set_files(str(doc_path))

        # Modal "Documents adjunts": seleccionar tipo y descripción
        await page.wait_for_selector('dialog', timeout=5000)
        await page.get_by_role("button", name="dropdown trigger").click()
        await page.get_by_role("option").first.click()   # Única opción disponible
        await page.get_by_role("textbox", name="IBAN").fill(doc_descripcio)
        await page.get_by_role("button", name="Adjuntar").click()

    # Secciones "Sol·licitud de suspensió" y "Dades bancàries" → ignorar
    await page.get_by_role("button", name="Continuar").click()
    await page.wait_for_url("**/notificacions**", timeout=15000)


async def continuar_notificacions(page: Page) -> None:
    """Página informativa de notificaciones → solo continuar."""
    await page.get_by_role("button", name="Continuar").click()
    await page.wait_for_url("**/resum**", timeout=15000)


# ─── FLUJO PRINCIPAL ──────────────────────────────────────────────────────────

async def presentar_recurs_reposicio(page: Page) -> None:
    """
    Flujo completo del recurs de reposició.
    Para justo antes del botón 'Presentar' (NO lo clica).
    Requiere certificado digital instalado en el perfil del navegador.
    """

    # ── PASO 1: Navegar hasta "Inicia el tràmit" ──────────────────────────────
    await page.goto(ENTRY_URL)
    await page.get_by_role("link", name="Recurs de reposició").click()
    await page.get_by_role("link", name="Presentar recurs de reposició").click()
    await page.get_by_role("link", name="Per internet").click()
    await page.get_by_role("link", name="Recurs de reposició. Inicia el tràmit").click()

    # ── PASO 2: Login con certificado digital (portal VALId) ──────────────────
    await login_certificat_digital(page)

    # ── PASO 3: Identificación de la tercera persona ──────────────────────────
    await identificar_tercera_persona(page, NIF_SUJETO_PASIVO, RAZO_SOCIAL)

    # ── PASO 4: CSV del acto a recurrir ───────────────────────────────────────
    await cercar_acte_per_csv(page, CSV_ACTO)

    # ── PASO 5: Motivo + documentación ────────────────────────────────────────
    await seleccionar_motiu_i_adjuntar(
        page,
        motivo=MOTIVO_RECURS,
        doc_path=DOC_PATH,
        doc_descripcio=DOC_DESCRIPCION,
    )

    # ── PASO 6: Notificaciones ────────────────────────────────────────────────
    await continuar_notificacions(page)

    # ── PARADA: Página de Resum con botón "Presentar" visible ─────────────────
    # URL final: https://seu2.atc.gencat.cat/ca/secured/recurs/resum
    # Botón presente: role=button name="Presentar" (NO clicar)
    print("✓ Recurs llest per presentar. Botó 'Presentar' visible. Revisió manual requerida.")


async def main():
    async with async_playwright() as pw:
        # Usar perfil persistente con certificado ya importado
        context = await pw.chromium.launch_persistent_context(
            "/ruta/al/perfil/chrome",
            headless=False,
            args=["--start-maximized"],
        )
        page = await context.new_page()
        await presentar_recurs_reposicio(page)
        input("Pulsa Enter para cerrar el navegador...")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())


---
Resumen de selectores y URLs

┌─────────────────────────────┬──────────────────────────────────────────────────────────────────┬──────────────┐
│           Campo             │                          Selector / URL                           │    Tipo      │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Página de impugnaciones     │ https://atc.gencat.cat/ca/gestions/impugnacions/                  │ URL          │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Link "Recurs de reposició"  │ role=link name="Recurs de reposició"                              │ <a>          │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Link "Presentar recurs"     │ role=link name="Presentar recurs de reposició"                    │ <a>          │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Desplegable "Per internet"  │ role=link name="Per internet" / class="hiperDesple"               │ <a>          │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Link "Inicia el tràmit"     │ role=link name="Recurs de reposició. Inicia el tràmit"            │ <a>          │
│                             │ href=https://seu2.atc.gencat.cat/ca/secured/recurs/               │              │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn certificat digital      │ [data-testid="certificate-btn"] / id="btnContinuaCert"            │ <button>     │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Radio tercera persona       │ role=radio name="En nom d'una tercera persona"                    │ <input radio>│
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ NIF sujeto pasivo           │ #thirdPresenterNif                                                │ <input text> │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Razón social                │ #thirdPresenterName                                               │ <input text> │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Validar NIF             │ role=button name="Validar"                                        │ <button>     │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Checkbox declaració resp.   │ role=checkbox name="Declaro sota la meva responsabilitat..."      │ <input>      │
│                             │ class="checkbox-input" id="checkbox-declaracio-responsable_..."   │              │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Continuar (general)     │ role=button name="Continuar"                                      │ <button>     │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Input CSV                   │ role=textbox name="CSV input" / id="csvActInput"                  │ <input text> │
│                             │ Formato: 20 chars alfanuméricos, CSV real y vigente               │              │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Cercar CSV              │ role=button name="Cercar"                                         │ <button>     │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Checkboxes motiu recurs     │ role=checkbox name="<texto exacto del motivo>"                    │ <input>      │
│                             │ (9 opciones, ver lista en paso 7)                                 │              │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Link subida doc.            │ role=link name="feu clic aquí"                                    │ <a>          │
│                             │ → abre file chooser; input#se_upload_file_input (hidden)          │              │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Combobox tipo documento     │ role=combobox (en modal "Documents adjunts")                      │ Angular sel. │
│                             │ Única opción: "Documentació acreditativa si escau"                │              │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Input descripción doc.      │ role=textbox name="IBAN" (dentro del modal)                       │ <input text> │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Adjuntar                │ role=button name="Adjuntar" (en modal)                            │ <button>     │
├─────────────────────────────┼──────────────────────────────────────────────────────────────────┼──────────────┤
│ Btn Presentar               │ role=button name="Presentar"  ⛔ NO CLICAR                        │ <button>     │
└─────────────────────────────┴──────────────────────────────────────────────────────────────────┴──────────────┘


Notas importantes

- El NIF del sujeto pasivo requiere dígito de control correcto (CIF/NIF/NIE/pasaporte).
  El sistema valida el formato Y comprueba la existencia en el censo. Si el NIF no existe
  en el sistema ATC, el botón "Validar" no avanzará.

- El CSV debe ser real y vigente: debe corresponder a un acto notificado a la persona
  indicada como sujeto pasivo. El sistema valida contra su BD interna. Un CSV de formato
  correcto pero inexistente devuelve modal de error.

- El formulario es Angular (Angular SPA). Los elementos tienen atributos _ngcontent-ng-cXXX
  dinámicos; usar siempre selectores semánticos (role, name, id estable) en lugar de
  atributos Angular.

- Subida de archivos: máximo 1 documento en la sección del motivo. Formatos admitidos:
  PDF / DOC / DOCX / JPG. Tamaño máximo: 10 MB por documento, 25 MB total.

- Las secciones "Sol·licitud de suspensió" y "Dades bancàries" son opcionales y se ignoran
  si no aplican al caso.

- La autenticación se hace via certificado digital en el portal VALId (Consorci AOC).
  El certificado debe estar instalado en el perfil del navegador. En entornos Docker/headless,
  usar perfil persistente con el certificado P12 importado.

- URLs del flujo:
    /ca/gestions/impugnacions/              → Entrada
    /ca/gestions/impugnacions/recurs/       → Info recurs
    /ca/secured/recurs/identificacio        → Identificación representado
    /ca/secured/recurs/actes-impugnables    → CSV del acto
    /ca/secured/recurs/allegacions          → Motivo + documentación
    /ca/secured/recurs/notificacions        → Notificaciones (informativa)
    /ca/secured/recurs/resum                → Resumen + botón Presentar ⛔
