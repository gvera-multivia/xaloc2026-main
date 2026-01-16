# Guia de movimientos dentro de la web de Madrid (hasta el formulario)

Esta guia describe el flujo de navegacion (clicks + esperas) hasta llegar al formulario de tramitacion en la Sede Electronica del Ayuntamiento de Madrid, siguiendo el documento `explore-html/Guia movimiento hasta el formulario en web de madrid.pdf`.

---

## 1 - Pagina base del tramite (Sede Madrid)

Enlace base (tramite de multas de circulacion):

`https://sede.madrid.es/portal/site/tramites/menuitem.62876cb64654a55e2dbd7003a8a409a0/?vgnextoid=dd7f048aad32e210VgnVCM1000000b205a0aRCRD&vgnextchannel=3838a38813180210VgnVCM100000c90da8c0RCRD&vgnextfmt=default`

Objetivo de esta pantalla: abrir el bloque de acciones de tramitacion en linea para poder acceder al "Registro Electronico".

Punto clave: el boton de "Tramitar en linea" no navega a otra URL directamente, si no que apunta a un ancla de la propia pagina (`href=\"#verTodas\"`). Por tanto, en automatizacion lo ideal es:

- Click al boton
- Esperar a que exista/sea visible el bloque `#verTodas`

### 1.1 - Boton "Tramitar en linea"

HTML de referencia:

```html
<a class="btn btn-primary btn-primary--icon" id="tramitarClick" href="#verTodas">
  <span>Tramitar en linea</span>
</a>
```

Selectores sugeridos:

- CSS por id: `#tramitarClick`
- Alternativa por rol/texto: `get_by_role('link', name=/Tramitar en l.{0,2}nea/i)`

---

## 2 - Acceso a "Registro Electronico"

Una vez desplegado el bloque de tramitacion, se debe pulsar el enlace "Registro Electronico" (abre la pasarela `servpub.madrid.es`).

HTML de referencia:

```html
<a
  href="https://servpub.madrid.es/WFORS_WBWFORS/servlet?&amp;idContent=dd7f048aad32e210VgnVCM1000000b205a0aRCRD&amp;nombreTramite=Multas de circulacion. Infracciones y sanciones competencia del Ayuntamiento de Madrid"
  target="_self"
  title=""
  rel="nofollow"
>
  Registro Electronico
  <span class="info-file"></span>
</a>
```

Punto clave: `target=\"_self\"` (navega en la misma pestana).

Selectores sugeridos:

- Por texto: `get_by_role('link', name=/Registro\\s+Electronico/i)`
- Por dominio: `a[href^='https://servpub.madrid.es/WFORS_WBWFORS/servlet']`

---

## 3 - Pantalla intermedia: "Continuar"

Tras entrar en el dominio `servpub.madrid.es` aparece un formulario con un boton "Continuar".

HTML de referencia:

```html
<input class="button button4" id="btn1" name="btn1" type="submit" value="Continuar">
```

Puntos clave:

- Es un `input[type=submit]`, por lo que puede disparar navegacion/recarga.
- El id `btn1` se reutiliza mas adelante con otro `type` (ver paso 9). No conviene depender solo del id; mejor combinar con `type` + `value`.

Selectores sugeridos:

- CSS: `input#btn1[type='submit'][value='Continuar']`

---

## 4 - Pantalla: "Iniciar tramitacion"

Siguiente accion: pulsar "Iniciar tramitacion".

HTML de referencia:

```html
<a id="btnConAuth" type="button" onclick="loading()" class="button button4" href="/WFORS_WBWFORS/signa">Iniciar tramitacion</a>
```

Puntos clave:

- Es un `<a>` con `href` relativo (`/WFORS_WBWFORS/signa`).
- Dispara `loading()` (habitual que haya overlay/spinner). Mejor esperar a `domcontentloaded` y/o a que desaparezca el overlay si existe.

Selectores sugeridos:

- CSS: `#btnConAuth`
- Alternativa: `a.button.button4:has-text('Iniciar tramitacion')`

---

## 5 - Metodo de acceso: "DNIe / Certificado"

En la pantalla de login de la Sede, elegir "DNIe / Certificado".

HTML de referencia:

```html
<a href="#" class="login-sede-opt-link" onclick="handleNoDomain(this,
  'IDPCLCTM',
  'CLAVE')">
  <div class="col-md-5 login-sede-opt">
    <div class="col-sm-6">
      <img class="login-sede-img" src="./login-clave/DNIe.png" alt="">
    </div>
    <div class="col-sm-7 login-sede-titel">
      DNIe / Certificado
    </div>
  </div>
</a>
```

