# Diputació BCN — Automatización `Presentmul`

URL real de entrada: `https://orgt.diba.cat/es/TramitsPagaments/Presentmul/presentmul`

> **Estado:** Mapeado hasta paso 3b. El paso 3b requiere subir doc acreditativa de representación (obligatorio).
> **Explorado con:** playwright-cli headed + certificado digital real (B62798210 / 35059210B).

---

## Código Python (Playwright)

```python
import asyncio
from playwright.async_api import async_playwright, Page

# ── Configuración ──────────────────────────────────────────────────────────────
URL_INICIAL = "https://orgt.diba.cat/es/TramitsPagaments/Presentmul/presentmul"

# Datos del representado — ajustar antes de ejecutar
TIPO_REPRESENTADO  = "fisica"          # "fisica" | "juridica"
NIF_INTERESSAT     = "00000000T"       # NIF/NIE válido (9 chars con letra de control)
NOM_CR4            = "Nom"             # Si física: nombre
COGNOM1            = "Cognom1"
COGNOM2            = "Cognom2"
NOM_JURIDICA       = "Empresa SL"      # Si jurídica: razón social

DOC_ACREDITATIVA   = "/ruta/poder_representacion.pdf"   # Obligatorio en paso 3b

MUNICIPIO          = "08019"           # value del select #MunicipisList
EXP_SANCIONADOR    = "2024/XXXX"
MATRICULA          = "1234ABC"
TELEFON            = "600000000"
EMAIL              = "notificacions@exemple.cat"
COMENTARI          = "Presentació documentació expedient sancionador"


async def run(playwright):
    # ── Navegador headed con perfil persistent (certificado) ──────────────────
    # El certificado debe estar instalado en el perfil o en el almacén de Windows.
    # Si se usa un perfil de Chrome existente, Chrome debe estar cerrado.
    browser = await playwright.chromium.launch_persistent_context(
        user_data_dir="/ruta/al/perfil/chromium",
        headless=False,
        args=["--start-maximized"],
    )
    page = browser.pages[0] if browser.pages else await browser.new_page()

    # ── 1. Acceso inicial ──────────────────────────────────────────────────────
    # NOTA: la URL sin /presentmul redirige a /Home/ajuda — usar la URL completa
    await page.goto(URL_INICIAL)

    # Aceptar cookies si aparecen
    cookie_btn = page.locator("button.cc-dismiss, button[aria-label='dismiss cookie message']")
    if await cookie_btn.count() > 0:
        await cookie_btn.first.click()

    # Botón "Acceder" en /Home/preidentificacio
    # NOTA: no es a.btn.btn-info.pull-left — es un generic div con cursor pointer
    await page.get_by_text("Acceder", exact=True).click()
    # → redirige a valid.aoc.cat/o/oauth2/...

    # ── 2. Autenticación AOC ───────────────────────────────────────────────────
    await page.wait_for_url("https://valid.aoc.cat/**")

    # 2.1 Click en "Certificat digital: idCAT, DNIe ..."
    # ID real: #btnContinuaCert (data-toggle="modal")
    await page.locator("#btnContinuaCert").click()
    # → El sistema pide seleccionar certificado (diálogo del navegador/SO)
    # → El usuario acepta manualmente (o se inyecta via clientCertificates en contexto)
    # → Redirige a /Home/representacioPas1juridica

    # ── 3. Rol de la persona identificada ─────────────────────────────────────
    # URL: /Home/representacioPas1juridica
    await page.wait_for_url("**/Home/representacioPas1juridica**")

    # 3.1 Seleccionar "Representante legal"
    await page.get_by_role("radio", name="Representante legal").click()

    # 3.2 Confirmar — aparece el botón tras seleccionar el radio
    await page.get_by_role("button", name="La entidad es representante de otra persona interesada").click()
    # → /Home/representacioPas2juridica

    # ── 4. Tipo de representado ────────────────────────────────────────────────
    # URL: /Home/representacioPas2juridica
    # La página muestra dos tabs (acordeón):
    #   #collapseFour → persona física
    #   #collapseFive → persona jurídica
    await page.wait_for_url("**/Home/representacioPas2juridica**")

    if TIPO_REPRESENTADO == "fisica":
        await _paso4_fisica(page)
    else:
        await _paso4_juridica(page)
    # → /Home/representacioPas3juridica

    # ── 3b. Documentación acreditativa de la representación ───────────────────
    # URL: /Home/representacioPas3juridica  ← PASO NO DOCUMENTADO ORIGINALMENTE
    # Obligatorio subir al menos un archivo (poder notarial, escritura, etc.)
    await page.wait_for_url("**/Home/representacioPas3juridica**")

    # Descripción del documento
    await page.locator("input[type='text']").first.fill("Poder de representación")

    # Subir archivo via botón "Navega..."
    async with page.expect_file_chooser() as fc_info:
        await page.get_by_role("button", name="Navega...").click()
    fc = await fc_info.value
    await fc.set_files(DOC_ACREDITATIVA)

    # Continuar
    await page.get_by_role("button", name="Continuar").click()
    # → siguiente paso (no mapeado aún)

    # ── 6. Descripción + subida de archivos del trámite ───────────────────────
    # TODO: mapear desde aquí
    await page.locator("#ComentFile").fill(COMENTARI)

    async with page.expect_file_chooser() as fc_info:
        await page.locator("#fakeBrowse").click()
    fc = await fc_info.value
    await fc.set_files("/ruta/documento_tramite.pdf")

    await page.locator("input[type='submit'][value='Continuar']").first.click()

    # ── 7. Datos de contacto ───────────────────────────────────────────────────
    await page.locator("#InfoMobil2").fill(TELEFON)
    await page.locator("#InfoMail2").fill(EMAIL)
    await page.locator("#uncheckNEPO2").click()
    await page.locator("input[type='submit'][value='Continuar']").first.click()

    # ── 8. Aceptación legal ────────────────────────────────────────────────────
    await page.locator("#LOPD").check()
    await page.locator("input[name='accio'][value='Acceder al trámite']").click()

    # ── 9. Datos del expediente ────────────────────────────────────────────────
    await page.locator("#MunicipisList").select_option(value=MUNICIPIO)
    await page.locator("#ExpSancionador").fill(EXP_SANCIONADOR)
    await page.locator("#Matricula").fill(MATRICULA)

    # TODO: submit final — flujo no mapeado más allá del paso 9


async def _paso4_fisica(page: Page):
    """Paso 4 persona física — abre tab #collapseFour y rellena campos."""
    # Abrir tab persona física
    await page.get_by_role("link", name="La entidad actúa en representación de una persona física").click()

    # Campos verificados con IDs reales:
    await page.locator("#nifcr4c").fill(NIF_INTERESSAT)        # name="identificadorInteressatCR4Rep"
    await page.locator("#nomcr4c").fill(NOM_CR4)               # name="nomInteressatCR4Rep_nom"
    await page.locator("#cognom1cr4c").fill(COGNOM1)           # name="nomInteressatCR4Rep_cognom1"
    await page.locator("#cognom2cr4c").fill(COGNOM2)           # name="nomInteressatCR4Rep_cognom2"

    # Botón Continuar dentro del tabpanel (no tiene name ni id — es el único en #collapseFour)
    await page.locator("#collapseFour").get_by_role("button", name="Continuar").click()


async def _paso4_juridica(page: Page):
    """Paso 4 persona jurídica — abre tab #collapseFive y rellena campos."""
    await page.get_by_role("link", name="La entidad actúa en representación de otra entidad").click()

    await page.locator("#identificadorInteressatCR5Rep").fill(NIF_INTERESSAT)
    await page.locator("#nomInteressatCR5Rep").fill(NOM_JURIDICA)

    await page.locator("#collapseFive").get_by_role("button", name="Continuar").click()


if __name__ == "__main__":
    async def main():
        async with async_playwright() as p:
            await run(p)
    asyncio.run(main())
```

