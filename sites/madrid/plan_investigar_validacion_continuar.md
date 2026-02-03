# Plan: investigar la validación al pulsar “Continuar” (Madrid / WFORS)

Objetivo: entender por qué, tras avanzar y volver atrás, el formulario acepta valores que antes marcaba como inválidos (p.ej. CP), y ajustar la automatización para comportarse como el flujo “correcto”.

> Nota de cumplimiento: no es apropiado intentar “desactivar” validaciones para enviar datos incorrectos. El enfoque recomendado es **diagnosticar** el origen de la diferencia y reproducir el comportamiento legítimo del flujo (mismo estado de sesión / misma secuencia de eventos) para que datos **válidos** no fallen por la automatización.

## Hipótesis a comprobar (sin suposiciones)

1) **Estado de sesión / server-side flags**: al pasar a la pantalla de adjuntos el servidor marca en sesión algo como “dirección normalizada/validada”, y al volver atrás relaja checks.
2) **Campos ocultos / tokens**: en “Continuar” se mandan inputs hidden adicionales que cambian entre el primer submit y el submit tras volver atrás.
3) **Eventos de UI no disparados**: manualmente se dispara una normalización/BDC (autocomplete) y en bot no, por eso falla CP o vía.
4) **Validación condicional**: los checks cambian según algún campo (p.ej. `TIPOVIA`, `PAIS`, `PROVINCIA`) o según el “paso” del motor WFORS.

## Qué capturar (evidencia)

### A) Captura de red (Network) en 2 escenarios

Escenario 1: rellenar “normal” → click “Continuar” (cuando falla).

Escenario 2: rellenar con datos que pasan → llegar a adjuntos → volver atrás → cambiar a datos “reales” → click “Continuar” (cuando pasa).

Para ambos escenarios, guardar:

- Todas las requests XHR/Fetch y POST del submit “Continuar”.
- “Copy as cURL” (sin cookies) y, sobre todo:
  - URL
  - método
  - payload (form data)
  - response (status + body si hay)

### B) Snapshot del DOM justo antes del submit

En ambos escenarios:

- HTML de `form#formDesigner`
- todos los `<input type="hidden">` y su valor
- valor + `class` de los campos sensibles: `NOMBREVIA`, `CODPOSTAL`, `MUNICIPIO`, `TIPOVIA`, `PROVINCIA`, `PAIS`

La idea es poder comparar “lo que se manda” y “en qué estado está el formulario” en cada caso.

## Comparación sistemática

1) **Diff de payloads** del submit “Continuar”:
   - ¿Aparece un flag nuevo tras volver atrás? (ej. `direccionNormalizada=true`, `validacionOk=true`, etc.)
   - ¿Cambia un token/`ViewState`/`controlFormulario`/`lastfieldsid`?
   - ¿Aparecen/ desaparecen campos hidden?
2) **Diff de estado del DOM**:
   - ¿Cambia la clase del input? (ej. `ui-autocomplete-loading`, `error`)
   - ¿Aparece algún hidden relacionado con dirección o BDC?
3) **Diff de secuencia de requests**:
   - ¿En el flujo “bueno” hay una llamada previa a `formClientServlet` que en el bot no ocurre?
   - ¿Se hace algún `POST`/`XHR` adicional al cambiar CP o vía?

## Acciones en el código (sin bypass)

### 1) Instrumentación en Playwright

Añadir logs temporales (solo en modo debug) para:

- loguear requests a:
  - `*/WFORS_WBWFORS/formClientServlet` (BDC)
  - endpoint del submit “Continuar” (el que cambie de pantalla)
- loguear (enmascarado) el payload de esos POSTs:
  - nombres de campos + longitud/si vacío, pero **sin** datos personales en claro.

### 2) Reproducir el “estado bueno” de forma legítima

Si el diff muestra que el submit “bueno” incluye un campo hidden/flag que se setea al:

- seleccionar una sugerencia del autocomplete,
- hacer blur/tab,
- esperar a que desaparezca `ui-autocomplete-loading`,
- o a que el servidor responda un XHR de validación,

entonces el bot debe:

- disparar exactamente esos eventos antes de pulsar “Continuar”,
- y esperar a que terminen los XHR relevantes.

### 3) Tratar el CP (código postal) como campo validado

Si CP falla en automático:

- confirmar si hay autocomplete/BDC también para CP o si depende de municipio/provincia.
- añadir una rutina de “validación pre-submit” parecida a `NOMBREVIA`:
  - escribir con tecleo (no `fill`)
  - esperar XHR/DOM update
  - comprobar ausencia de `span.textoError` y/o clase `error`

## Resultado esperado (criterios de éxito)

- El submit “Continuar” funciona con datos válidos sin depender del truco “ir y volver”.
- Si el usuario introduce datos realmente inválidos, el bot lo detecta y falla con un mensaje claro (campo + motivo), sin intentar forzar el submit.

## Próximo paso concreto

1) Identificar cuál es la request exacta del botón “Continuar” (URL + payload).
2) Capturar y comparar el payload del escenario 1 vs escenario 2.
3) Implementar en el flujo la condición que falta (eventos/esperas/campos) para igualar el escenario 2 **sin** pasar por adjuntos.

