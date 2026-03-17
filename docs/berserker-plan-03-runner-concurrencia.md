# Fase 3: Runner Playwright sin lock global

## Problema actual

`services/playwright_runner/app.py` linea 19:

```python
_EXECUTE_LOCK = asyncio.Lock()
```

Linea 117:

```python
async with _EXECUTE_LOCK:
    outcome = await execute_browser_flow(...)
```

Esto serializa todas las ejecuciones dentro de un mismo runner. Aunque lleguen 4 requests, se procesan de 1 en 1.

## Solucion con replicas: mantener el lock

**Decision de diseno: NO quitar el lock.** Cada replica de runner procesa 1 tramite a la vez. Con 4 replicas = 4 tramites en paralelo.

Razones:
- Un Xvfb con un display comparte framebuffer. Dos browsers en el mismo display se pisan visualmente (clicks, screenshots, seleccion de archivos).
- El perfil del navegador Chromium no soporta acceso concurrente al mismo User Data Directory.
- Mantener 1 tramite por runner simplifica debugging (VNC muestra exactamente que esta pasando).

## Cambios necesarios

### 1. Hacer el runner escalable (preparacion para Fase 5)

El runner no necesita cambios de codigo para soportar N replicas. El lock se mantiene dentro de cada replica.

### 2. Anadir endpoint /info para identificar la replica

Util para debugging y dashboards:

```python
import os

@app.get("/info")
def info() -> dict:
    return {
        "status": "ok",
        "hostname": os.getenv("HOSTNAME", "unknown"),
        "container_id": os.getenv("HOSTNAME", "unknown"),
    }
```

### 3. Logging con identificador de replica

Anadir hostname al log format para saber que replica procesa cada request:

```python
file_handler.setFormatter(
    logging.Formatter(
        f"%(asctime)s - [PLAYWRIGHT-RUNNER:{os.getenv('HOSTNAME', '?')[:12]}] - %(levelname)s - %(message)s"
    )
)
```

## Alternativa descartada: quitar el lock y usar concurrencia interna

Se descarta por:
1. Un display Xvfb no soporta 2 browsers simultaneos de forma fiable (clicks se van a la ventana equivocada).
2. Se necesitarian N displays (:99, :100, :101, :102) y N gestores de ventanas.
3. Aumenta la complejidad sin beneficio sobre replicas Docker.
4. No se puede hacer `--scale` si el contenedor tiene `DISPLAY=:99` compartido entre procesos.

## Ficheros a modificar

| Fichero | Cambio |
|---------|--------|
| `services/playwright_runner/app.py` | Endpoint `/info`, mejorar logging |

## Test de validacion

1. Levantar 1 runner, enviar 2 requests simultaneas: la segunda espera al lock (comportamiento actual, sin regresion).
2. Levantar 2 runners (Fase 5), enviar 2 requests: cada uno procesa 1 en paralelo.