---

## Flujo real (mapeado con headed + certificado)

| # | URL (parcial) | Título página | Acción | Selector real |
|---|---------------|---------------|--------|---------------|
| 1 | `/Home/preidentificacio` | Identificación | Click "Acceder" | `page.get_by_text("Acceder", exact=True)` |
| 2 | `valid.aoc.cat/...` | Inici de sessió amb VALId | Click certificado digital | `#btnContinuaCert` |
| 3 | `/Home/representacioPas1juridica` | Rol de la persona identificada | Radio "Representante legal" | `role=radio[name="Representante legal"]` |
| 3.2 | — | — | Click confirmar | `role=button[name="La entidad es representante..."]` |
| 4 | `/Home/representacioPas2juridica` | Datos de la persona interesada | Tab física o jurídica | `role=link[name="La entidad actúa en representación de una persona física..."]` |
| 4f | — | — | Campos física | `#nifcr4c`, `#nomcr4c`, `#cognom1cr4c`, `#cognom2cr4c` |
| 4j | — | — | Campos jurídica | `#identificadorInteressatCR5Rep`, `#nomInteressatCR5Rep` |
| 4.x | — | — | Continuar | `#collapseFour` o `#collapseFive` → `role=button[name="Continuar"]` |
| **3b** | `/Home/representacioPas3juridica` | **Documentación acreditativa** ⚠️ | Subir poder/escritura | `role=button[name="Navega..."]` |
| 3b.x | — | — | Continuar | `role=button[name="Continuar"]` |
| 6+ | (no mapeado) | — | Descripción + archivos trámite | `#ComentFile`, `#fakeBrowse` |