Selectores sugeridos:

- Por texto: `get_by_role('link', name=/DNIe\\s*\\/\\s*Certificado/i)`
- Por clase + texto: `a.login-sede-opt-link:has-text('DNIe / Certificado')`

---

## 6 - Certificado: redireccion + popup de Windows

Tras pulsar "DNIe / Certificado", se indica:

- Esperar redireccion temporal
- Aparece la alerta/popup de seleccion de certificado (nativo de Windows)

Este paso es equivalente a lo que ya existe en el proyecto para otros sitios (ej.: `sites/base_online/flows/login.py` y `utils/windows_popup.py`):

- Se lanza un thread con `pyautogui` para aceptar automaticamente el certificado
- En paralelo, Playwright espera a la URL destino o a que la pantalla siguiente cargue

Punto clave: no conviene usar `networkidle` como condicion general (puede no alcanzarse si hay peticiones constantes). Usar `domcontentloaded` + esperas especificas.

---

## 7 - Pantalla tras autenticacion: boton "Continuar"

Tras autenticarse, pulsar "Continuar".

HTML de referencia:

```html
<input class="button button4" id="btnContinuar" name="btnContinuar" type="submit" value="Continuar" onclick="continuarTramite();">
```

Selectores sugeridos:

- CSS: `#btnContinuar`
- Alternativa por atributos: `input[type='submit'][value='Continuar'][onclick*='continuarTramite']`

---

## 8 - Seleccion de opcion: "Tramitar nueva solicitud"

En la siguiente pantalla se debe seleccionar la opcion de "Tramitar nueva solicitud".

HTML de referencia:

```html
<input type="radio" id="checkboxNuevoTramite" name="checkbox1" class="checkbox01" value="nuevoTramite" onclick="cargarOpciones()">
```

Punto clave: tras el click se ejecuta `cargarOpciones()` y el DOM se actualiza mostrando nuevas opciones. Por tanto:

- Click al radio
- Esperar a que el siguiente grupo de radios aparezca

Selectores sugeridos:

- CSS: `#checkboxNuevoTramite`

---

## 9 - Seleccion de rol: "Persona o Entidad interesada"

Una vez actualizado el DOM, seleccionar "Persona o Entidad interesada" y continuar.

HTML de referencia (radio):

```html
<input type="radio" id="checkboxInteresado" name="checkbox" class="checkbox01" value="interesado">
```

HTML de referencia (boton continuar en esta pantalla):

```html
<input class="button button4" id="btn1" name="btn1" type="button" value="Continuar" onclick="validar(); loading()" title="Continuar">
```

Puntos clave:

- Aqui `btn1` ya no es `submit`, si no `type=\"button\"`.
- Se ejecuta `validar(); loading()`: puede haber overlay/spinner, y la navegacion puede ocurrir despues de una validacion previa.

Selectores sugeridos:

- Radio: `#checkboxInteresado`
- Continuar: `input#btn1[type='button'][value='Continuar']`

---

## 10 - Condicional: existe tramite a medias

Puede aparecer una pantalla que indique que hay un tramite a medias. En ese caso, siempre se debe pulsar "Nuevo tramite".

HTML de referencia:

```html
<input class="button button4" id="btnNuevoTramite" name="btnNuevoTramite" type="submit" value="Nuevo tramite" onclick="nuevoTramite();">
```

Recomendacion de deteccion:

- Si existe `#btnNuevoTramite`, pulsarlo y continuar el flujo normal.
- Si no existe, continuar sin hacer nada (ya estamos en el camino de tramite nuevo).

Nota del PDF: "Considera el html completo del interior del form para poder identificar cuando estamos o no en este caso".

---

## 11 - Llegada al formulario (fin del alcance del PDF)

El PDF termina en el paso anterior (pantalla condicional). Para finalizar la automatizacion hasta "estar en el formulario", es recomendable definir una condicion de llegada, por ejemplo:

- URL contiene un path del tramite concreto (cuando se capture con una ejecucion real)
- Existe un elemento estable del formulario final (por ejemplo un `form`, un `h1`/`legend` especifico o un input obligatorio)

Para completar esta parte con el mismo nivel de detalle que `explore-html/base-guide.md`, lo ideal es capturar el HTML del formulario final (igual que se hizo con los HTML en `explore-html/` para BASE) y anexar aqui:

