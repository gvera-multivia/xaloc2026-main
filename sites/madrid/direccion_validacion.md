# Validación y normalización de direcciones (Madrid / WFORS)

Este documento describe la mejor forma de **validar y normalizar** campos de dirección (especialmente `NOMBREVIA`) en el trámite de Madrid (WFORS), **sin “inventar” texto**: solo se aceptan valores **devueltos por el propio sistema**.

## Qué está pasando en el formulario

Al escribir en “Domicilio / Nombre vía” aparece un desplegable (jQuery UI Autocomplete) y, si el valor no existe, el formulario marca el campo como error (ej. `La calle introducida no es correcta`).

La fuente real de esas sugerencias no es el HTML: es una llamada a un endpoint backend:

- `POST https://servcla.madrid.es/WFORS_WBWFORS/formClientServlet`
- `content-type: application/x-www-form-urlencoded`
- `response: application/json`

Parámetros observados (DevTools → Network → XHR/Fetch):

- `elemento`: identifica el campo (ej. `COMUNES_NOTIFICACION_NOMBREVIA`)
- `valor`: lo que se va tecleando (ej. `CHA`)
- `recargaBDC`: `true/false`
- `mapaIdName`: JSON con el estado del formulario (pares `["CAMPO","VALOR"]`)

La respuesta observada es un JSON tipo diccionario:

```json
{
  "CHAMBERI  [PLAZA]": "CHAMBERI  [PLAZA]",
  "CHAMARTIN  [MERCADO]": "CHAMARTIN  [MERCADO]"
}
```

## Por qué hay “incongruencias” al escribir calles

Estas son las variaciones típicas que causan que un “texto humano” no coincida con el “texto válido” del sistema:

1) **Tildes/diacríticos**: `CHAMBERÍ` vs `CHAMBERI`.
2) **Puntuación y comas**: `GENERAL MITRE, DEL` vs `GENERAL MITRE DEL`.
3) **Abreviaturas/sinónimos**: `PZA` vs `PLAZA`, `AVDA` vs `AVENIDA`, `C/` vs `CALLE`.
4) **Artículos/preposiciones**: `DE`, `DEL`, `LA`, `LAS`, etc. (a veces el sistema las mueve o las separa con coma).
5) **Orden distinto**: el sistema puede expresar el tipo de vía como sufijo en corchetes:
   - usuario: `PLAZA DE CHAMBERI`
   - sistema: `CHAMBERI  [PLAZA]`
6) **Topónimos “especiales”**: estaciones/mercados/parques/etc. con etiquetas `[ESTACION]`, `[MERCADO]`, `[PARQUE]`, etc.
7) **Contexto del formulario**: municipio/provincia/tipo de vía ya seleccionados pueden afectar qué devuelve BDC.

## Objetivo: 0 invenciones, 100% seleccionable

La regla operativa recomendada es:

- **Nunca** enviar un texto “libre” como definitivo.
- **Siempre** elegir una opción que el sistema te ofrece (autocomplete/BDC).
- Si no hay opción suficientemente buena → **fallar temprano** y pedir revisión (o reintentar con otra estrategia), en vez de “forzar”.

## Estrategia recomendada (mejor práctica)

### 1) Separar “tipo de vía” y “nombre”

Si el formulario tiene `TIPOVIA` (PLAZA, CALLE, AVENIDA…), **rellénalo primero**. Luego valida `NOMBREVIA`.

Esto evita intentar meter `PLAZA DE ...` dentro de `NOMBREVIA` cuando el sistema lo espera como `... [PLAZA]`.

### 2) Prevalidar contra BDC antes de rellenar

Antes de escribir en el input, hacer una consulta a BDC con:

- `elemento = ..._NOMBREVIA` del bloque correspondiente (ej. `COMUNES_NOTIFICACION_NOMBREVIA`)
- `valor =` prefijo (3–5 letras) del nombre de vía normalizado (sin acentos, mayúsculas)
- `mapaIdName =` estado actual del formulario (incluye municipio/tipovia, etc.)

Con eso obtienes el catálogo de sugerencias válido **para ese contexto**.

En este repo hay un helper para llamarlo desde Playwright (reusa cookies/sesión del navegador):

- `sites/madrid/bdc.py` (`bdc_sugerencias_desde_pagina`)

### 3) Elegir la mejor sugerencia con reglas explícitas

Como la respuesta incluye strings del estilo `NOMBRE  [TIPO]`, la selección debe:

1) Normalizar texto (sin tildes, mayúsculas, colapsar espacios, quitar puntuación “no esencial”).
2) Puntuar candidatos por similitud:
   - match por inclusión del “core” del nombre (tokens)
   - penalizar candidatos demasiado largos si empatan
3) Si tienes `TIPOVIA` seleccionado, **priorizar** candidatos cuyo `[TIPO]` coincida (o al menos contenga un equivalente).

Muy importante: el resultado final debe ser **exactamente una de las sugerencias** devueltas.

### 4) Rellenar el input seleccionando la sugerencia (no solo “escribir”)

Incluso si prevalidas, en UI lo más seguro es:

- teclear el valor (o parte)
- esperar el desplegable
- hacer click en la sugerencia elegida (o `ArrowDown` + `Enter` como fallback)
- forzar `blur` (p.ej. `Tab`) para que dispare validación

En este repo ya se aplica esta idea en:

- `sites/madrid/flows/formulario.py` (relleno con autocomplete + validación de error)

### 5) Verificación final: “no hay error”

Después de seleccionar sugerencia:

- comprobar que el input no queda con clase `error`
- comprobar que no aparece `span.textoError` (ej. “La calle introducida no es correcta”)

Si falla, abortar la ejecución: evita continuar con una dirección inválida.

## Estrategias de reintento (sin inventar)

Cuando no hay sugerencias o no hay un match claro:

1) **Cambiar `valor`**:
   - usar otro prefijo (primeras 3 letras “útiles”)
   - eliminar palabras vacías (`DE`, `DEL`, `LA`) para construir el prefijo
2) **Reconsultar con el formulario en el estado correcto**:
   - asegurar `MUNICIPIO` y `TIPOVIA` están fijados antes de pedir `NOMBREVIA`
3) **Aumentar tolerancia de coincidencia**, pero siempre eligiendo una sugerencia:
   - token set matching (por tokens) en vez de igualdad exacta
4) Si aun así no hay match:
   - **fallar temprano** y registrar el listado de sugerencias devueltas para revisión humana.

## Recomendación práctica para “PLAZA DE CHAMBERI”

1) En `TIPOVIA` seleccionar `PLAZA`.
2) En `NOMBREVIA` buscar por `CHA` (o `CHAM`).
3) Elegir `CHAMBERI  [PLAZA]`.
4) Insertar seleccionando el autocomplete, y validar que no queda error.

Esto evita “inventar” `PLAZA DE CHAMBERI` cuando el sistema realmente quiere `CHAMBERI  [PLAZA]`.

## Nota de seguridad y privacidad

El `mapaIdName` incluye datos personales del formulario. Evita:

- guardar payloads crudos en logs
- pegar cookies o sesiones en tickets/chats

Si necesitas depurar, enmascara valores sensibles o guarda solo los nombres de campos y longitudes.

