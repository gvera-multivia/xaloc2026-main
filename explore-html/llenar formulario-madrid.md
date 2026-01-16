# Guia para rellenar el formulario de Madrid

Este documento continua el flujo descrito en `explore-html/madrid-guide.md` una vez ya estamos dentro del formulario (copia HTML en `explore-html/formulario-madrid.html`), y concreta como completar los campos siguiendo `explore-html/Continuación Madrid.pdf`.

---

## 0 - Pantalla y objetivo

El formulario corresponde a "Multas de circulacion. Presentar alegaciones" y el objetivo de esta pantalla es:

1. Rellenar los campos requeridos del formulario.
2. Pulsar "Continuar" para pasar a la fase de adjuntar documentacion (pantalla posterior).

En el HTML se describe explicitamente:

```html
<span>Rellene el formulario y pulse el boton <span class="bold">Continuar</span> para completar los datos y <span class="bold">adjuntar</span> documentacion.</span>
```

---

## 1 - Datos del expediente (Referencia + formato)

### 1.1 - Seleccion del formato (radio buttons)

Primero hay que seleccionar el formato de la "Referencia del expediente" y rellenar los 3 campos correspondientes, segun la opcion elegida.

HTML de los radios (ids relevantes):

```html
<input type="radio" id="TIPO_EXPEDIENTE_1" value="opcion1">
<input type="radio" id="TIPO_EXPEDIENTE_2" value="opcion2">
```

Los textos de ayuda indican el formato esperado:

- `opcion1`: `NNN/EEEEEEEEE.D` (ejemplo: `911/102532229.3`)
- `opcion2`: `LLL/AAAA/EEEEEEEEE` (ejemplo: `MSA/2025/123456789`)

Punto clave: al cambiar el radio se dispara un refresco (hay un `refresh_method` oculto), por lo que en automatizacion hay que:

- Click en `#TIPO_EXPEDIENTE_1` o `#TIPO_EXPEDIENTE_2`
- Esperar a que el DOM se actualice y los inputs correspondientes esten habilitados

### 1.2 - Inputs para `opcion1` (NNN/EEEEEEEEE.D)

Campos a rellenar (clases recomendadas):

- `NNN` -> `.formula2_EXP1\.1`
- `EEEEEEEEE` -> `.formula2_EXP1\.2`
- `D` -> `.formula2_EXP1\.3`

HTML de referencia (ids variables, usar clase en automatizacion):

```html
<input class="formula2_EXP1.1" type="text">
<input class="formula2_EXP1.2" type="text">
<input class="formula2_EXP1.3" type="text">
```

Nota tecnica: el punto `.` forma parte del nombre de clase (hay que escaparlo en CSS: `\\.`, por ejemplo `.formula2_EXP1\\.1`).

### 1.3 - Inputs para `opcion2` (LLL/AAAA/EEEEEEEEE)

Campos a rellenar (clases recomendadas):

- `LLL` -> `.formula2_EXP2\.1`
- `AAAA` -> `.formula2_EXP2\.2`
- `EEEEEEEEE` -> `.formula2_EXP2\.3`

HTML de referencia:

```html
<input class="formula2_EXP2.1" type="text">
<input class="formula2_EXP2.2" type="text">
<input class="formula2_EXP2.3" type="text">
```

---

## 2 - Matricula del vehiculo

Tras completar la referencia del expediente, rellenar la matricula:

```html
<input class="formula2_GESTION_MULTAS_MATRICULA" type="text" aria-required="true">
```

Selector recomendado:

- CSS: `.formula2_GESTION_MULTAS_MATRICULA`

---

## 3 - Datos del interesado/a (mayoritariamente pre-rellenado)

En esta seccion muchos campos vienen ya informados y/o deshabilitados (derivados del certificado/usuario) y no se deben forzar.

### 3.1 - Confirmacion por email / SMS (checkboxes)