- Selectores de campos a rellenar
- Validaciones/errores habituales
- Subida de documentos si aplica

---

# Plan de accion: como crear un flujo de automatizacion por web en este proyecto (aplicable a Madrid)

Esta seccion resume la estructura "por web" que sigue el proyecto y propone un plan para implementar la automatizacion de Madrid manteniendo el mismo patron que `sites/xaloc_girona` y `sites/base_online`.

## Estructura del proyecto (patron por sitio)

Cada web se implementa como un paquete dentro de `sites/<site_id>/` con estas piezas:

1. `sites/<site_id>/config.py`
   - Extiende `core/base_config.py:BaseConfig`
   - Define `url_base` y selectores/regex/urls objetivo del login y transiciones.

2. `sites/<site_id>/data_models.py`
   - Define dataclasses con los datos de entrada del tramite (inputs del formulario, ficheros adjuntos, etc.).

3. `sites/<site_id>/controller.py`
   - Expone `site_id` y `display_name`
   - Crea config (`create_config`) y datos demo (`create_demo_data`) para ejecucion local desde `main.py`.

4. `sites/<site_id>/automation.py`
   - Clase `XxxAutomation(BaseAutomation)` (ver `core/base_automation.py`)
   - Orquesta el flujo completo: login -> navegacion -> formulario -> subida -> confirmacion

5. `sites/<site_id>/flows/`
   - Funciones async, separadas por fases (ej.: `login.py`, `formulario.py`, `documentos.py`, `confirmacion.py`)
   - `flows/__init__.py` re-exporta funciones principales que usa `automation.py`

Y finalmente se registra el sitio en `core/site_registry.py` (mapea `site_id` -> clase Automation y Controller).

## Plan de implementacion para Madrid (pasos recomendados)

### Paso A - Captura de HTML y criterios de espera

1. Capturar HTML real de cada pantalla del flujo (pasos 1 a 10 de esta guia), y del formulario final (paso 11):
   - Guardar copias en `explore-html/` (mismo enfoque que BASE), para documentar selectores y detectar cambios.
2. Definir criterios de espera robustos por pantalla:
   - Evitar `networkidle` como regla general
   - Usar `domcontentloaded` + `wait_for_url` + esperas a elementos clave (ids/roles)

### Paso B - Crear el nuevo sitio `sites/madrid/`

1. `sites/madrid/config.py`
   - `url_base` = enlace base del tramite (paso 1)
   - Selectores: `#tramitarClick`, link Registro Electronico, `#btnConAuth`, `#btnContinuar`, radios, `#btnNuevoTramite`
2. `sites/madrid/data_models.py`
   - Empezar solo con datos minimos (si el objetivo inicial es llegar al formulario, puede no requerir campos)
   - Cuando se documente el formulario final, anadir campos obligatorios + lista de adjuntos (si existe upload)
3. `sites/madrid/flows/login.py` (o `navegacion.py` si no hay login independiente)
   - Implementar los pasos 1 a 10 (y el condicional) con Playwright
   - Reutilizar `utils/windows_popup.py` para el popup de certificado (thread + click)
4. `sites/madrid/automation.py`
   - Orquestar: navegar hasta formulario -> (futuro) rellenar -> (futuro) adjuntar -> (futuro) confirmar
5. `sites/madrid/controller.py`
   - `site_id = 'madrid'`, `display_name` claro
   - `create_demo_data()` con datos ficticios y rutas a `pdfs-prueba/` si se adjuntan documentos

### Paso C - Registrar el sitio y exponerlo en CLI

1. Anadir entrada en `core/site_registry.py:SITES`:
   - `automation_path=\"sites.madrid.automation:MadridAutomation\"`
   - `controller_path=\"sites.madrid.controller:get_controller\"`
2. (Opcional) Anadir parametros CLI en `main.py` si Madrid requiere inputs especificos (como `--protocol` en BASE).

### Paso D - Iteracion y endurecimiento

1. Anadir logs por fase en `automation.py` (mismo estilo que BASE/Xaloc).
2. Capturar screenshot final de la pantalla de formulario y de errores (ya soportado por `BaseAutomation.capture_error_screenshot`).
3. Aislar piezas reutilizables:
   - Si Madrid tiene subida de ficheros similar a BASE, reutilizar el patron de `sites/base_online/flows/upload.py` (modal + iframe).
