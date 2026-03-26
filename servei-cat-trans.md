# Documentación Playwright — Formulario "Presentar una alegació o recurs amb certificat digital" (gencat)




LA AUTOMATIZACION PARTE DE LA URL: https://transit.gencat.cat/es/gestions/multes-i-sancions/presentacio-escrits/

LUEGO se clica aqui: <a class="" title="Este enlace se abre en una nueva pestaña: Presentar alegaciones con certificado digital" target="_blank" href="https://ovt.gencat.cat/gsitgf/AppJava/traint/renderitzar.do?reqCode=inicial&amp;set-locale=es_ES&amp;idServei=TRN001SIGN&amp;urlRetorn=http://transit.gencat.cat/es/gestions/expedients_sancionadors/presentacio_d_escrits">
        <span class="list-group-item-wrapper-content">Presentar alegaciones con certificado digital</span>

	    

        
            <span class="sr-only">(Abre en pestaña nueva)</span>
        

    </a>





Esperamos a la redireccion a https://ovt.gencat.cat/gsitgf/AppJava/traint/renderitzar.do?reqCode=inicial&set-locale=es_ES&idServei=TRN001SIGN&urlRetorn=http://transit.gencat.cat/es/gestions/expedients_sancionadors/presentacio_d_escrits

Clicamos en <input type="button" class="btn btn-default bgRed white btn-form" onclick="location.href='/gsitgf/AppJava/traint/renderitzaruploadSecure.do?reqCode=autenticarFormulariHtml&amp;authMFA=false'" value="Acceder">

Nos redirige a valid.aoc.cat

Y ahi, como simepre clicamos en <button id="btnContinuaCert" data-testid="certificate-btn" data-toggle="modal" class="btn btn-opc btn-certificatDigital">
                          <span class="txt">Certificado digital:</span>
                      <span class="info">idCAT, DNIe ...</span>
                    </button>

Esperamos a la redireccion a https://ovt.gencat.cat/gsitgf/AppJava/traint/renderitzaruploadSecure.do?reqCode=autenticarFormulariHtml&authMFA=false


Clicamos en <a class="link_tramit" href="/gsitgf/AppJava/traint/renderitzaruploadSecure.do?reqCode=autenticarFormulariHtml&amp;presentador=P">
	                
	               		<div class="paper3">
	                		<p class="flex-container-space-between align-items">
				                
				            	
				            		<b>Actúo en nombre de la persona interesada (presentador/a)</b>
				            	
				                <img class="icono-link-presentador" alt="" src="/gsitgf/images/NG_ico_mes_consultat_tancar.png">
				            </p>
				    	</div>
		            </a>



**URL:** `https://ovt.gencat.cat/gsitgf/AppJava/traint/renderitzaruploadSecure.do?reqCode=autenticarFormulariHtml&presentador=P`

> El formulario requiere autenticación previa con certificado digital. Los datos de la sección "Datos de la persona que presenta la solicitud" (razón social, NIF empresa, nombre del representante, DNI) se auto-rellenan desde el certificado y **no deben sobrescribirse**.

---

## Requisitos previos

- Sesión activa con certificado digital (el navegador ya debe estar autenticado)
- Los archivos a adjuntar deben ser **.jpg o .pdf** (el formulario rechaza .txt y otros formatos)
- Los campos `Servicio Territorial`, `Expediente` y `Dígito de control` deben ser correctos para que el botón "Comprobar datos expediente" valide correctamente

---

## Estructura del formulario

1. **Código personal** — opcional, identificador libre del trámite
2. **Datos de la persona que presenta la solicitud** — auto-rellenado por el certificado (persona jurídica con representante)
3. **Datos del solicitante** — persona en cuyo nombre se presenta → **bifurcación física/jurídica**
4. **Notificaciones** — email y teléfono móvil para avisos
5. **Número de expediente** — Servicio Territorial + Expediente + Dígito de control → botón comprobar
6. **Tipo de escrito** — Escrito de alegaciones / Recurso potestativo de reposición / Recurso extraordinario de revisión
7. **EXPONGO y SOLICITO** — campos de texto libre
8. **Protección de datos** — checkbox obligatorio
9. **Documentación** — hasta 4 adjuntos opcionales + Acreditación de la representación (obligatorio si el solicitante es jurídica)

---

## Código Playwright completo

