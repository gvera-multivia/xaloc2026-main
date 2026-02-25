# Incidencia Firma Programatica (Ayunta Palma)

## Contexto
- Sitio: `ayunta_palma`
- Protocolos afectados: `P1` y `P2`
- Entorno principal de ejecucion: Docker/Linux (runner Playwright)
- Punto de fallo: fase de firma al pulsar `Signar tots els documents`

## Objetivo
Conseguir firma completamente programatica en Linux/Docker, sin interaccion manual, evitando el popup del navegador (`Open xdg-open?`) y continuando el flujo hasta confirmacion + justificante.

## Problema Actual
- El flujo llega correctamente a la pantalla/modal de firma.
- Al intentar disparar la firma:
  - o bien no se captura la URL `afirma://...` dentro del timeout;
  - o aparece el popup de protocolo externo `Open xdg-open?` y el flujo queda bloqueado.
- Resultado final en worker: `Runner 500` con timeout de captura de `afirma://`.

Error recurrente:
- `[AP-FIRMA] Timeout: URL afirma:// no capturada en 45000ms`

## Evidencias Relevantes
- En consola manual del navegador se observa:
  - `Iniciando cliente @firma`
  - `Launched external handler for 'afirma://sign?...'`
- Esto confirma que la web SI genera la URL `afirma://`.
- Captura visual recurrente: dialogo de Chromium/Edge en Linux
  - `Open xdg-open?`
  - origen: `https://palma.sedipualba.es wants to open this application`

## Lo que se intento (resumen)

### 1) Flags de navegador / protocolo externo
- Cambios en `core/base_automation.py`:
  - `--disable-features=ExternalProtocolDialog`
  - `--disable-popup-blocking`
  - merge robusto de `--disable-features` para no perder otras flags (`TranslateUI`)
- Resultado:
  - No elimina de forma fiable el popup `Open xdg-open?` en este flujo.

### 2) Interceptores JS de `afirma://` en frames
- En `sites/ayunta_palma/flows/firma_programatica.py`:
  - hooks sobre `window.open`, `location.assign`, `location.replace`, `Location.prototype.href`
  - captura en clicks de enlaces y `HTMLAnchorElement.click`
  - escaneo fallback de DOM (`a[href^='afirma://']` e `input hidden` con valor `afirma://`)
- Resultado:
  - Insuficiente en casos donde el navegador deriva a handler externo y no deja traza util en el mismo contexto JS.

### 3) Inyeccion global temprana
- `context.add_init_script(_INTERCEPT_SCRIPT)` para cubrir nuevas paginas/frames/postbacks.
- Reinyeccion continua en nuevos frames del contexto.
- Resultado:
  - Mejora cobertura, pero sigue habiendo timeouts en casos reales.

### 4) Captura por consola Playwright
- Listener `page.on("console")` en todas las paginas del contexto.
- Extraccion regex de `afirma://...` desde mensajes tipo:
  - `Launched external handler for 'afirma://...'`
- Resultado esperado:
  - Fallback robusto cuando falla captura por hooks JS.
- Estado observado:
  - Aun aparecen ejecuciones con timeout (pendiente verificar despliegue/imagen y logs de esta ruta en produccion).

### 5) Estrategias de click en boton de firma
- Se probaron varias:
  - click Playwright “trusted” en boton visible;
  - click via JS `el.click()`;
  - fallback a submit oculto (`btnFirmar`) opcional;
  - reintentos periodicos.
- Resultado:
  - Con reintentos agresivos se detecto bucle de carga/click.
  - Se limito para evitar bucles (`max retry clicks` bajo/0).
  - Manualmente el click abre popup `Open xdg-open?`, confirmando que ese boton realmente dispara protocolo externo.

## Lo que SI se ha conseguido
- Flujo estable hasta llegar a firma.
- Diagnostico mas completo:
  - logs de candidatos de click por frame/pagina;
  - trazas de captura (`source`, `frame_url`, `page_url`);
  - trazas de timeout por frame (`has_anchor`, `has_hidden`, `readyState`).
- Reduccion de esperas innecesarias en fase de representante.
- Control de reintentos para evitar bucles de recarga.

## Bloqueo tecnico actual
- El navegador en Linux sigue mostrando `Open xdg-open?` en situaciones donde deberia capturarse internamente la URL `afirma://`.
- Aunque la web genera `afirma://`, no siempre se logra retener esa URL de forma consistente dentro del flujo automatizado antes de que el handler externo tome control.

## Que queremos conseguir (criterio de exito)
1. Capturar siempre la URL `afirma://` (por hooks JS o por consola).
2. Firmar con CLI (`autofirma`) usando PFX en contenedor.
3. Inyectar firma en `hfFirma` (o equivalente) y enviar formulario.
4. Cerrar modal de firma y continuar sin popup externo ni accion manual.
5. Llegar a confirmacion/justificante de forma totalmente automatica.

## Estado actual (corto)
- Estado: **bloqueado en la captura estable de `afirma://` bajo popup externo `xdg-open`**.
- Impacto: tareas `P1/P2` fallan por timeout en fase de firma.

## Lineas de investigacion externas (aportadas)
- El popup `Open xdg-open?` es coherente con Chromium/Edge en Linux al abrir protocolos externos (`afirma://`).
- Los flags sueltos de Chromium no son una mitigacion estable para este caso de seguridad.
- Politica candidata de navegador: `AutoLaunchProtocolsFromOrigins` (permitir `protocol=afirma` solo para `https://palma.sedipualba.es`).
- Registro de handler XDG recomendado:
  - `.desktop` con `MimeType=x-scheme-handler/afirma;`
  - `xdg-mime default ... x-scheme-handler/afirma`
- Parser de URL `afirma://` a revisar:
  - no depender solo de `params` JSON;
  - cubrir variantes con `dat`, `properties`, `fileid`, `rtservlet`, `stservlet`.

## Cambio estructural aplicado
- Se movio la preparacion de captura `afirma://` al inicio del contexto (antes del login), no solo en la fase final de firma:
  - `sites/ayunta_palma/flows/firma_programatica.py`: `preparar_captura_afirma_context(...)`
  - `sites/ayunta_palma/automation.py`: llamada al inicio de `ejecutar_flujo_completo(...)`
- Objetivo del cambio: reducir carreras de inicializacion de scripts/listeners cuando el flujo de firma abre/modifica frames rapidamente.

## Cambio de plataforma aplicado (Docker)
- `infra/docker/playwright-runner-entrypoint.sh`:
  - escribe politica `AutoLaunchProtocolsFromOrigins` para `protocol=afirma` y origen `https://palma.sedipualba.es` (configurable por env);
  - registra `x-scheme-handler/afirma` con un handler propio.
- `infra/docker/afirma-handler.sh`:
  - captura la URI `afirma://...` en `/tmp/xaloc_afirma_uri.latest` y log en `/tmp/xaloc_afirma_uri.log`.
- `sites/ayunta_palma/flows/firma_programatica.py`:
  - añade fallback de captura leyendo `/tmp/xaloc_afirma_uri.latest` cuando falla captura por JS/consola.
