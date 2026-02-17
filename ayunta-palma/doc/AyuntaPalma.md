Para que un modelo de IA o un sistema de automatización basado en lenguaje natural entienda exactamente qué hacer con esa página de la Sede Electrónica de Palma, el prompt debe ser muy específico sobre la jerarquía de los elementos y el comportamiento asíncrono (el hecho de que el login aparece en un modal después de cargar la página).
Aquí tienes un prompt detallado y estructurado que puedes usar para que Playwright (o un asistente que genere código) entienda la tarea a la perfección:

Prompt de Configuración y Acción
Contexto de la página:
La URL objetivo es una página de inicio de sesión de la Sede Electrónica de Palma (https://palma.sedipualba.es/carpetaciudadana/login.aspx?returnUrl=https%3a%2f%2fpalma.sedipualba.es%2fcarpetaciudadana%2fnueva_entrada.aspx%3fidtramite%3d13809). Al cargar, la página ejecuta automáticamente una función JavaScript llamada loginConSeguridad() que abre un diálogo modal de jQuery UI.
Estructura del DOM:
Capa Principal: Contiene un elemento iframe con el ID ventanaModal. Este iframe se encuentra dentro de un contenedor con clase .ui-dialog.
Capa Iframe: El contenido real de autenticación reside exclusivamente dentro de ese iframe.
Elemento Objetivo: Dentro del iframe, existe una tabla con id="optSsl". El objetivo es interactuar con la primera fila (<tr>) de esta sección, que corresponde a la opción de "Identificarse con certificado digital".
Instrucciones para Playwright:
Paso 1: Navega a la URL y espera a que el estado de la red esté inactivo para asegurar que los scripts de jQuery hayan disparado el modal.
Paso 2: Localiza el frame mediante el selector #ventanaModal. Es crucial no intentar buscar los botones en la página principal, sino dentro del contexto de este frame.
Paso 3: Dentro del frame, identifica el elemento que contiene el texto: "Identificar-se amb certificat digital a través del nostre servidor".
Paso 4: Realiza un click() sobre el div con clase .titulo-opcion o directamente sobre la fila que contiene dicho texto.
Paso 5: Dado que la apertura del certificado digital puede disparar una ventana nativa del sistema, asegúrate de que el script no falle por un timeout esperando una navegación inmediata si el navegador requiere selección de certificado.
Selectores técnicos recomendados:
Frame: page.frameLocator('#ventanaModal')
Botón: frame.locator('#optSsl tr').first() o frame.getByText('Identificar-se amb certificat digital', { exact: false })

Cómo se traduce esto a código Playwright (para tu referencia)
Si introduces el prompt anterior en una herramienta de generación de código, el resultado debería ser algo similar a esto:
JavaScript
import { test, expect } from '@playwright/test';


test('Click en certificado digital dentro de iframe', async ({ page }) => {
  // Ir a la página
  await page.goto('https://palma.sedipualba.es/carpetaciudadana/login.aspx?returnUrl=https%3a%2f%2fpalma.sedipualba.es%2fcarpetaciudadana%2fnueva_entrada.aspx%3fidtramite%3d13809');


  // 1. Crear el localizador del iframe
  const loginFrame = page.frameLocator('#ventanaModal');


  // 2. Esperar a que el contenido interno del iframe esté cargado
  // (Buscamos la opción específica del certificado)
  const certOption = loginFrame.locator('#optSsl tr').first();


  // 3. Realizar la acción
  await certOption.click();
  
  // Nota: Si el navegador pide el certificado del sistema, 
  // Playwright se quedará esperando a menos que tengas el certificado instalado en el perfil.
});






<button class="btn redirect-url stop-click-propagation btn-bl1 btn-icono" data-icono="plus.svg" data-icono-color="#6889CE">Nueva instancia en blanco<span class="btn-icono-after" style="background-image: url(&quot;https://palma.sedipualba.es/jscomun/formularios/imgs/btns/plus.svg&quot;); background-color: rgb(104, 137, 206);"></span></button>

<input type="submit" name="ctl00$ctl00$cphM$cph$btnUltimoBorradorCancelar" value="Nueva instancia en blanco" id="ctl00_ctl00_cphM_cph_btnUltimoBorradorCancelar" class="btn clickable redirect-url stop-click-propagation" data-icono="plus.svg" data-icono-color="#6889CE" data-clickable-url="https://palma.sedipualba.es/carpetaciudadana/nueva_entrada.aspx?idtramite=13809&amp;recuperar=false" style="display: none;">

—--
Cambio url:
https://palma.sedipualba.es/carpetaciudadana/nueva_entrada.aspx?identrada=2048670


<div class="btn-bar-horizontal-centrada-inner"><button class="btn btn-icono" data-icono="plus.svg" data-icono-color="#6889CE">Nuevo/a interesado/a<span class="btn-icono-after" style="background-image: url(&quot;https://palma.sedipualba.es/jscomun/formularios/imgs/btns/plus.svg&quot;); background-color: rgb(104, 137, 206);"></span></button><input type="submit" name="ctl00$ctl00$cphM$cph$btnListaInteresadosOpcionesNuevo" value="Nuevo/a interesado/a" id="ctl00_ctl00_cphM_cph_btnListaInteresadosOpcionesNuevo" class="btn" data-icono="plus.svg" data-icono-color="#6889CE" style="display: none;"></div>



Te encuentras ante un diálogo flotante (jQuery UI) titulado "Nuevo/a interesado/a". Este formulario utiliza una técnica de carga parcial: al cambiar ciertos desplegables, el servidor procesa la información y actualiza los campos disponibles.
Instrucciones paso a paso para Playwright:
Selección de "Otra persona":
Localiza el select con ID #ctl00_ctl00_cphM_cph_ddlPersonaTipoUsuario.
Cambia el valor a OtraPersona.
Crucial: Debido a la clase autopostback, la página entrará en un estado de carga. Debes esperar a que el selector de "Tipo de personalidad" (que antes estaba deshabilitado) esté disponible y habilitado, o simplemente esperar a que el "velo" de carga desaparezca.
Selección de Personalidad (Lógica Condicional):
Localiza el select con ID #ctl00_ctl00_cphM_cph_ddlPersonaTipoPersonalidad.
Caso Persona Física: Selecciona el valor PersonaFisica. Esto habilitará campos como nombre y apellidos.
Caso Persona Jurídica: Selecciona el valor PersonaJuridica. Esto habilitará el campo de Razón Social.
Nota: Cada vez que selecciones uno, espera un breve momento (waitForLoadState o una espera de selector) porque el DOM se reconstruirá.
Confirmación:
Una vez completados los campos específicos de cada tipo, el botón final para guardar NO es un input tradicional, sino un button que contiene el texto "Aceptar" dentro de un contenedor con clase .btn-bar-horizontal-centrada-inner.
Utiliza el selector: button:has-text("Aceptar").
Estrategia de Código sugerida:
JavaScript
// 1. Seleccionar 'Otra persona' y esperar recarga parcial
await page.selectOption('#ctl00_ctl00_cphM_cph_ddlPersonaTipoUsuario', 'OtraPersona');

// Esperamos a que el sistema procese el postback 
// (El select de personalidad debería habilitarse)
const selectPersonalidad = page.locator('#ctl00_ctl00_cphM_cph_ddlPersonaTipoPersonalidad');
await expect(selectPersonalidad).toBeEnabled();

// 2. Lógica según el tipo de persona
const tipoPersona = 'PersonaFisica'; // O 'PersonaJuridica'

if (tipoPersona === 'PersonaFisica') {
    await selectPersonalidad.selectOption('PersonaFisica');
    // Aquí Playwright debería esperar a que aparezcan los campos de Nombre/Apellidos
    await page.waitForSelector('#ctl00_ctl00_cphM_cph_txtPersonaNombre'); 
} else {
    await selectPersonalidad.selectOption('PersonaJuridica');
    // Esperar a que el campo Razón Social esté habilitado
    await page.waitForSelector('#ctl00_ctl00_cphM_cph_txtPersonaRazonSocial');
}

// 3. Click en Aceptar (usando el botón visible con icono)
await page.locator('.btn-bar-horizontal-centrada-inner button:has-text("Aceptar")').cli



El flujo de Persona Física en esta sede electrónica es altamente dinámico debido al uso de autopostback. Cada vez que seleccionas un tipo de documento, el servidor reconstruye el formulario para mostrar solo los campos legalmente válidos para ese documento.
A continuación, detallo la ramificación completa y los campos que Playwright encontrará en cada camino:

📂 Ramificación: Persona Física
Una vez seleccionado PersonaFisica en el nivel anterior, el campo clave es #ctl00_ctl00_cphM_cph_ddlPersonaTipoDocumentoIdentidad. Aquí se abren tres rutas:
1. Opción: NIF/NIE (value="F")
Es la opción por defecto para ciudadanos españoles o residentes con NIE.
Campo Identificador: input#ctl00_ctl00_cphM_cph_txtPersonaCodigoDocumentoIdentidad (Formato 8 números + letra o X/Y/Z + 7 números + letra).
Campos de Nombre: * #ctl00_ctl00_cphM_cph_txtPersonaNombre (Obligatorio)
#ctl00_ctl00_cphM_cph_txtPersonaApellido1 (Obligatorio)
#ctl00_ctl00_cphM_cph_txtPersonaApellido2 (Opcional, pero usual en España)
2. Opción: Doc. Identidad UE (value="X")
Para ciudadanos de la Unión Europea que no residen en España o no tienen NIE.
Campo Identificador: El campo de código de documento se mantiene, pero suele validarse de forma distinta (permite caracteres específicos del país de origen).
Campo adicional (País): Suele aparecer un nuevo desplegable:
select#ctl00_ctl00_cphM_cph_ddlPersonaPais (Para indicar el estado miembro emisor).
Campos de Nombre: Se mantienen Nombre y Apellidos.
3. Opción: Pasaporte (value="P")
Para ciudadanos extracomunitarios.
Campo Identificador: El mismo input de código, pero configurado para aceptar el formato de pasaporte (alfanumérico).
Campo adicional (País): Aparece obligatoriamente el selector de país emisor del pasaporte.
Estructura de Nombre: En algunos casos, si el pasaporte no distingue apellidos, el sistema permite dejar el segundo apellido vacío o agruparlos en el primero.

🔄 Flujo de Interacción para Playwright
Para que el script no falle, debes seguir este orden lógico de "espera y acción":
Paso A: Selección del documento
JavaScript
// Seleccionamos Pasaporte como ejemplo
await page.selectOption('#ctl00_ctl00_cphM_cph_ddlPersonaTipoDocumentoIdentidad', 'P');

// ESPERA CRÍTICA: El formulario se recarga. 
// Debemos esperar a que el campo de Nombre sea editable de nuevo.
await page.waitForSelector('#ctl00_ctl00_cphM_cph_txtPersonaNombre:not([disabled])');

Paso B: Rellenar Datos (Ejemplo ramificado)
Campo
Selector Playwright
Tipo
Código Doc.
#ctl00_ctl00_cphM_cph_txtPersonaCodigoDocumentoIdentidad
Input
Nombre
#ctl00_ctl00_cphM_cph_txtPersonaNombre
Input
1º Apellido
#ctl00_ctl00_cphM_cph_txtPersonaApellido1
Input
País (Solo UE/Pas)
#ctl00_ctl00_cphM_cph_ddlPersonaPais
Select


⚠️ Puntos de Bloqueo Comunes
Validación de Formato: Si introduces un NIF incorrecto en el campo de texto, al perder el foco (blur) o al intentar darle a "Aceptar", el servidor lanzará una alerta o un mensaje de error dentro del modal. Playwright debe verificar si aparece un elemento con clase .validador-error o .alert.
El "Velo" de Carga: Esta sede usa un div id="velo" con un gif de "Espere, por favor...". Una técnica avanzada de Playwright es esperar a que este velo sea invisible antes de continuar:
JavaScript
await page.waitForSelector('#velo', { state: 'hidden' });


Selector de Correo-e: Recuerda que al final del formulario hay otro select de email. Si la persona es nueva, tendrás que seleccionar la opción [Otro] (valor vacío ""), lo cual disparará otra recarga para mostrar un campo de texto donde escribir el email manualmente.
🏢 Flujo: Persona Jurídica
Una vez seleccionado PersonaJuridica en el desplegable de personalidad, el formulario se simplifica para centrarse en los datos de la entidad.
1. Identificación de la Empresa
A diferencia de la persona física, aquí no hay selección de "Tipo de documento", ya que para empresas siempre se espera el NIF societario.
NIF de la Empresa:
Selector: #ctl00_ctl00_cphM_cph_txtPersonaCodigoDocumentoIdentidad
Acción: fill() con el NIF (ej. B12345678).
Razón Social:
Selector: #ctl00_ctl00_cphM_cph_txtPersonaRazonSocial
Acción: fill() con el nombre completo de la sociedad.
2. Datos de Notificación (Punto Crítico)
Las personas jurídicas están obligadas por ley a la notificación electrónica. En este formulario, verás que el checkbox de "Acepta ser notificado/a de forma electrónica" suele aparecer marcado y bloqueado (disabled="disabled").
Lo que sí debes gestionar es el canal de aviso:
Email: Si el email de la empresa no está en el desplegable, deberás seleccionar la opción [Otro].
Teléfono: Al igual que el email, si el móvil no está en la lista, hay que seleccionar [Otro].

🛠️ Implementación en Playwright
Debido a que los campos pueden tardar un instante en pasar de disabled a enabled tras el postback, el código debe ser así:
JavaScript
// 1. Introducir NIF y Razón Social
// Usamos .waitForEditable() para asegurar que el postback anterior terminó
const nifInput = page.locator('#ctl00_ctl00_cphM_cph_txtPersonaCodigoDocumentoIdentidad');
await nifInput.waitFor({ state: 'visible' });
await nifInput.fill('B62798210');

const razonSocialInput = page.locator('#ctl00_ctl00_cphM_cph_txtPersonaRazonSocial');
await razonSocialInput.fill('NOMBRE DE LA EMPRESA SL');

// 2. Manejo de Email (Seleccionar "Otro" si es necesario)
const emailSelect = page.locator('#ctl00_ctl00_cphM_cph_ddlPersonaEmailNotificacionSelector');
await emailSelect.selectOption({ label: '[Otro]' });

// Al seleccionar "[Otro]", se dispara un autopostback. Esperamos el nuevo input.
const emailManual = page.locator('#ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion');
await emailManual.waitFor({ state: 'visible' });
await emailManual.fill('contacto@empresa.com');

// 3. Manejo de Teléfono
const tlfSelect = page.locator('#ctl00_ctl00_cphM_cph_ddlPersonaTelefonoMovilSelector');
await tlfSelect.selectOption({ label: '[Otro]' });

const tlfManual = page.locator('#ctl00_ctl00_cphM_cph_txtPersonaTelefonoMovil');
await tlfManual.waitFor({ state: 'visible' });
await tlfManual.fill('600000000');

// 4. Finalizar
await page.locator('.btn-bar-horizontal-centrada-inner button:has-text("Aceptar")').click();


⚠️ Lo que Playwright debe vigilar en este camino
Validación de Razón Social: Este campo tiene un maxlength="90". Si el nombre de la empresa es muy largo, Playwright lo truncará automáticamente, lo cual podría invalidar la firma posterior si no coincide exactamente con el certificado.
El estado "Disabled": En tu HTML de ejemplo, los inputs aparecen como disabled="disabled". Esto sucede porque el sistema todavía cree que eres el "Usuario Autenticado". Solo se volverán editables después de que Playwright seleccione OtraPersona en el primer paso y el servidor responda.
Interoperabilidad: Verás un checkbox llamado #ctl00_ctl00_cphM_cph_chkPersonaInterop. Por defecto está desmarcado. Si lo marcas, la empresa se "opone" a que el ayuntamiento consulte sus datos en otras administraciones, lo que te obligará a subir más documentos después. Normalmente se deja sin marcar.
Esta es la fase final del formulario de interesado, y es donde Playwright debe ser más cuidadoso debido a la validación de duplicidad (repetir el email) y a la naturaleza obligatoria de los campos.
Como mencionamos antes, estos campos de texto (input) suelen aparecer solo cuando seleccionas "[Otro]" en los desplegables anteriores. Aquí tienes el mapa de actuación para Playwright:

📧 Sección: Modalidad de Notificación
El sistema requiere que el correo electrónico se introduzca dos veces para evitar errores tipográficos. Playwright debe simular esto correctamente.
1. Validación de Email (Campos Gemelos)
Primer campo: #ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion
Segundo campo (Confirmación): #ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion2
Nota: Este segundo campo tiene autocomplete="off", lo que refuerza que el sistema quiere una entrada manual o una simulación de escritura clara.
2. Validación de Teléfono
Campo: #ctl00_ctl00_cphM_cph_txtPersonaTelefonoMovil
Restricción: Tiene un maxlength="9". Playwright no debe incluir prefijos (como +34) a menos que el validador lo permita, pero por el estándar de Sedipualba, suelen ser 9 dígitos estrictos.

🤖 Implementación en Playwright
Para asegurar que los campos son interactuables (ya que aparecen tras un postback), lo ideal es usar este flujo:
JavaScript
const email = "usuario@ejemplo.com";
const telefono = "600123456";

// 1. Rellenar y confirmar el correo electrónico
const emailInput1 = page.locator('#ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion');
const emailInput2 = page.locator('#ctl00_ctl00_cphM_cph_txtPersonaEmailNotificacion2');

await emailInput1.fill(email);
await emailInput2.fill(email);

// 2. Rellenar el teléfono móvil
const tlfInput = page.locator('#ctl00_ctl00_cphM_cph_txtPersonaTelefonoMovil');
await tlfInput.fill(telefono);

// 3. Verificación de seguridad (Opcional pero recomendado)
// A veces el sistema tarda en habilitar el botón "Aceptar" hasta que los campos obligatorios son válidos
await expect(emailInput1).toHaveValue(email);
await expect(tlfInput).toHaveAttribute('class', /campo-obligatorio/);


📈 Diagrama de Flujo: Decisiones de Interesado
Para visualizar cómo Playwright debe navegar por todas las opciones que hemos discutido (Persona Física vs. Jurídica y tipos de documento), aquí tienes la estructura lógica:

⚠️ Consideraciones Críticas para el Éxito
Validación en tiempo real: Esta página usa validadores de ASP.NET. Si el email 1 y el email 2 no coinciden, al intentar hacer clic en "Aceptar", aparecerá un mensaje de error (normalmente un <span> con color rojo). Es bueno que Playwright verifique si aparece algún texto de error después de rellenar los campos.
Formato del Teléfono: Si intentas meter espacios (ej: "600 12 34 56"), el atributo maxlength="9" cortará el número. Usa siempre .fill() con los 9 dígitos seguidos.
El botón "Aceptar": Recuerda que el botón de envío real es el que tiene el ID #ctl00_ctl00_cphM_cph_btnAceptarPersona, pero físicamente el usuario suele ver un <button> de jQuery UI que lo envuelve. Playwright es más robusto si clicas en el botón visible:
JavaScript
await page.getByRole('button', { name: /Aceptar/i }).click();
1. Finalización del Interesado
Una vez rellenos los datos de notificación del interesado (email y teléfono), debemos cerrar ese primer diálogo.
Acción: Clic en el botón "Aceptar".
Selector técnico: Aunque el ID del input oculto es #ctl00_ctl00_cphM_cph_btnAceptarPersona, Playwright debe interactuar con el botón visible de la interfaz jQuery UI.
Código:
JavaScript
await page.locator('.btn-bar-horizontal-centrada-inner button:has-text("Aceptar")').click();



2. Transición y Selección de Representante
Al aceptar, el diálogo desaparece y la página principal se actualiza mostrando al interesado en una lista. Ahora aparece una nueva barra de botones para ese interesado específico.
Espera: Debes esperar a que el diálogo anterior se cierre completamente y aparezca el botón "Indicar representante".
Acción: Clic en "Indicar representante".
Selector técnico: #ctl00_ctl00_cphM_cph_repListaInteresados_ctl00_btnListaInteresadosItemNuevoRepresentante (o su versión visible en botón).
Código:
JavaScript
// Esperar a que el botón sea visible tras el cierre del modal anterior
const btnRepresentante = page.getByRole('button', { name: 'Indicar representante' });
await btnRepresentante.waitFor({ state: 'visible' });
await btnRepresentante.click();



3. Configuración del Representante (Nuevo Diálogo)
Se abrirá un segundo diálogo titulado "Nuevo/a representante del/de la interesado/a...". Aunque visualmente es igual al anterior, los IDs de los campos suelen ser los mismos porque la página los recicla o usa la misma estructura de panel.
Diferencia clave: En este caso, como el usuario que está haciendo el trámite suele ser el representante (gestoría, abogado o la propia empresa), el sistema selecciona por defecto "Usuario autenticado".
Acción solicitada: Confirmar los datos que ya vienen rellenos del certificado digital y darle a Aceptar directamente.
Estrategia para Playwright:
JavaScript
// 1. Esperar 2 segundos a que el diálogo del representante cargue completamente
await page.waitForTimeout(2000); 

// 2. Verificar que el diálogo está presente (por el título específico)
await expect(page.locator('.ui-dialog-title')).toContainText('Nuevo/a representante');

// 3. Click en Aceptar (abajo de todo en el nuevo diálogo)
// Usamos el mismo selector de botón de aceptar que antes, 
// ya que el DOM del modal anterior ha sido reemplazado o el nuevo está encima.
const btnAceptarRep = page.locator('.btn-bar-horizontal-centrada-inner button:has-text("Aceptar")');
await btnAceptarRep.scrollIntoViewIfNeeded(); // Aseguramos visibilidad
await btnAceptarRep.click();


⚠️ Notas de robustez para el bot:
Z-Index y Foco: Al haber múltiples diálogos que se abren y cierran, a veces Playwright puede intentar clicar en el "Aceptar" del diálogo anterior si no ha desaparecido del DOM. Es más seguro usar page.locator('.ui-dialog:visible .btn-bar-horizontal-centrada-inner button:has-text("Aceptar")') para asegurar que clicas en el que está activo en pantalla.
Validación de Carga: Si después de dar a "Indicar representante" aparece el "velo" (#velo), asegúrate de que sea invisible antes de intentar clicar en el "Aceptar" final.
Identidad del Representante: En tu HTML se ve que el valor por defecto es UsuarioAutenticado (la empresa MULTIVIA...). Si este es el comportamiento deseado, no toques los desplegables de este segundo diálogo y ve directo al botón inferior.
1. Avance a la Fase de Formulario
Tras configurar al representante, la página principal se actualiza. Debemos avanzar al siguiente paso del asistente.
Acción: Clic en "Siguiente".
Selector Sugerido: button:has-text("Siguiente") (asociado al input #ctl00_ctl00_cphM_cph_btnSiguiente).
Nota de Robustez: Asegúrate de NO clicar en "Eliminar este borrador", que está justo al lado.
JavaScript
// Esperar a que el botón de Siguiente esté disponible tras el postback del representante
await page.locator('.btn-bar-horizontal-centrada-inner button:has-text("Siguiente")').click();


2. Entrada al Formulario de Alegaciones (Iframe)
Al pulsar siguiente, se abre un diálogo con un título como "ALEGACIONS-RECURSOS MULTES". Dentro hay un iframe.
Identificador del Frame: id="ventanaModal"
Campos de Entrada: Los IDs que has facilitado (como ctl00_cph_638481508662232584) parecen ser dinámicos o generados por el motor de formularios (cambian según la sesión).
Estrategia de Localización Segura: Como los IDs son complejos y probablemente cambien, usaremos selectores basados en la posición o etiquetas asociadas si Playwright tiene acceso al texto de los labels. Si solo tenemos el HTML que pasaste, usaremos los IDs pero con cautela.
JavaScript
// 1. Localizar el iframe del formulario
const formFrame = page.frameLocator('#ventanaModal');

// 2. Rellenar los campos dentro del iframe
// Expediente
await formFrame.locator('#ctl00_cph_638481508662232584').fill('2024-EXP-12345');

// Matrícula
await formFrame.locator('#ctl00_cph_638481510178519833').fill('1234BBB');

// Expone (Textarea)
await formFrame.locator('#ctl00_cph_638469681591763749').fill('Que he recibido una notificación de sanción...');

// Solicitud (Textarea)
await formFrame.locator('#ctl00_cph_638469681932006542').fill('Que se proceda a la anulación de la multa por...');


⚠️ Advertencia sobre IDs Dinámicos
Si al ejecutar el script ves que Playwright no encuentra los campos, es porque esos números largos en el ID (63848150...) han cambiado. En ese caso, la mejor forma de actuar es por el orden de los inputs dentro del formulario:
JavaScript
// Forma alternativa si los IDs fallan:
const inputs = formFrame.locator('input[type="text"].form-control');
await inputs.nth(0).fill('EXPEDIENTE_AQUI'); // Primer input
await inputs.nth(1).fill('MATRICULA_AQUI');  // Segundo input

const textareas = formFrame.locator('textarea.form-control');
await textareas.nth(0).fill('TEXTO_EXPONE');
await textareas.nth(1).fill('TEXTO_SOLICITUD');

1. Confirmación del Formulario de Alegaciones
Dentro del iframe de alegaciones que rellenamos antes, hay que confirmar para que los datos se guarden en el borrador.

Selector: button:has-text("Confirmar")

Contexto: Sigue siendo dentro del frameLocator('#ventanaModal').

Acción: Clic y esperar a que el iframe se cierre o la página principal se refresque.

JavaScript
const formFrame = page.frameLocator('#ventanaModal');
await formFrame.locator('button:has-text("Confirmar")').click();
2. Abrir el Diálogo de "Añadir Fichero"
Una vez guardadas las alegaciones, volverás a la pantalla principal de la instancia donde aparece la lista de documentos.

Selector: El botón "Añadir" con el icono azul (plus.svg).

Código:

JavaScript
await page.locator('.btn-bar-horizontal-centrada-inner button:has-text("Añadir")').click();
3. Subida del Archivo (El truco del input:file)
Aquí está la parte difícil: El botón "Enviar fichero" es puramente visual. Para subir un archivo en Playwright, no debes clicar en ese botón, sino interactuar con el input oculto que el sistema tiene preparado.

Estructura técnica:
El HTML muestra un <input type="file" multiple="multiple" style="display:none">. Playwright puede "inyectar" el archivo ahí aunque no sea visible.

Pasos para el script:

Localizar el input de tipo archivo que está dentro del panel #ctl00_ctl00_cphM_cph_pnlNuevoFichero.

Usar .setInputFiles() para cargar tu PDF o imagen.

Esperar a que la barra de carga (si aparece) termine.

JavaScript
// 1. Definir la ruta del archivo local
const rutaArchivo = 'ruta/a/tu/documento.pdf';

// 2. Localizar el input oculto y subir el archivo
// Usamos un selector que combine el contenedor del modal y el tipo input
await page.setInputFiles('#ctl00_ctl00_cphM_cph_pnlNuevoFichero input[type="file"]', rutaArchivo);

// 3. Esperar a que el archivo aparezca en la lista del modal (confirmación de subida)
// Normalmente aparece una tabla o el nombre del archivo en el área de drag&drop
await page.waitForSelector('.tabla-ficheros td'); 
4. Aceptar y Cerrar el Modal de Archivos
Una vez que el archivo ha sido procesado por el servidor, el botón "Aceptar" del modal se habilitará.

Acción: Clic en "Aceptar".

Selector: button:has-text("Aceptar") dentro del contexto del modal de ficheros.

JavaScript
await page.locator('.panel-dialog button:has-text("Aceptar")').click();
💡 Resumen del Flujo de Documentación
Consejos para evitar fallos:
Extensiones: El script que compartiste acepta una lista enorme (JPG, PDF, DOCX, ZIP, etc.). Asegúrate de que tu archivo no supere los 150 MB mencionados.

Tiempos de espera: La subida de archivos depende de tu conexión. Si el archivo es grande, Playwright podría dar timeout. Puedes aumentar el tiempo de espera así:

JavaScript
await page.locator('.panel-dialog button:has-text("Aceptar")').click({ timeout: 60000 });
Estado del botón: A veces el botón "Aceptar" no funciona hasta que el componente Multifileuploader termina de enviar los fragmentos del archivo. Si el clic falla, añade un pequeño waitForTimeout(1000) después de subir el archivo.