```typescript
import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// ═══════════════════════════════════════════════════════════════════
//  CONFIGURACIÓN — sustituir todos los valores YOUR_*
// ═══════════════════════════════════════════════════════════════════
const CONFIG = {

  codigoPersonal: '',   // opcional — nombre libre para identificar el trámite

  // ── Datos del presentador (representante del certificado) ──────────────
  // Solo se rellenan email, teléfono y dirección; el resto viene del cert.
  presentador: {
    email:         'info@xvia-serviciosjuridicos.com',
    telefonoMovil: '722761154',
    direccion: {
      tipoVia:      'RONDA',              // texto visible del select
      nombreVia:    'DEL GENERAL MITRE',
      numero:       '169',
      codigoPostal: '08022',
      comarca:      'BARCELONÈS',       // texto visible del select
      municipio:    'BARCELONA',  // texto visible del select
    },
  },

  // ── Datos del solicitante (representado) ───────────────────────────────
  solicitante: {
    tipoPerson: 'juridica' as 'fisica' | 'juridica',

    // Solo se usa cuando tipoPerson === 'fisica'
    fisica: {
      nombre:          'clientes.Nombre',
      primerApellido:  'clientes.Apellido1',
      segundoApellido: 'clientes.Apellido2 or '' ',                 // opcional
      tipoDocumento:   'DNI' as 'DNI' | 'NIE' | 'Pasaporte' | 'Documento de identidad extranjero', //se infiere segun el formato del nif
      nif:             'YOUR_NIF',
      email:           'info@xvia-serviciosjuridicos.com',
      telefonoMovil:   '722761154',                 // opcional
      direccion: {
        tipoVia:      '(se debe de inferir)',//podemos usar lo de inferir la calle con groq para toda la direccion
        nombreVia:    'YOUR_STREET_NAME',
        numero:       'YOUR_STREET_NUMBER',
        codigoPostal: 'YOUR_POSTAL_CODE',
        comarca:      'YOUR_COMARCA',
        municipio:    'YOUR_MUNICIPALITY',
      },
    },

    // Solo se usa cuando tipoPerson === 'juridica'
    juridica: {
      razonSocial:   'clientes.Nombrefiscal',
      tipoDocumento: 'NIF de empresa' as 'NIF de empresa' | 'Documento de identidad extranjero', //se infiere segun el formato del nif
      nifEmpresa:    'clientes.nifempresa',   // ej. B17600099
      representante: {
        nombre:          'clientes.Nombre',
        primerApellido:  'clientes.Apellido1',
        segundoApellido: 'clientes.Apellido2 or '' ',               // opcional
        tipoDocumento:   'DNI' as 'DNI' | 'NIE' | 'Pasaporte', //se infiere segun el formato del nif
        nif:             'clientes.nif',   // ej. 35081517P
        email:           'info@xvia-serviciosjuridicos.com',
        telefonoMovil:   '722761154',               // opcional
        direccion: {
          tipoVia:      '(se debe de inferir)', //podemos usar lo de inferir la calle con groq para toda la direccion
          nombreVia:    'YOUR_STREET_NAME',
          numero:       'YOUR_STREET_NUMBER',
          codigoPostal: 'YOUR_POSTAL_CODE',
          comarca:      'YOUR_COMARCA',
          municipio:    'YOUR_MUNICIPALITY',
        },
      },
    },
  },

  // ── Notificaciones ────────────────────────────────────────────────────
  notificaciones: {
    email:         'info@xvia-serviciosjuridicos.com',    // puede copiarse del solicitante
    telefonoMovil: '722761154',
  },

  // ── Número de expediente ──────────────────────────────────────────────
  //Aqui habra que parsear el expediente (tabla recursos.recursosExp columna Expedient) siempre tendra el formato ##/########-# o ##-########-#
  //Por tanto servicioTerritorial serian los 2 primeros ##, expediente seria los que siguen ######## y digitoControl el ultimo #
  expediente: {
    servicioTerritorial: 'YOUR_SERVICIO_TERRITORIAL',  // ej. 17
    expediente:          'YOUR_EXPEDIENTE',             // ej. 35104337
    digitoControl:       'YOUR_DIGITO_CONTROL',         // ej. 2
  },

  // ── Tipo de escrito y contenido ───────────────────────────────────────
  // Opciones: 'alegaciones' | 'reposicion' | 'revision'
  tipoEscrito: 'alegaciones' as 'alegaciones' | 'reposicion' | 'revision', //en funcion de la faseprocedimiento
  expongo:  'YOUR_EXPONGO_TEXT', //tambien en funcion de la fase
  solicito: 'YOUR_SOLICITO_TEXT',//tambien en funcion de la fase

  // ── Archivos adjuntos (rutas absolutas, formato .pdf o .jpg) ─────────
  //SACAMOS LA RUTA DEL CLIENTE y DE AHI LA DOCUMENTACIONs
  archivos: {
    doc1:         '/path/to/documento1.pdf',    // Documentación adicional 1 (opcional)
    doc2:         '/path/to/documento2.pdf',    // Documentación adicional 2 (opcional)
    doc3:         '',                           // Documentación adicional 3 (opcional)
    doc4:         '',                           // Documentación adicional 4 (opcional)
    acreditacion: '/path/to/acreditacion.pdf',  // Obligatorio si solicitante es jurídica (aqui la autorizacion)
  },
};

// ═══════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════

/** Selecciona una opción de un <select> por su texto visible usando JS,
 *  necesario para los selects de AEM Forms que no responden bien a
 *  Playwright selectOption en algunos casos. */
async function jsSelect(page: Page, elementId: string, optionText: string) {
  await page.evaluate(({ id, text }) => {
    const el = document.getElementById(id) as HTMLSelectElement;
    if (!el) throw new Error(`Select no encontrado: ${id}`);
    const opt = Array.from(el.options).find(o => o.text === text);
    if (!opt) throw new Error(`Opción no encontrada: "${text}" en ${id}`);
    el.value = opt.value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, { id: elementId, text: optionText });
}

/** Selecciona la comarca y espera a que el municipio cargue sus opciones. */
async function selectComarca(page: Page, baseAdrecaId: string, comarca: string) {
  await jsSelect(page, `${baseAdrecaId}-guidedropdownlist_2056216251___widget`, comarca);
  await page.waitForTimeout(500);
}

/** Selecciona el municipio. */
async function selectMunicipio(page: Page, baseAdrecaId: string, municipio: string) {
  await jsSelect(page, `${baseAdrecaId}-guidedropdownlist_988023112___widget`, municipio);
}

/** Rellena un bloque de dirección completo (tipo vía, nombre, número, CP, comarca, municipio). */
async function rellenarDireccion(
  page: Page,
  panelId: string,   // ID del panel de la calle  (panel_298747259)
  cpPanelId: string, // ID del panel del código postal (panel_1697806457)
  dir: typeof CONFIG.presentador.direccion,
) {
  await jsSelect(page, `${panelId}-guidedropdownlist___widget`, dir.tipoVia);
  await page.locator(`#${panelId}-guidetextbox___widget`).fill(dir.nombreVia);
  await page.locator(`#${panelId}-panel-guidetextbox___widget`).fill(dir.numero);

  await page.locator(`#${cpPanelId}-guidetextbox___widget`).fill(dir.codigoPostal);
  await page.keyboard.press('Tab');
  await page.waitForTimeout(1000); // esperar autocompletado provincia

  await selectComarca(page, cpPanelId, dir.comarca);
  await selectMunicipio(page, cpPanelId, dir.municipio);
}