Segun el PDF, hay que marcar las checkboxes de confirmacion por email (y opcionalmente SMS si aplica).

Checkbox email interesado:

```html
<input type="checkbox" class="formula2_COMUNES_INTERESADO_CHECKEMAIL">
```

Checkbox email representante:

```html
<input type="checkbox" class="formula2_COMUNES_REPRESENTANTE_CHECKEMAIL">
```

Opcional (tambien existe en el HTML):

- `.formula2_COMUNES_INTERESADO_CHECKSMS`
- `.formula2_COMUNES_REPRESENTANTE_CHECKSMS`

### 3.2 - Telefono interesado/a (editable)

En el HTML, el campo de telefono del interesado aparece editable:

```html
<input class="formula2_COMUNES_INTERESADO_TELEFONO" type="text" maxlength="20">
```

---

## 4 - Datos del/de la representante

El PDF indica que se deben rellenar los campos de esta zona, pero con excepciones claras: no tocar los campos que ya vienen informados y deshabilitados.

### 4.1 - Campos que NO se rellenan (porque ya estan informados)

No rellenar (segun el PDF):

- Tipo de documento
- Numero de documento
- Nombre
- Primer apellido
- Segundo apellido
- Razon social

Estos campos suelen venir deshabilitados en el HTML (clases `formula2_COMUNES_REPRESENTANTE_TIPODOC`, `..._NUMIDENT`, `..._NOMBRE`, `..._APELLIDO1`, `..._APELLIDO2`, `..._RAZONSOCIAL`).

### 4.2 - Campos que SI se rellenan (contacto/domicilio)

Campos representate (segun `explore-html/formulario-madrid.html`):

- Tipo via (select): `.formula2_COMUNES_REPRESENTANTE_TIPOVIA`
- Domicilio / nombre via: `.formula2_COMUNES_REPRESENTANTE_NOMBREVIA`
- Tipo numeracion (select): `.formula2_COMUNES_REPRESENTANTE_TIPONUM`
- Portal: `.formula2_COMUNES_REPRESENTANTE_PORTAL`
- Escalera: `.formula2_COMUNES_REPRESENTANTE_ESCALERA`
- Planta: `.formula2_COMUNES_REPRESENTANTE_PLANTA`
- Puerta: `.formula2_COMUNES_REPRESENTANTE_PUERTA`
- C.P.: `.formula2_COMUNES_REPRESENTANTE_CODPOSTAL`
- Municipio: `.formula2_COMUNES_REPRESENTANTE_MUNICIPIO`
- Provincia (select): `.formula2_COMUNES_REPRESENTANTE_PROVINCIA`
- Pais (select): `.formula2_COMUNES_REPRESENTANTE_PAIS`
- Email: `.formula2_COMUNES_REPRESENTANTE_EMAIL`
- Movil: `.formula2_COMUNES_REPRESENTANTE_MOVIL`
- Telefono: `.formula2_COMUNES_REPRESENTANTE_TELEFONO`

---

## 5 - Datos a efectos de notificacion

El PDF indica rellenar todos los campos de esta zona.

### 5.1 - Botones de copia (si se quiere pre-rellenar)

Existen botones para copiar los datos desde interesado o representante:

```html
<input type="submit" value="Copiar datos del interesado">
<input type="submit" value="Copiar datos del representante">
```

Recomendacion:

- Si se usa uno de estos botones, esperar recarga completa del DOM (`domcontentloaded`) antes de seguir rellenando.

### 5.2 - Identificacion (depende del tipo de documento)

Campos:

- Tipo doc (select): `.formula2_COMUNES_NOTIFICACION_TIPODOC` (NIF/NIE/Pasaporte)
- Numero doc: `.formula2_COMUNES_NOTIFICACION_NUMIDENT`
- Nombre: `.formula2_COMUNES_NOTIFICACION_NOMBRE`
- Apellido1: `.formula2_COMUNES_NOTIFICACION_APELLIDO1`
- Apellido2: `.formula2_COMUNES_NOTIFICACION_APELLIDO2`
- Razon social: `.formula2_COMUNES_NOTIFICACION_RAZONSOCIAL`

