# Fase 4: Worker sin singleton + N workers

## Problema actual

`core/worker/consumer.py` linea 61:

```python
enforce_singleton = (os.getenv("WORKER_ENFORCE_SINGLETON") or "1").strip().lower() in {"1", "true", "yes", "on"}
```

Con `WORKER_ENFORCE_SINGLETON=1` (default), solo 1 worker puede estar activo. Los demas quedan en bucle esperando el lock de Postgres (`pg_try_advisory_lock`).

## Solucion: desactivar singleton y resolver colisiones

### 1. Variable de entorno

```env
WORKER_ENFORCE_SINGLETON=0
```

Con esto, multiples workers pueden correr en paralelo. Redis Streams con XREADGROUP + consumer_id distinto ya asegura que cada job se entrega a un solo consumer.

### 2. Cada worker habla con SU runner

Hoy el worker usa `PLAYWRIGHT_RUNNER_URL=http://playwright-runner-service:8111`. Con replicas Docker, el DNS `playwright-runner-service` hace round-robin entre las replicas.

**Opcion A (simple, recomendada):** Mantener round-robin DNS. Cada request del worker va a una replica libre.

**Opcion B (afinidad 1:1):** Cada worker-N habla con runner-N. Requiere mas configuracion Compose. Descartada por complejidad innecesaria — el lock del runner ya serializa dentro de cada replica, y el round-robin DNS distribuye naturalmente.

### 3. Cada worker tiene su worker_instance_id unico

Ya implementado en `consumer.py` linea 58:

```python
worker_instance_id = f"worker-{uuid.uuid4().hex}"
```

Esto permite que el sistema de heartbeat y reconciliacion distinga N workers simultaneos.

### 4. Evitar colision en queue consumer group

Redis Streams con `XREADGROUP` ya soporta multiples consumers en el mismo grupo. Cada worker llama a `reserve()` con su `worker_id` como consumer name. El stream entrega cada mensaje a **un solo consumer** del grupo. No hay duplicados.

Evidencia: `core/redis_streams_queue_gateway.py` linea 110, 266 — usa `XREADGROUP GROUP worker_group {worker_id}`.

### 5. Reconciliacion de processing sigue funcionando

La reconciliacion (`reconcile_processing_with_worker_runtime`) usa `FOR UPDATE SKIP LOCKED` para no interferir entre workers. Cada worker reconcilia jobs cuyos workers estan muertos (heartbeat_timeout). Con N workers, si uno muere, los demas reclaman sus jobs pendientes.

## Cambios necesarios

### En docker-compose (Fase 5)

```yaml
worker-orchestrator-service:
  # Quitar container_name para permitir --scale
  # container_name: xaloc-worker-orchestrator  # ELIMINADO
  environment:
    WORKER_ENFORCE_SINGLETON: "0"
```

### En consumer.py — anadir hostname al logger

```python
import socket
worker_instance_id = f"worker-{socket.gethostname()[:12]}-{uuid.uuid4().hex[:8]}"
```

Esto permite trazar en logs que contenedor procesa cada job.

## Interaccion worker-runner con round-robin

```
worker-1 ──POST /execute──> runner-2 (le toco por DNS round-robin)
worker-2 ──POST /execute──> runner-1 (le toco por DNS round-robin)
worker-3 ──POST /execute──> runner-3 (le toco por DNS round-robin)
worker-4 ──POST /execute──> runner-4 (le toco por DNS round-robin)
```

Si un runner esta ocupado (lock adquirido), el request queda en espera dentro del runner hasta que el lock se libere. No se pierde — simplemente tarda mas. Pero con 4 workers y 4 runners, la probabilidad de espera es baja.

## Ficheros a modificar

| Fichero | Cambio |
|---------|--------|
| `core/worker/consumer.py` | Hostname en worker_instance_id |
| `infra/docker/docker-compose.microservices.yml` | `WORKER_ENFORCE_SINGLETON=0` (Fase 5) |

## Test de validacion

1. Con `WORKER_ENFORCE_SINGLETON=0`, levantar 2 workers. Verificar que ambos procesan jobs (no se bloquean mutuamente).
2. Encolar 4 jobs. Con 4 workers, verificar que los 4 se procesan simultaneamente.
3. Matar 1 worker abruptamente. Verificar que su job pendiente se reconcilia y otro worker lo toma.
4. Sin `BERSERKER_MODE` / con `WORKER_ENFORCE_SINGLETON=1`: comportamiento identico al actual.