/** Inyecta un archivo en un <input type="file"> de AEM Forms mediante DataTransfer,
 *  evitando el diálogo nativo del SO. */
async function injectFile(page: Page, inputId: string, filePath: string) {
  const content = fs.readFileSync(filePath);
  const base64  = content.toString('base64');
  const filename = path.basename(filePath);
  const mimeType = filename.endsWith('.pdf') ? 'application/pdf' : 'image/jpeg';

  await page.evaluate(({ inputId, base64, filename, mimeType }) => {
    const input = document.getElementById(inputId) as HTMLInputElement;
    if (!input) throw new Error(`Input file no encontrado: ${inputId}`);
    const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
    const blob  = new Blob([bytes], { type: mimeType });
    const file  = new File([blob], filename, { type: mimeType });
    const dt    = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, { inputId, base64, filename, mimeType });

  await page.waitForTimeout(1000);
}

// ═══════════════════════════════════════════════════════════════════
//  SECCIONES DEL FORMULARIO
// ═══════════════════════════════════════════════════════════════════

/** SECCIÓN 1 — Código personal (opcional) */
async function rellenarCodigoPersonal(page: Page) {
  if (!CONFIG.codigoPersonal) return;
  await page.locator('#codiPersonal-input').fill(CONFIG.codigoPersonal);
}

// ─────────────────────────────────────────────────────────────────
/** SECCIÓN 2 — Datos del presentador (persona jurídica con certificado).
 *  Solo se rellenan email, teléfono y dirección del representante;
 *  razón social, NIF empresa, nombre y DNI vienen del certificado. */
async function rellenarDatosPresentador(page: Page) {
  const BASE = 'guideContainer-rootPanel-seccio_presentador-personaJuridica-PJ';
  const REP  = `${BASE}-panel_21004007`;
  const DIR  = `guideContainer-rootPanel-seccio_presentador-personaJuridica-adreca-panel_298747259`;
  const CP   = `guideContainer-rootPanel-seccio_presentador-personaJuridica-adreca-panel_1697806457`;

  const p = CONFIG.presentador;

  // Email y teléfono del representante
  await page.locator(`#${REP}-panel-guidetextbox_31092572___widget`).fill(p.email);
  await page.locator(`#${REP}-panel-guidetextbox___widget`).fill(p.telefonoMovil);

  // Dirección
  await rellenarDireccion(page, DIR, CP, p.direccion);
}

// ─────────────────────────────────────────────────────────────────
/** SECCIÓN 3 — Datos del solicitante (bifurcación física / jurídica). */
async function rellenarDatosSolicitante(page: Page) {

  const RADIO_FISICA   = '#guideContainer-rootPanel-seccio_solicitant-tipusPersona-guideradiobutton__-1_widget';
  const RADIO_JURIDICA = '#guideContainer-rootPanel-seccio_solicitant-tipusPersona-guideradiobutton__-2_widget';

  // ── RAMA: Persona física ──────────────────────────────────────────────
  if (CONFIG.solicitante.tipoPerson === 'fisica') {
    await page.locator(RADIO_FISICA).check();  // value="particular"
    await page.waitForTimeout(500);

    const d   = CONFIG.solicitante.fisica;
    const PF  = 'guideContainer-rootPanel-seccio_solicitant-personaFisica-PF';
    const DIR = `${PF}-adreca-panel_298747259`;
    const CP  = `${PF}-adreca-panel_1697806457`;

    // Nombre y apellidos
    await page.locator(`#${PF}-panel-guidetextbox_897852897___widget`).fill(d.nombre);
    await page.locator(`#${PF}-panel-guidetextbox_1197861190___widget`).fill(d.primerApellido);
    if (d.segundoApellido) {
      await page.locator(`#${PF}-panel-guidetextbox___widget`).fill(d.segundoApellido);
    }

    // Tipo de documento + NIF
    // Opciones disponibles: DNI | NIE | Pasaporte | Documento de identidad extranjero
    await page.locator(`#${PF}-panel_1244233668-guidedropdownlist___widget`).selectOption({ label: d.tipoDocumento });
    await page.locator(`#${PF}-panel_1244233668-guidetextbox___widget`).fill(d.nif);
    await page.keyboard.press('Tab');
    await page.waitForTimeout(300);

    // Contacto
    await page.locator(`#${PF}-panel_1967475855-guidetextbox_31092572___widget`).fill(d.email);
    if (d.telefonoMovil) {
      await page.locator(`#${PF}-panel_1967475855-guidetextbox___widget`).fill(d.telefonoMovil);
    }

    // Dirección
    await rellenarDireccion(page, DIR, CP, d.direccion);

  // ── RAMA: Persona jurídica ────────────────────────────────────────────
  } else {
    await page.locator(RADIO_JURIDICA).check();  // value="on"
    await page.waitForTimeout(500);

    const d   = CONFIG.solicitante.juridica;
    const PJ  = 'guideContainer-rootPanel-seccio_solicitant-personaJuridica-PJ';
    const REP = `${PJ}-panel_21004007`;
    const DIR = `guideContainer-rootPanel-seccio_solicitant-personaJuridica-adreca-panel_298747259`;
    const CP  = `guideContainer-rootPanel-seccio_solicitant-personaJuridica-adreca-panel_1697806457`;

    // Razón social + tipo doc + NIF empresa
    // Opciones tipoDocumento: NIF de empresa | Documento de identidad extranjero
    await page.locator(`#${PJ}-panel-guidetextbox___widget`).fill(d.razonSocial);
    await page.locator(`#${PJ}-panel_1552294135-guidedropdownlist___widget`).selectOption({ label: d.tipoDocumento });
    await page.locator(`#${PJ}-panel_1552294135-guidetextbox___widget`).fill(d.nifEmpresa);
    await page.keyboard.press('Tab');
    await page.waitForTimeout(300);

    // Datos del representante de la empresa
    const r = d.representante;

    // Nombre y apellidos del representante
    await page.locator(`#${REP}-guidetextbox_8978528___widget`).fill(r.nombre);
    await page.locator(`#${REP}-guidetextbox_1197861___widget`).fill(r.primerApellido);
    if (r.segundoApellido) {
      await page.locator(`#${REP}-guidetextbox_1958877719___widget`).fill(r.segundoApellido);
    }

    // Tipo documento + NIF del representante
    // Opciones: DNI | NIE | Pasaporte | Documento de identidad extranjero
    await page.locator(`#${REP}-panel-guidedropdownlist___widget`).selectOption({ label: r.tipoDocumento });
    await page.locator(`#${REP}-panel-guidetextbox___widget`).fill(r.nif);
    await page.keyboard.press('Tab');
    await page.waitForTimeout(300);

    // Contacto del representante
    await page.locator(`#${REP}-panel-guidetextbox_31092572___widget`).fill(r.email);
    if (r.telefonoMovil) {
      await page.locator(`#${REP}-panel-guidetextbox_31092572___widget`).fill(r.telefonoMovil);
    }

    // Dirección del representante
    await rellenarDireccion(page, DIR, CP, r.direccion);
  }
}

// ─────────────────────────────────────────────────────────────────
/** SECCIÓN 4 — Notificaciones. */
async function rellenarNotificaciones(page: Page) {
  // El botón "Copiar datos de la persona solicitante" rellena email automáticamente
  await page.locator('button:has-text("de la persona solicitante")').click();
  await page.waitForTimeout(500);

  const n = CONFIG.notificaciones;

  // Email (si no se copió o se quiere sobrescribir)
  const emailInput = page.locator(
    '#guideContainer-rootPanel-seccio_declaracions-declaracionsText-guidetextbox_6143511_740763653___widget'
  );
  if (!(await emailInput.inputValue())) {
    await emailInput.fill(n.email);
  }

  // Teléfono móvil (obligatorio)
  await page.locator(
    '#guideContainer-rootPanel-seccio_declaracions-declaracionsText-guidetextbox_6143511___widget'
  ).fill(n.telefonoMovil);
}

// ─────────────────────────────────────────────────────────────────
/** SECCIÓN 5 — Número de expediente y verificación. */
async function rellenarExpediente(page: Page) {
  const e = CONFIG.expediente;
  const BASE = 'guideContainer-rootPanel-seccio_dadesParticulars-panel-panel-panel';

  await page.locator(`#${BASE}-guidetextbox___widget`).fill(e.servicioTerritorial);
  await page.locator(`#${BASE}-guidetextbox_5569220___widget`).fill(e.expediente);
  await page.locator(`#${BASE}-guidetextbox_1768694___widget`).fill(e.digitoControl);

  await page.locator('button:has-text("Comprobar datos expediente")').click();
  await page.waitForTimeout(3000);

  // Verificar que la validación fue correcta
  await expect(
    page.locator('text=Los datos del expediente son correctos')
  ).toBeVisible({ timeout: 10000 });
}

// ─────────────────────────────────────────────────────────────────
/** SECCIÓN 6 — Tipo de escrito + EXPONGO + SOLICITO. */
async function rellenarContenido(page: Page) {
  const BASE = 'guideContainer-rootPanel-seccio_dadesParticulars-panel-panel-panel_208485415';
  const TEXTO = 'guideContainer-rootPanel-seccio_dadesParticulars-panel-panel-panel_672934189-panel';

  // Seleccionar tipo de escrito
  const radioMap = {
    alegaciones: `#${BASE}-guideradiobutton__-1_widget`,
    reposicion:  `#${BASE}-guideradiobutton__-2_widget`,
    revision:    `#${BASE}-guideradiobutton__-3_widget`,
  };
  await page.locator(radioMap[CONFIG.tipoEscrito]).check();

  // EXPONGO y SOLICITO
  await page.locator(`#${TEXTO}-guidetextbox___widget`).fill(CONFIG.expongo);
  await page.locator(`#${TEXTO}-guidetextbox_641545334___widget`).fill(CONFIG.solicito);
}

// ─────────────────────────────────────────────────────────────────
/** SECCIÓN 7 — Protección de datos (checkbox obligatorio). */
async function aceptarProteccionDatos(page: Page) {
  await page.locator(
    '#guideContainer-rootPanel-seccio_protecciodade-GDPR-guidecheckbox___1_widget'
  ).check();
}

// ─────────────────────────────────────────────────────────────────
/** SECCIÓN 8 — Documentación adjunta.
 *
 *  Los IDs de los inputs tipo file siguen el patrón:
 *  GUID<timestamp>__guideContainer-rootPanel-seccio_adjunts-adjunts-panel-guidefileupload___widget
 *
 *  Los timestamps varían entre sesiones. La forma más robusta de localizarlos
 *  es por posición: el primer input file visible es doc1, el segundo doc2, etc.
 *  La alternativa (IDs hardcoded de la sesión actual) se incluye como comentario.
 */
async function subirDocumentacion(page: Page) {
  // Obtener todos los inputs file visibles en orden de aparición
  const fileInputIds: string[] = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('input[type="file"]'))
      .filter(el => (el as HTMLElement).offsetParent !== null)
      .map(el => el.id);
  });

  // El orden es: [mainUploader, doc1, doc2, doc3, doc4, acreditacion]
  // fileInputIds[0] es el uploader principal interno de AEM (accept=audio/*,video/*...)
  // fileInputIds[1..4] son Documentación adicional 1..4
  // fileInputIds[5] es Acreditación de la representación
  const slots = {
    doc1:         fileInputIds[1],
    doc2:         fileInputIds[2],
    doc3:         fileInputIds[3],
    doc4:         fileInputIds[4],
    acreditacion: fileInputIds[5],
  };

  const archivos = CONFIG.archivos;
  if (archivos.doc1 && slots.doc1)         await injectFile(page, slots.doc1, archivos.doc1);
  if (archivos.doc2 && slots.doc2)         await injectFile(page, slots.doc2, archivos.doc2);
  if (archivos.doc3 && slots.doc3)         await injectFile(page, slots.doc3, archivos.doc3);
  if (archivos.doc4 && slots.doc4)         await injectFile(page, slots.doc4, archivos.doc4);
  if (archivos.acreditacion && slots.acreditacion) {
    await injectFile(page, slots.acreditacion, archivos.acreditacion);
  }
}

