# Fase 2: Aislamiento del canal de firma por job/worker

## Problema actual

### 2a) afirma-handler.sh — rutas fijas en /tmp

`infra/docker/afirma-handler.sh` lineas 28-31:

```bash
log_file="${XALOC_AFIRMA_URI_LOG:-/tmp/xaloc_afirma_uri.log}"
latest_file="${XALOC_AFIRMA_URI_LATEST:-/tmp/xaloc_afirma_uri.latest}"
proxy_pid_file="${XALOC_AFIRMA_PROXY_PID:-/tmp/xaloc_afirma_proxy.pid}"
proxy_ready_file="${XALOC_AFIRMA_PROXY_READY:-/tmp/xaloc_afirma_proxy.ready}"
```

Con 4 runners en contenedores separados, esto **no es problema** si cada runner tiene su propio filesystem `/tmp`. Pero si se compartiera el mismo contenedor, 2 firmas concurrentes se pisarian.

### 2b) Valencia FIRe — canal in-process

Valencia ya usa `core/fire_signing_bridge.py` con `page.context.request` (cookies del browser). Esto es **intrinsecamente aislado por BrowserContext**. No requiere cambios para berserker.

### 2c) Palma — firma programatica via AutoFirma CLI

`sites/ayunta_palma/flows/firma_programatica.py` ejecuta `sign_with_pfx()` de `core/autofirma_signing_bridge.py`. Este firma con CLI y no usa archivos compartidos en `/tmp`. Es **seguro para concurrencia** siempre que cada invocacion use su propio archivo temporal (ya lo hace con tempfile).

### 2d) Redsara — proxy WebSocket

`sites/redsara/flows/firma_proxy.py` lanza `autofirma_proxy.py` que escucha en puertos especificos. Si dos tramites Redsara corren simultaneos en el **mismo contenedor**, ambos intentarian escuchar en el mismo puerto.

## Solucion por arquitectura de replicas

Con la estrategia de **1 runner por contenedor** (Fase 5), cada contenedor tiene:
- Su propio `/tmp` (filesystem aislado)
- Su propio Xvfb `:99`
- Su propia instancia de AutoFirma/proxy
- Sus propios puertos WebSocket internos

**No se necesita namespacing de archivos si cada runner vive en su contenedor.**

## Cambios necesarios (defensivos)

Aun con contenedores separados, es buena practica no depender de rutas fijas:

### 1. Parametrizar rutas de afirma-handler.sh por WORKER_ID

Si en el futuro se quisiera meter mas de 1 ejecucion por contenedor, preparar la infra:

```bash
# Opcion: las env vars ya permiten override, pero ponerlas con suffix
worker_suffix="${XALOC_WORKER_SUFFIX:-}"
log_file="${XALOC_AFIRMA_URI_LOG:-/tmp/xaloc_afirma_uri${worker_suffix}.log}"
latest_file="${XALOC_AFIRMA_URI_LATEST:-/tmp/xaloc_afirma_uri${worker_suffix}.latest}"
proxy_pid_file="${XALOC_AFIRMA_PROXY_PID:-/tmp/xaloc_afirma_proxy${worker_suffix}.pid}"
proxy_ready_file="${XALOC_AFIRMA_PROXY_READY:-/tmp/xaloc_afirma_proxy${worker_suffix}.ready}"
```

**Prioridad: baja.** Con contenedores separados no es estrictamente necesario.

### 2. Verificar que firma_proxy.py (Redsara) no abre puertos fijos conflictivos

El proxy WebSocket parsea los puertos de la URI `afirma://websocket?ports=X,Y,Z` y escucha en ellos. Como cada contenedor tiene su red interna, no hay conflicto. **No requiere cambios.**

### 3. Verificar que sign_with_pfx() usa temporales unicos

`core/autofirma_signing_bridge.py` deberia usar `tempfile.NamedTemporaryFile` o `tempfile.mkdtemp`. Verificar que no escribe a rutas fijas.

## Matriz de firma por site y riesgo berserker

| Site | Mecanismo de firma | Usa archivos /tmp fijos | Riesgo con N contenedores |
|------|--------------------|------------------------|---------------------------|
| Palma | AutoFirma CLI (`sign_with_pfx`) | No (usa tempfile) | Ninguno |
| Redsara | WebSocket proxy (`autofirma_proxy.py`) | Si, pero cada contenedor tiene su /tmp | Ninguno |
| Valencia | FIRe in-process (`fire_signing_bridge.py`) | No (usa browser session) | Ninguno |
| Madrid | No firma (solo upload) | N/A | Ninguno |
| Xaloc Girona | No firma en browser (sFTP/XVIA) | N/A | Ninguno |
| ATC | Pendiente de definir | — | Evaluar cuando se implemente |

## Ficheros a modificar

| Fichero | Cambio | Prioridad |
|---------|--------|-----------|
| `infra/docker/afirma-handler.sh` | Suffix opcional en rutas | Baja (defensivo) |
| `core/autofirma_signing_bridge.py` | Verificar uso de tempfile (audit) | Media (audit) |

## Test de validacion

1. Con 2 runners en contenedores separados, lanzar 2 firmas Palma simultaneas: ambas deben completarse sin error.
2. Con 2 runners, lanzar 2 firmas Redsara simultaneas: verificar que cada proxy escucha en su contenedor sin conflicto.
3. Valencia: 2 FIRe signing en paralelo — ya deberia funcionar por diseno.