Punto clave (nota del PDF):

- Si se elige `NIF` normalmente es persona juridica -> suele tener sentido rellenar `Razon social`.
- Si se elige `NIE` o `Pasaporte` normalmente es persona fisica -> suele tener sentido rellenar `Nombre` y `Apellidos`.

Ademas, el propio HTML avisa de que al abandonar el campo de tipo documento se dispara un refresco completo:

```html
<p class="ariaDescribedby">Al abandonar el campo actual se provocara un refresco completo de la pagina</p>
```

Por tanto, tras seleccionar el tipo de documento, esperar recarga/actualizacion antes de rellenar el resto.

### 5.3 - Domicilio y contacto de notificacion

Campos principales (segun `explore-html/formulario-madrid.html`):

- Pais (select): `.formula2_COMUNES_NOTIFICACION_PAIS`
- Provincia (select): `.formula2_COMUNES_NOTIFICACION_PROVINCIA`
- Municipio: `.formula2_COMUNES_NOTIFICACION_MUNICIPIO`
- Tipo via (select): `.formula2_COMUNES_NOTIFICACION_TIPOVIA`
- Domicilio / nombre via: `.formula2_COMUNES_NOTIFICACION_NOMBREVIA`
- Tipo numeracion (select): `.formula2_COMUNES_NOTIFICACION_TIPONUM`
- Numero: `.formula2_COMUNES_NOTIFICACION_NUMERO`
- Portal: `.formula2_COMUNES_NOTIFICACION_PORTAL`
- Escalera: `.formula2_COMUNES_NOTIFICACION_ESCALERA`
- Planta: `.formula2_COMUNES_NOTIFICACION_PLANTA`
- Puerta: `.formula2_COMUNES_NOTIFICACION_PUERTA`
- C.P.: `.formula2_COMUNES_NOTIFICACION_CODPOSTAL`
- Email: `.formula2_COMUNES_NOTIFICACION_EMAIL`
- Movil: `.formula2_COMUNES_NOTIFICACION_MOVIL`
- Telefono: `.formula2_COMUNES_NOTIFICACION_TELEFONO`

---

## 6 - Naturaleza del escrito

Seleccionar una de estas opciones (el PDF indica que solo se contemplan 3 casos):

- Alegacion
- Recurso
- Identificacion del conductor/a

Radios (ids):

```html
<input type="radio" id="GESTION_MULTAS_NATURALEZA_1" value="A"> <!-- Alegacion -->
<input type="radio" id="GESTION_MULTAS_NATURALEZA_2" value="R"> <!-- Recurso -->
<input type="radio" id="GESTION_MULTAS_NATURALEZA_3" value="I"> <!-- Identificacion conductor/a -->
```

Punto clave: al cambiar naturaleza tambien hay `refresh_method`, asi que tras seleccionar, esperar estabilizacion del DOM.

---

## 7 - Expone y solicita

Rellenar los dos textarea obligatorios:

```html
<textarea class="formula2_GESTION_MULTAS_EXPONE" aria-required="true"></textarea>
<textarea class="formula2_GESTION_MULTAS_SOLICITA" aria-required="true"></textarea>
```

---

## 8 - Guardar borrador / Continuar

Botones al final del formulario:

```html
<input name="guardar_borrador" type="submit" value="Guardar Borrador">
<input id="formDesigner:_id699" type="submit" value="Continuar">
```

Recomendacion:

- Usar "Continuar" para avanzar a la pantalla de adjuntos.
- Tras el click, esperar navegacion/recarga (`domcontentloaded`) y validar que hemos cambiado de pantalla (URL o elemento estable de la pantalla de adjuntos).