// ═══════════════════════════════════════════════════════════════════
//  TEST PRINCIPAL
// ═══════════════════════════════════════════════════════════════════
test('Rellenar formulario alegación/recurso gencat', async ({ page }) => {

  const URL = 'https://ovt.gencat.cat/gsitgf/AppJava/traint/renderitzaruploadSecure.do'
            + '?reqCode=autenticarFormulariHtml&presentador=P';

  await page.goto(URL);
  await page.waitForLoadState('networkidle');

  await rellenarCodigoPersonal(page);
  await rellenarDatosPresentador(page);
  await rellenarDatosSolicitante(page);  // ← bifurcación física/jurídica aquí
  await rellenarNotificaciones(page);
  await rellenarExpediente(page);        // ← lanza la verificación contra el servidor
  await rellenarContenido(page);
  await aceptarProteccionDatos(page);
  await subirDocumentacion(page);

  // El formulario queda listo para que el usuario lo firme y envíe manualmente.
  console.log('✅ Formulario completado. Procede a firmar y enviar.');
});
```

---

## Notas de implementación

**Selectores de dirección.** Los selects de Provincia y Comarca dependen del código postal introducido; hay que hacer `Tab` y esperar ~1 segundo antes de intentar seleccionar comarca/municipio.

**IDs de los `input[type="file"]`.** Los IDs tienen un prefijo de timestamp (`GUID1774262656590__…`) que cambia entre sesiones. El helper `subirDocumentacion` los obtiene dinámicamente por orden de aparición en el DOM, que sí es estable.

**Validación del expediente.** El botón "Comprobar datos expediente" hace una llamada al servidor; si Servicio Territorial, Expediente o Dígito de control son incorrectos, el formulario no muestra las secciones de contenido (EXPONGO/SOLICITO) y el test fallará en el `expect`.

**Bifurcación física/jurídica.**

| | Persona física | Persona jurídica |
|---|---|---|
| Radio value | `particular` | `on` |
| Campos de identificación | Nombre + apellidos + DNI/NIE/Pasaporte | Razón social + NIF empresa + datos del representante |
| Documentos tipo | `DNI`, `NIE`, `Pasaporte`, `Documento de identidad extranjero` | `NIF de empresa`, `Documento de identidad extranjero` |
| Acreditación representación | No requerida | Obligatoria |

**Firma y envío.** El formulario no puede enviarse de forma automatizada porque requiere firma con certificado digital (DNI-e, FNMT, Camerfirma, etc.). El test deja el formulario relleno y el usuario debe hacer clic en "Firmar y enviar" manualmente.