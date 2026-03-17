# Modo Berserker x4 — Plan de accion

Fecha: 2026-03-17

## Objetivo

Escalar de 1 tramite simultaneo a 4 tramites en paralelo sin romper nada.

## Estado actual (serializado)

| Punto de serializacion | Fichero | Mecanismo |
|------------------------|---------|-----------|
| Runner Playwright | `services/playwright_runner/app.py:19` | `_EXECUTE_LOCK = asyncio.Lock()` |
| Worker singleton | `core/worker/consumer.py:61` | `WORKER_ENFORCE_SINGLETON=1` + `pg_try_advisory_lock` |
| Limpieza tmp global | `core/worker_execution/task_orchestrator.py:370-393` | `_cleanup_tmp_workspace()` borra todo `tmp/` |
| AutoFirma rutas fijas | `infra/docker/afirma-handler.sh:28-31` | `/tmp/xaloc_afirma_uri.latest`, `.log`, `.pid`, `.ready` |
| container_name fijo | `infra/docker/docker-compose.microservices.yml:312` | `container_name: xaloc-playwright-runner` bloquea `--scale` |
| Puertos host fijos | `docker-compose.microservices.yml:369-373` | `8111:8111`, `6080:6080`, `5900:5900` impiden replicas |
| Perfil navegador compartido | `core/worker_execution/browser_executor.py:72` | `profiles/worker` unico para sites con `keep_browser_open` |

## Lo que YA funciona para concurrencia

- Cola Redis Streams con XREADGROUP + XACK + XAUTOCLAIM (multiples consumers OK)
- Dedupe por recurso con SET NX EX (sin duplicados de idRecurso)
- Reconciliacion processing con FOR UPDATE SKIP LOCKED
- Perfiles efimeros ya implementados para Valencia y sites con `XALOC_DISABLE_KEEP_BROWSER_OPEN=1`

## Estrategia: replicar horizontal, no concurrencia interna

**No** vamos a meter asyncio.gather ni hilos dentro de un runner. Vamos a levantar N replicas identicas e independientes:

```
[Redis Streams cola "jobs"]
       |
   XREADGROUP (consumer_id distinto por worker)
       |
  +---------+---------+---------+
  |         |         |         |
worker-1  worker-2  worker-3  worker-4
  |         |         |         |
runner-1  runner-2  runner-3  runner-4
  |         |         |         |
Xvfb :99  Xvfb :99  Xvfb :99  Xvfb :99
(cada contenedor con su display)
```

Cada worker habla con SU runner via red Docker interna. No comparten nada.

## Fases del plan

| Fase | Doc | Riesgo si se salta | Esfuerzo |
|------|-----|--------------------|----------|
| 1. Aislamiento tmp por job | [01-aislamiento-tmp.md](berserker-plan-01-aislamiento-tmp.md) | Alto: borrado cruzado de archivos | Bajo |
| 2. Aislamiento firma por job | [02-aislamiento-firma.md](berserker-plan-02-aislamiento-firma.md) | Alto: firma de un job pisa a otro | Medio |
| 3. Runner sin lock + escalable | [03-runner-concurrencia.md](berserker-plan-03-runner-concurrencia.md) | Medio: runner sigue serializado | Bajo |
| 4. Worker sin singleton + N workers | [04-worker-escalado.md](berserker-plan-04-worker-escalado.md) | Medio: solo 1 worker activo | Bajo |
| 5. Compose infra (scale, puertos, VNC) | [05-compose-infra.md](berserker-plan-05-compose-infra.md) | Bloquea: no se pueden levantar replicas | Medio |
| 6. Validacion y rollback | [06-validacion.md](berserker-plan-06-validacion.md) | — | Medio |

## Orden de ejecucion obligatorio

```
Fase 1 ──> Fase 2 ──> Fase 3 + Fase 4 (paralelo) ──> Fase 5 ──> Fase 6
```

Las fases 3 y 4 son independientes entre si, pero ambas dependen de 1 y 2.
La fase 5 (Compose) se aplica al final porque es el "interruptor" que levanta las replicas.
La fase 6 valida todo junto.

## Variables de entorno del modo berserker

```env
# Activar modo berserker (default: 0)
BERSERKER_MODE=1
BERSERKER_CONCURRENCY=4

# Desactivar singleton de worker
WORKER_ENFORCE_SINGLETON=0

# Cada worker habla con SU runner (via Docker DNS interno)
USE_PLAYWRIGHT_RUNNER_SERVICE=1
# PLAYWRIGHT_RUNNER_URL se resuelve por docker compose service name

# Aislamiento de tmp activado
XALOC_TMP_ISOLATION=1
```

## Principio de diseno: cero cambios si BERSERKER_MODE=0

Todo cambio se implementa detras de feature flags. Con `BERSERKER_MODE=0` (default), el sistema funciona exactamente igual que hoy. Esto permite rollback instantaneo.
