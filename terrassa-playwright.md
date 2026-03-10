
● He completado la exploración completa del tràmit. Aquí tienes el código Python con Playwright:

  ---
  Código Python Playwright — Terrassa Al·legació Multa de Trànsit

  Lo que descubrí durante la exploración

  Flujo real observado:
  1. Página inicial → clic "Ompliu el formulari"
  2. Si no hay sesión → página de identificació → Identifiqueu-vos → valid.aoc.cat → botón "Certificat digital" (tiene reCAPTCHA, el usuario debe seleccionar el certificado manualmente)
  3. Si hay sesión activa → va directo al formulario
  4. Clic "Vull actuar com a representant" → la página recarga con el formulario de Sol·licitant vacío
  5. Selección tipo doc + número + nombre (empresa) o nombre + 2 apellidos (físico)
  6. Campos de la multa: expedient, data, matrícula, marca
  7. Alegaciones + observaciones
  8. Subida de documentos: descripción → tipo → fichero → la página se recarga automáticamente y aparece una segunda sección
  9. Clic Continuar → Paso 2 revisión → se ve "SIGNAR EL TRÀMIT" → nos detenemos aquí

  Validaciones del formulario:
  - El CIF/NIF se valida en onblur mediante JS nativo → hay que usar datos reales válidos
  - La fecha acepta formato DD/MM/YYYY
  - Los documentos se suben mediante <iframe> interno (la página no recarga completamente, solo la sección de docs)

  ---
  import asyncio
  from pathlib import Path
  from playwright.async_api import async_playwright, Page


  # ──────────────────────────────────────────────────────────────────────────────
  # DATOS DEL TRÁMITE — rellenar con los valores reales
  # ──────────────────────────────────────────────────────────────────────────────
  TRAMIT_URL = "https://aoberta.terrassa.cat/tramits/fitxa.jsp?id=3822"

  # Sol·licitant (persona o empresa que recibe la multa)
  ES_EMPRESA = True          # True → CIF;  False → DNI/NIE/Passaport
  TIPUS_DOCUMENT = "CIF o entitats"  # opciones: "DNI / NIF", "NIE", "CIF o entitats",
                                     # "Passaport estranger", "Document d'identificació estranger",
                                     # "Doc. d'identificació jurídic estranger"
  NUM_DOCUMENT  = "B62798210"        # CIF/NIF/NIE real — el form valida onblur
  NOM_RAO_SOCIAL = "EMPRESA EXEMPLE SL"  # Empresa: razón social / Persona: nombre

  # Solo para persona física (ES_EMPRESA = False):
  PRIMER_COGNOM  = ""   # Primer apellido
  SEGON_COGNOM   = ""   # Segundo apellido (opcional)

  # Datos de la multa
  NUM_EXPEDIENT  = "R25V123456"   # Número de expediente de la multa
  DATA_INFRACTIO = "01/01/2025"   # Fecha infracción DD/MM/YYYY
  MATRICULA      = "1234ABC"
  MARCA_VEHICLE  = "Otros"        # siempre "Otros" porque no se suele tener el dato

  # Texto libre
  MOTIUS   = "Al·legació: el vehicle no es trobava en la ubicació indicada."
  OBSERV   = "S'adjunta documentació fotogràfica com a prova."

  # Documentos a adjuntar: lista de dicts con descripción, tipo y ruta del fichero
  # Tipos disponibles: "Al·legació", "Autorització", "Certificat", "Document Nacional Identitat - NIF",
  #   "Informe", "Justificant", "Notificació", "Poders notarials", ...
  DOCUMENTS = [
      {
          "descripcio": "Autoritzacio",
          "tipus": "Autorització",       # valor del <option> en el select
          "fitxer": Path("/ruta/al/fitxer/autoritzacio.pdf"),
      },
      {
          "descripcio": "Allegacio",
          "tipus": "Al·legació",
          "fitxer": Path("/ruta/al/fitxer/allegacio.pdf"),
      },
  ]
  # ──────────────────────────────────────────────────────────────────────────────


  async def esperar_formulari_o_identificacio(page: Page) -> str:
      """
      Tras clicar 'Ompliu el formulari', espera a que llegue o bien
      al formulario (URL contiene 'ferTramit') o bien a la página de
      identificación (URL contiene 'demanaIdentitat' o 'ferTramit' con
      el heading de 'verificació').
      Devuelve 'form' o 'auth'.
      """
      await page.wait_for_load_state("domcontentloaded")
      url = page.url
      # Si ya cargó el formulario directamente (sesión activa)
      if "ferTramit" in url and await page.locator("text=Vull actuar com a representant").count() > 0:
          return "form"
      # Si muestra la pantalla de verificació d'identitat
      if await page.locator("a[href='/demanaIdentitat']").count() > 0:
          return "auth"
      return "form"


  async def autenticar(page: Page):
      """
      Navega por el flujo de valid.aoc.cat hasta el selector de certificado.
      El usuario debe seleccionar el certificado manualmente en la ventana del SO.
      """
      # Clic en "Identifiqueu-vos"
      await page.click("a[href='/demanaIdentitat']")
      await page.wait_for_load_state("domcontentloaded")

      # Estamos en valid.aoc.cat — clic en "Certificat digital"
      # El botón puede estar disabled hasta que cargue reCAPTCHA;
      # esperamos hasta 20 s a que se habilite
      btn_cert = page.locator("button.btn-certificatDigital")
      await btn_cert.wait_for(state="visible", timeout=20_000)

      # Nota: el botón tiene data-callback="submitCertificat" con reCAPTCHA.
      # En la práctica, si reCAPTCHA bloquea el clic automatizado hay que
      # hacer clic manual. Intentamos el clic automático primero:
      await btn_cert.click()

      # Aquí el navegador abre el selector de certificados del SO.
      # El proceso no puede automatizarse: el usuario selecciona el certificado.
      print("\n[ACCION REQUERIDA] Selecciona el certificado digital en la ventana del sistema operativo.")
      print("Esperando hasta 120 s a que se complete la autenticación...\n")

      # Esperamos a que la URL vuelva a aoberta.terrassa.cat con el formulario
      await page.wait_for_url("**/ferTramit.jsp**", timeout=120_000)
      await page.wait_for_load_state("domcontentloaded")


  async def rellenar_solicitant(page: Page):
      """Rellena la sección Sol·licitant y hace clic en 'Vull actuar com a representant'."""

      # Clic en "Vull actuar com a representant"
      await page.click("a[href='/accions/identificaRepIntercanvi']")
      await page.wait_for_load_state("domcontentloaded")

      # Seleccionar tipo de documento
      await page.select_option("select#IDPersona_TD", label=TIPUS_DOCUMENT)

      # Número de documento (la validación onblur puede lanzar alert())
      await page.fill("input#IDPersona_ND", NUM_DOCUMENT)
      # Disparamos blur manualmente para que valide
      await page.evaluate("document.getElementById('IDPersona_ND').blur()")
      # Si aparece un alert de validación lo aceptamos (con datos reales no debería)
      try:
          await page.wait_for_event("dialog", timeout=2_000)
          # Si llega aquí es que hubo un alert de error — aceptarlo e informar
          raise ValueError(
              f"El número de documento '{NUM_DOCUMENT}' no pasó la validación del formulario. "
              "Revisa que sea un CIF/NIF/NIE válido."
          )
      except Exception as e:
          if "TimeoutError" not in str(type(e).__name__):
              raise

      # Nombre / Razón social
      await page.fill("input#nom", NOM_RAO_SOCIAL)
      await page.evaluate("document.getElementById('nom').blur()")

      # Solo para persona física
      if not ES_EMPRESA:
          await page.fill("input#cognom1", PRIMER_COGNOM)
          await page.evaluate("document.getElementById('cognom1').blur()")
          if SEGON_COGNOM:
              await page.fill("input#cognom2", SEGON_COGNOM)
              await page.evaluate("document.getElementById('cognom2').blur()")


  async def rellenar_dades_multa(page: Page):
      """Rellena los campos de datos de la multa."""
      await page.fill("input#_NUM_EXPEDIENT", NUM_EXPEDIENT)
      await page.evaluate("document.getElementById('_NUM_EXPEDIENT').blur()")

      await page.fill("input#_DATA_FET", DATA_INFRACTIO)
      await page.evaluate("document.getElementById('_DATA_FET').blur()")

      await page.fill("input#_MATRICULA", MATRICULA)
      await page.evaluate("document.getElementById('_MATRICULA').blur()")

      await page.fill("input#_MARCA", MARCA_VEHICLE)
      await page.evaluate("document.getElementById('_MARCA').blur()")

      await page.fill("textarea#_MOTIUS", MOTIUS)
      await page.fill("textarea#_OBSERV", OBSERV)


  async def subir_documento(page: Page, doc: dict, num: int):
      """
      Sube un documento al formulario.
      'num' indica qué upload section usar (1, 2, …).
      El form usa iframes internos; la page no recarga completamente,
      pero sí añade una nueva sección tras cada subida.
      """
      # Los campos de descripción y tipo del último bloque de subida
      # siempre son los últimos en el DOM con ese name
      desc_inputs = page.locator("input[name='descripcio']")
      tipo_selects = page.locator("select[name='tipologia_documental']")
      file_inputs = page.locator("input[type='file']")

      # Usamos el último de cada lista (el bloque recién aparecido)
      await desc_inputs.last.fill(doc["descripcio"])
      await tipo_selects.last.select_option(label=doc["tipus"])

      # Subida de fichero — playwright intercepta el file chooser
      async with page.expect_file_chooser() as fc_info:
          await file_inputs.last.click()
      file_chooser = await fc_info.value
      await file_chooser.set_files(str(doc["fitxer"]))

      # Esperamos a que aparezca el nombre del fichero en el DOM (confirmación)
      nombre_fichero = doc["fitxer"].name
      await page.wait_for_selector(
          f"text={nombre_fichero}",
          timeout=15_000
      )


  async def tramit_terrassa(headless: bool = False):
      async with async_playwright() as pw:
          browser = await pw.chromium.launch(headless=headless)
          context = await browser.new_context()
          page = await context.new_page()

          # Gestionar alerts de validación automáticamente
          page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

          # 1. Página inicial del tràmit
          await page.goto(TRAMIT_URL)
          await page.wait_for_load_state("domcontentloaded")

          # 2. Clic en "Ompliu el formulari"
          await page.click("a[href='/tramits/ferTramit.jsp?id=3822']")
          await page.wait_for_load_state("domcontentloaded")

          # 3. Autenticación si es necesaria
          estado = await esperar_formulari_o_identificacio(page)
          if estado == "auth":
              await autenticar(page)
          # Si ya hay sesión activa, continuamos directamente

          # 4. Sol·licitant + representant
          await rellenar_solicitant(page)

          # 5. Datos de la multa
          await rellenar_dades_multa(page)

          # 6. Documentos (mínimo 1, puede ser más)
          for i, doc in enumerate(DOCUMENTS, start=1):
              await subir_documento(page, doc, i)

          # 7. Continuar al paso 2 (revisión)
          await page.click("a:has-text('Continuar')")
          await page.wait_for_load_state("domcontentloaded")

          # ── FIN DEL TRÁMITE AUTOMATIZADO ──────────────────────────────────
          # En este punto estamos en "Pas 2 de 3: Repàs de les dades"
          # con el botón "SIGNAR EL TRÀMIT" visible.
          # NO hacemos clic en firmar — se deja para acción manual.
          print("\n[OK] Formulario completado. Estamos en el Pas 2 de revisión.")
          print(f"URL actual: {page.url}")
          print("El usuario puede revisar los datos y clicar 'Signar el tràmit' manualmente.")

          # Mantener el navegador abierto para revisión manual
          input("\nPulsa ENTER para cerrar el navegador...")
          await browser.close()


  if __name__ == "__main__":
      asyncio.run(tramit_terrassa(headless=False))

  ---
  Notas importantes para la automatización

  ┌──────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │       Aspecto        │                                                                                                    Detalle                                                                                                    │
  ├──────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Autenticación        │ El botón "Certificat digital" en valid.aoc.cat tiene reCAPTCHA. La selección del certificado es siempre manual (diálogo del SO).                                                                              │
  ├──────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Sesión persistente   │ Si guardas el storage_state con context.storage_state(path="session.json") y lo reutilizas con context = await browser.new_context(storage_state="session.json"), puedes omitir el paso de autenticación      │
  │                      │ mientras la sesión sea válida.                                                                                                                                                                                │
  ├──────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Validación CIF/NIF   │ El formulario valida onblur con JS. Con datos incorrectos muestra alert(). El código los acepta automáticamente pero lanza excepción para forzar el uso de datos reales.                                      │
  ├──────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Upload de documentos │ La subida usa un <iframe> interno (iframeUpload1). Playwright gestiona el file chooser correctamente con expect_file_chooser().                                                                               │
  ├──────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Segundo bloque de    │ Aparece automáticamente tras la primera subida exitosa. El código usa .last en los locators para apuntar siempre al último bloque disponible.                                                                 │
  │ docs                 │                                                                                                                                                                                                               │
  ├──────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Empresa vs           │ La diferencia es el selector #IDPersona_TD y los campos adicionales #cognom1 / #cognom2 solo para persona física.                                                                                             │
  │ particular           │                                                                                                                                                                                                               │
  └──────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