---

## Diferencias respecto al flujo original documentado

| Paso original | Selector original | Selector real |
|---------------|------------------|---------------|
| 1 Botón Acceder | `a.btn.btn-info.pull-left` | `page.get_by_text("Acceder", exact=True)` (div clickable) |
| 3.1 Tipo representación | `input#PersonaTipus2[value="L"]` | `role=radio[name="Representante legal"]` |
| 3.2 Confirmar | `input[type="submit"][name="a"]` | `role=button[name="La entidad es representante..."]` |
| 4.1 Persona física | `#CR4Rep` | Tab link → `role=link[name="La entidad actúa en representación de una persona física..."]` |
| 4.2 Persona jurídica | `#CR5Rep` | Tab link → `role=link[name="La entidad actúa en representación de otra entidad..."]` |
| — | (no existía) | **PASO 3b**: `/Home/representacioPas3juridica` — upload doc acreditativa (OBLIGATORIO) |

---

## Campos verificados (IDs reales)

### Persona física (#collapseFour)
| Campo | ID | name |
|-------|----|------|
| NIF/NIE | `#nifcr4c` | `identificadorInteressatCR4Rep` |
| Nombre | `#nomcr4c` | `nomInteressatCR4Rep_nom` |
| Apellido 1 | `#cognom1cr4c` | `nomInteressatCR4Rep_cognom1` |
| Apellido 2 | `#cognom2cr4c` | `nomInteressatCR4Rep_cognom2` |
| Continuar | (sin id) | (sin name) — `type=submit` dentro de `#collapseFour` |

### Persona jurídica (#collapseFive)
| Campo | ID | name |
|-------|----|------|
| NIF entidad | `#identificadorInteressatCR5Rep` | `identificadorInteressatCR5Rep` |
| Razón social | `#nomInteressatCR5Rep` | `nomInteressatCR5Rep` |
| Continuar | (sin id) | (sin name) — `type=submit` dentro de `#collapseFive` |

---

## Notas de implementación

- **Perfil persistent:** necesario para tener el certificado disponible. Chrome debe estar cerrado al lanzar Playwright con su perfil.
- **Certificado en headed:** el diálogo de selección de certificado es nativo del navegador — solo visible en headed mode. En automatización desatendida, usar `clientCertificates` de Playwright (v1.46+).
- **Validación NIF:** el servidor rechaza NIFs con formato incorrecto. Usar NIFs reales o computar la letra de control correctamente.
- **Paso 3b es OBLIGATORIO:** no se puede continuar sin subir al menos una doc acreditativa. El trámite queda "en revisión" hasta que el ORGT la valida.
- **Botón "Continuar" duplicado:** usar `.locator("#collapseFour").get_by_role(...)` para evitar ambigüedad.
- **TODO:** mapear pasos 6 en adelante (`#ComentFile`, `#fakeBrowse`, contacto, LOPD, expediente). Los selectores del documento original son plausibles pero no verificados.

## Continuacion tras "Continuar" (hasta correo)

Despues de `representacioPas3juridica` y pulsar `Continuar`:

1. **Pantalla de documentacion del tramite**
- Rellenar comentario: `#ComentFile`
- Subir fichero del tramite: click `#fakeBrowse` + `file_chooser.set_files(...)`
- Pulsar continuar: `input[type='submit'][value='Continuar']`

2. **Pantalla de contacto**
- Telefono: `#InfoMobil2`
- Correo electronico: `#InfoMail2`
- Opcional desmarcar aviso: `#uncheckNEPO2`
- Pulsar continuar: `input[type='submit'][value='Continuar']`

Este punto deja el flujo justo despues de introducir correo/telefono, antes de LOPD y acceso final al tramite.
