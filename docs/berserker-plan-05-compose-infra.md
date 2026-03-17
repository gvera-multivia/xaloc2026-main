# Fase 5: Docker Compose — infraestructura para replicas

## Problemas actuales que bloquean --scale

### 1. container_name fijo

`docker-compose.microservices.yml` lineas 279 y 312:

```yaml
worker-orchestrator-service:
  container_name: xaloc-worker-orchestrator  # BLOQUEA scale

playwright-runner-service:
  container_name: xaloc-playwright-runner     # BLOQUEA scale
```

Docker Compose no permite `--scale` si el servicio tiene `container_name` — cada replica necesita un nombre unico.

### 2. Puertos host fijos en runner

```yaml
ports:
  - "8111:8111"  # Solo 1 contenedor puede bindear al puerto host
  - "6080:6080"
  - "5900:5900"
  - "9222:9222"
```

Con N replicas, solo la primera puede bindear al puerto host. Las demas fallan.

### 3. Worker con depends_on a un solo runner

```yaml
worker-orchestrator-service:
  depends_on:
    playwright-runner-service:
      condition: service_started
```

Esto funciona con replicas (Docker espera a que al menos 1 replica este started).

## Solucion: docker-compose.berserker.yml (override)

Crear un fichero override que se usa **solo** cuando se quiere berserker. No se modifica el compose base.

### Fichero: `infra/docker/docker-compose.berserker.yml`

```yaml
# Override para modo berserker x4
# Uso: docker compose -f docker-compose.microservices.yml -f docker-compose.berserker.yml up --scale worker-orchestrator-service=4 --scale playwright-runner-service=4

services:
  worker-orchestrator-service:
    container_name: ""  # Vaciar para permitir scale
    environment:
      WORKER_ENFORCE_SINGLETON: "0"
      BERSERKER_MODE: "1"

  playwright-runner-service:
    container_name: ""  # Vaciar para permitir scale
    ports: []           # Eliminar bindings al host
    # VNC y noVNC solo para debug — se acceden via docker exec o port dinamic
```

### Exponer VNC de forma dinamica (opcional)

Si se necesita ver las replicas via VNC, dos opciones:

**Opcion A: puertos dinamicos (recomendada)**

```yaml
playwright-runner-service:
  ports:
    - "6080"    # Docker asigna puerto host aleatorio
    - "5900"    # Consultar con: docker compose port playwright-runner-service 6080
```

Consultar puertos asignados:
```bash
docker compose -f ... port --index=1 playwright-runner-service 6080
docker compose -f ... port --index=2 playwright-runner-service 6080
```

**Opcion B: proxy reverso con path-based routing**

Usar Caddy/nginx para rutear `/vnc/1`, `/vnc/2`, etc. a cada replica. Mas complejo, no necesario inicialmente.

### API gateway a los runners (opcional)

El worker accede a `http://playwright-runner-service:8111/execute`. Con replicas, Docker Compose DNS resuelve round-robin. **No se necesita load balancer adicional.**

### Healthcheck sin container_name

El healthcheck actual funciona sin cambios — cada replica ejecuta su propio health check independiente.

### Autoheal

`autoheal` monitoriza contenedores con `label: autoheal=true`. Funciona con replicas — si una replica falla el healthcheck, autoheal la reinicia.

## Script de arranque berserker

### `scripts/berserker_up.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

CONCURRENCY="${BERSERKER_CONCURRENCY:-4}"
COMPOSE_DIR="$(cd "$(dirname "$0")/../infra/docker" && pwd)"

echo "[berserker] Levantando stack con $CONCURRENCY workers y $CONCURRENCY runners..."

docker compose \
  -f "$COMPOSE_DIR/docker-compose.microservices.yml" \
  -f "$COMPOSE_DIR/docker-compose.berserker.yml" \
  up -d \
  --scale worker-orchestrator-service="$CONCURRENCY" \
  --scale playwright-runner-service="$CONCURRENCY"

echo "[berserker] Stack levantado. Verificando replicas..."
docker compose \
  -f "$COMPOSE_DIR/docker-compose.microservices.yml" \
  -f "$COMPOSE_DIR/docker-compose.berserker.yml" \
  ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
```

### `scripts/berserker_down.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")/../infra/docker" && pwd)"

echo "[berserker] Deteniendo stack berserker..."
docker compose \
  -f "$COMPOSE_DIR/docker-compose.microservices.yml" \
  -f "$COMPOSE_DIR/docker-compose.berserker.yml" \
  down
```

## Recursos del host

### CPU y RAM para 4 runners

Cada runner con Playwright + Chromium + Xvfb consume aprox:
- **CPU**: 1-2 cores durante ejecucion activa, ~0 en idle
- **RAM**: 500MB-1.2GB por contenedor (Chromium es el principal consumidor)

Para 4 runners: **4-8 cores y 2-5GB RAM** disponibles.

Recomendacion: limitar en compose si el host tiene recursos ajustados:

```yaml
playwright-runner-service:
  deploy:
    resources:
      limits:
        cpus: "2.0"
        memory: 1.5G
```

### Disco

Cada job usa tmp aislado (Fase 1). Los archivos son PDFs pequenos (<10MB). 4 jobs concurrentes = ~40MB temporales max. No hay riesgo de disco.

## Ficheros a crear/modificar

| Fichero | Accion |
|---------|--------|
| `infra/docker/docker-compose.berserker.yml` | Crear (override) |
| `scripts/berserker_up.sh` | Crear |
| `scripts/berserker_down.sh` | Crear |
| `infra/docker/docker-compose.microservices.yml` | NO modificar — el override lo gestiona |

## Test de validacion

1. `docker compose -f ... -f ... config` — verificar que el merge es correcto.
2. Levantar con `--scale=2` y verificar que hay 2 replicas de cada servicio.
3. Verificar que los runners responden a `/health` desde el worker (via DNS interno).
4. Verificar que VNC es accesible (puertos dinamicos).
5. Levantar sin el override berserker: todo funciona como antes (1 runner, 1 worker).
