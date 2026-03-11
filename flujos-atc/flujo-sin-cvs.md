  Mapa del formulario ATC Gencat - Registro Electrónico                                                                 
  Flujo completo                                                                                                        
  1. https://atc.gencat.cat/es/gestions/registre-electronic/
     └─ click link → abre nueva pestaña

  2. https://valid.aoc.cat/  (portal VALId - login)
     ├─ id="btnContinuaCert" / class="btn btn-opc btn-certificatDigital"
     └─ click → redirige al formulario

  3. https://seu.atc.gencat.cat/es/OficinaVirtual/Paginas/TramitsGenerics.aspx
     └─ Formulario genérico ATC (todo el flujo a partir de aquí)

  ---
  Código Playwright Python completo

  import asyncio
  from pathlib import Path
  from playwright.async_api import async_playwright, Page

  # ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

  FORM_URL = "https://seu.atc.gencat.cat/es/OficinaVirtual/Paginas/TramitsGenerics.aspx"

  # Datos del formulario - parametrizar según caso real
  TIPO_TRAMITE    = "Aporte de documentos"        # combobox #tipusTramits
  TIPO_DOCUMENTO  = "Expediente"                  # combobox
  #MainContent_TramitsGenericsControl_ctlTipoDocument_SelectTipusDoc
  IMPUESTO        = "Impuesto sobre sucesiones y donaciones"  #
  #MainContent_TramitsGenericsControl_ctlTipoDocument_SelectTipusImpost
  NUM_DOCUMENTO   = "2025/12345/E"                # input #MainContent_TramitsGenericsControl_ctlTipoDocument_NumDoc

  EMAIL           = "gestor@empresa.com"          # input
  #MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxCorreo
  TELEFONO        = "600000000"                   # input
  #MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxTelefon

  NIF_INTERESADO  = "12345678Z"                   # input #MainContent_TramitsGenericsControl_ctlSubjectepassiu_Text1
  NOMBRE_INTERESADO = "APELLIDO1 APELLIDO2 NOMBRE" # input #MainContent_TramitsGenericsControl_ctlSubjectepassiu_Text2

  ORGANO          = "Oficina Central de Gestión Tributaria"  # combobox #tipusOrgans
  ASUNTO          = "Aportación de documentación requerida"  # textarea #txtAssumpteDesc

  # Lista de documentos a adjuntar: (ruta_archivo, descripcion, tipo_doc)
  # tipo_doc opciones: Alegación, Autoliquidación, Autorización, Certificado,
  #   Certificado de datos bancarios, Contrato, Documento notarial (Escritura),
  #   Fotografía, Informe, Justificante, Nota simple, Plano, Recibo, Renuncia,
  #   Representación, Resolución, Solicitud, Otros
  DOCUMENTOS = [
      (Path("doc1.pdf"), "Documentación principal", "Otros"),
      (Path("doc2.pdf"), "Justificante de pago",    "Justificante"),
  ]


  # ─── HELPERS ──────────────────────────────────────────────────────────────────

  async def accept_file_upload(page: Page, file_path: Path) -> None:
      """
      Mecanismo de subida de archivos del formulario ATC.
      Usa plUpload (Plupload library) con un input[type=file] oculto.

      Flujo:
        click #MainContent_TramitsGenericsControl_btnValidDocUpload  → abre dialog
        click button "Agregar Archivos"  → activa file chooser
        set_input_files(file_path)       → selecciona archivo
        click button "Subir."            → sube al servidor
        click button "Cerrar"            → cierra dialog, archivo aparece en tabla
      """
      # Abrir dialog de subida
      await page.locator("#MainContent_TramitsGenericsControl_btnValidDocUpload").click()
      await page.wait_for_selector('dialog[aria-label*="Enviar"], .ui-dialog:visible', timeout=5000)

      # Seleccionar archivo (file chooser)
      async with page.expect_file_chooser() as fc_info:
          await page.get_by_role("button", name="Agregar Archivos").click()
      file_chooser = await fc_info.value
      await file_chooser.set_files(str(file_path))

      # Subir
      await page.get_by_role("button", name="Subir.").click()
      # Esperar a que llegue al 100%
      await page.wait_for_function(
          "document.querySelector('.plupload_progress_bar') === null || "
          "document.querySelector('.plupload_progress_bar').style.width === '100%'",
          timeout=30000
      )

      # Cerrar dialog
      await page.get_by_role("button", name="Cerrar").click()


  # ─── FLUJO PRINCIPAL ──────────────────────────────────────────────────────────

  async def rellenar_formulario_atc(page: Page) -> None:
      """
      Rellena el formulario genérico de la ATC.
      Asume que ya estás autenticado y en FORM_URL.
      Para al llegar a 'Firmar y presentar' (NO lo clica).
      """

      # ── PASO 1: Trámite y referencia ──────────────────────────────────────────
      # Selector tipo trámite
      await page.locator("#tipusTramits").select_option(TIPO_TRAMITE)

      # Selector tipo documento
      await page.locator(
          "#MainContent_TramitsGenericsControl_ctlTipoDocument_SelectTipusDoc"
      ).select_option(TIPO_DOCUMENTO)

      # Selector impuesto (aparece dinámicamente según tipo trámite)
      await page.locator(
          "#MainContent_TramitsGenericsControl_ctlTipoDocument_SelectTipusImpost"
      ).select_option(IMPUESTO)

      # Número de documento
      await page.locator(
          "#MainContent_TramitsGenericsControl_ctlTipoDocument_NumDoc"
      ).fill(NUM_DOCUMENTO)

      # Botón Continuar (paso 1 → paso 2)
      await page.locator("#MainContent_TramitsGenericsControl_btnValidar").click()
      await page.wait_for_timeout(1000)  # esperar renderizado

      # ── PASO 2: Datos personales, órgano, asunto y documentos ─────────────────

      # Email y teléfono del presentador
      await page.locator(
          "#MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxCorreo"
      ).fill(EMAIL)
      await page.locator(
          "#MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxTelefon"
      ).fill(TELEFONO)

      # Datos del interesado (NIF + nombre)
      await page.locator(
          "#MainContent_TramitsGenericsControl_ctlSubjectepassiu_Text1"
      ).fill(NIF_INTERESADO)
      await page.locator(
          "#MainContent_TramitsGenericsControl_ctlSubjectepassiu_Text2"
      ).fill(NOMBRE_INTERESADO)

      # Órgano destinatario
      await page.locator("#tipusOrgans").select_option(ORGANO)

      # Asunto (textarea)
      await page.locator("#txtAssumpteDesc").fill(ASUNTO)

      # ── SUBIDA DE DOCUMENTOS ──────────────────────────────────────────────────
      # Máximo 5 documentos, máx 10 MB cada uno
      # Formatos: .pdf .txt .csv .xls .xlsx .doc .docx .odt .ods .gif .jpg .png
      for doc_path, _, _ in DOCUMENTOS:
          await accept_file_upload(page, doc_path)

      # Rellenar descripción y tipo de cada documento en la tabla
      for idx, (_, descripcion, tipo_doc) in enumerate(DOCUMENTOS, start=1):
          await page.locator(f"#inputAttach{idx}").fill(descripcion)
          await page.locator(f"#selectAttach-{idx}").select_option(tipo_doc)

      # ── VALIDAR → pantalla de resumen ─────────────────────────────────────────
      await page.locator("#MainContent_TramitsGenericsControl_btnValidar").click()
      await page.wait_for_selector(
          "#MainContent_TramitsGenericsControl_ctlSignature_btnFirmaBroker",
          timeout=10000
      )

      # ── PARADA: botón "Firmar y presentar" visible pero NO clicado ────────────
      # id = "MainContent_TramitsGenericsControl_ctlSignature_btnFirmaBroker"
      # class = "ui-button ui-widget ... ui-button-text-only"
      # <span class="ui-button-text">Firmar y presentar</span>
      print("✓ Formulario listo para firmar. Botón 'Firmar y presentar' visible.")
      print(f"  Selector: #MainContent_TramitsGenericsControl_ctlSignature_btnFirmaBroker")


  async def main():
      async with async_playwright() as pw:
          browser = await pw.chromium.launch(headless=False)
          context = await browser.new_context()

          # ── Autenticación con certificado digital ────────────────────────────
          # El certificado debe estar instalado en el sistema / perfil del navegador.
          # Si usas un perfil persistente con el cert ya cargado:
          # context = await pw.chromium.launch_persistent_context(
          #     "/ruta/al/perfil",
          #     headless=False,
          # )

          page = await context.new_page()

          # Ir a la página origen y hacer clic en "Inicia el tràmit"
          await page.goto("https://atc.gencat.cat/es/gestions/registre-electronic/")

          # El link abre nueva pestaña
          async with context.expect_page() as new_page_info:
              await page.locator(
                  "a[href='https://seu.atc.gencat.cat/es/OficinaVirtual/Paginas/TramitsGenerics.aspx']"
              ).click()
          form_page = await new_page_info.value
          await form_page.wait_for_load_state("networkidle")

          # ── Portal VALId - selección de certificado digital ──────────────────
          # El portal de login aparece en la nueva pestaña
          # Botón: id="btnContinuaCert", class="btn btn-opc btn-certificatDigital"
          await form_page.locator("#btnContinuaCert").click()
          # Aquí el navegador abre el selector nativo de certificados del SO.
          # En automatización real debes tener el certificado P12 importado
          # en el perfil del navegador o usar --client-certificate-path.
          await form_page.wait_for_url("**/TramitsGenerics.aspx**", timeout=30000)

          # ── Relleno del formulario ────────────────────────────────────────────
          await rellenar_formulario_atc(form_page)

          # Mantener abierto para revisión manual
          input("Pulsa Enter para cerrar el navegador...")
          await browser.close()


  if __name__ == "__main__":
      asyncio.run(main())

  ---
  Resumen de selectores (solo IDs/clases)

  ┌──────────────┬─────────────────────────────────────────────────────────────────────────────────────┬───────────┐
  │    Campo     │                                    Selector CSS                                     │   Tipo    │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Tipo trámite │ #tipusTramits                                                                       │ <select>  │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Tipo         │                                                                                     │           │
  │ documento    │ #MainContent_TramitsGenericsControl_ctlTipoDocument_SelectTipusDoc                  │ <select>  │
  │ referencia   │                                                                                     │           │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Impuesto (co │ #MainContent_TramitsGenericsControl_ctlTipoDocument_SelectTipusImpost               │ <select>  │
  │ ndicional)   │                                                                                     │           │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Número       │ #MainContent_TramitsGenericsControl_ctlTipoDocument_NumDoc                          │ <input    │
  │ documento    │                                                                                     │ text>     │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Btn          │                                                                                     │           │
  │ Continuar    │ #MainContent_TramitsGenericsControl_btnValidar                                      │ <button>  │
  │ (paso 1)     │                                                                                     │           │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Email        │ #MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxCorre │ <input    │
  │ presentador  │ o                                                                                   │ text>     │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Teléfono     │ #MainContent_TramitsGenericsControl_ctlDadesPersonBasicTramitsGenerics_TextBoxTelef │ <input    │
  │ presentador  │ on                                                                                  │ text>     │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ NIF          │ #MainContent_TramitsGenericsControl_ctlSubjectepassiu_Text1                         │ <input    │
  │ interesado   │                                                                                     │ text>     │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Nombre       │ #MainContent_TramitsGenericsControl_ctlSubjectepassiu_Text2                         │ <input    │
  │ interesado   │                                                                                     │ text>     │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Órgano       │ #tipusOrgans                                                                        │ <select>  │
  │ destinatario │                                                                                     │           │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Asunto       │ #txtAssumpteDesc                                                                    │ <textarea │
  │              │                                                                                     │ >         │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Btn Examinar │ #MainContent_TramitsGenericsControl_btnValidDocUpload                               │ <button>  │
  │  (ficheros)  │                                                                                     │           │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Input file   │ input[type=file] dentro del dialog                                                  │ <input    │
  │ (en dialog)  │                                                                                     │ file>     │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Descripción  │ #inputAttach{N} (N=1,2,3...)                                                        │ <input    │
  │ doc N        │                                                                                     │ text>     │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Tipo doc N   │ #selectAttach-{N} (N=1,2,3...)                                                      │ <select>  │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Btn Validar  │ #MainContent_TramitsGenericsControl_btnValidar                                      │ <button>  │
  │ (paso 2)     │                                                                                     │           │
  ├──────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────┤
  │ Firmar y     │ #MainContent_TramitsGenericsControl_ctlSignature_btnFirmaBroker                     │ <button>  │
  │ presentar    │                                                                                     │ ⛔        │
  └──────────────┴─────────────────────────────────────────────────────────────────────────────────────┴───────────┘

  Notas importantes

  - El campo "Impuesto" solo aparece cuando el "Tipo documento" es "Expediente" → hay que esperar a que renderice antes
  de intentar seleccionarlo
  - Subida de archivos: usa Plupload. El input[type=file] tiene ID dinámico — usar siempre el selector input[type=file]
  genérico. El flujo es: Examinar → Agregar Archivos → (file chooser) → Subir → Cerrar
  - Límite: máx 5 documentos, 10 MB/doc. Formatos: .pdf .txt .csv .xls .xlsx .doc .docx .odt .ods .gif .jpg .png
  - El formulario usa Knockout.js para bindings reactivos — algunos campos aparecen/desaparecen según selecciones
  previas
  - El botón "Continuar" en el paso 1 tiene id="MainContent_TramitsGenericsControl_btnValidar" (mismo ID que el
  "Validar" del paso 2)