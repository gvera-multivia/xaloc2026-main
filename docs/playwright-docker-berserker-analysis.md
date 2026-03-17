# Analisis Docker Playwright y viabilidad de "modo berserker x4"

Fecha del analisis: 2026-03-17

## Resumen ejecutivo

- Estado actual: el sistema esta **serializado** en varios puntos criticos. Hoy no esta preparado para 4 tramites simultaneos de forma segura.
- Sobre los "4 desktops": en el contenedor hay **1 display Xvfb (`:99`)** y **Openbox con 4 workspaces virtuales**. Esos 4 workspaces no equivalen a 4 ejecuciones paralelas reales.
- Se puede habilitar un modo "berserker x4", pero requiere cambios de arquitectura para aislar runner/worker/tmp/firma y proteger escritura de documentos.

## Como funciona ahora mismo (local)

### 1) Topologia de servicios

- `worker-orchestrator-service` consume cola y llama al runner remoto.
- `playwright-runner-service` expone `POST /execute`.
- Redis Streams y Postgres llevan estado de cola y runtime.

Evidencia:
- `USE_PLAYWRIGHT_RUNNER_SERVICE=1` y `PLAYWRIGHT_RUNNER_URL=http://playwright-runner-service:8111` en [`infra/docker/docker-compose.microservices.yml`](../infra/docker/docker-compose.microservices.yml).
- Servicio runner en [`infra/docker/docker-compose.microservices.yml`](../infra/docker/docker-compose.microservices.yml) con `container_name: xaloc-playwright-runner`.

### 2) Runner Playwright serializado

- En `services/playwright_runner/app.py` hay lock global `_EXECUTE_LOCK = asyncio.Lock()`.
- Todas las ejecuciones pasan por `async with _EXECUTE_LOCK`.

Evidencia:
- [`services/playwright_runner/app.py`](../services/playwright_runner/app.py): lineas 19 y 117.

Impacto:
- Aunque lleguen multiples requests, el runner procesa de una en una.

### 3) Worker serializado (por defecto)

- `WORKER_ENFORCE_SINGLETON` default `1`.
- El worker adquiere `pg_try_advisory_lock` para que solo haya 1 worker activo.
- El loop procesa un job por iteracion (`reserve -> process_task -> ack/nack/release`).

Evidencia:
- [`core/worker/consumer.py`](../core/worker/consumer.py): lineas 61, 139, 216, 244.
- [`core/pg_runtime_store.py`](../core/pg_runtime_store.py): lineas 27 y 449.

### 4) Stack visual Docker

- `start-ui.sh` arranca un solo `Xvfb` con `-screen 0` en `DISPLAY=:99`, mas `openbox`, `x11vnc`, `websockify`.

Evidencia:
- [`infra/docker/start-ui.sh`](../infra/docker/start-ui.sh): lineas 5, 35, 51, 52, 56.

Runtime real observado:
- `docker exec xaloc-playwright-runner ps -ef` muestra un unico `Xvfb :99`.
- `docker exec xaloc-playwright-runner sh -lc "ls -la /tmp/.X11-unix"` muestra solo `X99`.
- `grep '<number>' /etc/xdg/openbox/rc.xml` devuelve `<number>4</number>` (4 workspaces de Openbox).

Conclusion sobre "4 desktops":
- Son 4 escritorios virtuales de Openbox, no 4 displays ni 4 pipelines aislados.

## Riesgos reales para "x4" que hoy romperian cosas

### 1) Limpieza global de `tmp` (riesgo alto)

- `process_task` borra todo `tmp` al finalizar cada tarea.
- Con concurrencia, una tarea puede borrar temporales de otra.

Evidencia:
- [`core/worker_execution/task_orchestrator.py`](../core/worker_execution/task_orchestrator.py): lineas 370-386 y 501.

### 2) Canal AutoFirma compartido en `/tmp` (riesgo alto)

- Handler/proxy usan rutas fijas globales (`/tmp/xaloc_afirma_uri.latest`, `.log`, `.pid`, `.ready`).
- Varios tramites firmando a la vez pueden pisarse.

Evidencia:
- [`infra/docker/autofirma_proxy.py`](../infra/docker/autofirma_proxy.py): lineas 48-51.
- [`infra/docker/afirma-handler.sh`](../infra/docker/afirma-handler.sh): lineas 28-31.
- [`sites/ayunta_palma/flows/firma_programatica.py`](../sites/ayunta_palma/flows/firma_programatica.py): lineas 1068-1069.

### 3) Guardado de justificantes no atomico (riesgo medio)

- Se calcula nombre libre con `exists()` y luego `copy2()`.
- En carrera, dos procesos podrian elegir el mismo nombre antes de copiar.

Evidencia:
- [`core/justificantes_storage.py`](../core/justificantes_storage.py): lineas 33, 37, 43, 87, 88.

### 4) Escalado Compose bloqueado por `container_name` (riesgo de despliegue)

- Con `container_name` en el runner, Compose no escala ese servicio a multiples replicas.

Evidencia local:
- [`infra/docker/docker-compose.microservices.yml`](../infra/docker/docker-compose.microservices.yml): linea 312.

## Lo que SI esta bien para concurrencia

- Cola Redis Streams con `XREADGROUP` + `XACK` + `XAUTOCLAIM` (patron correcto para consumidores concurrentes y recuperacion de pendientes).
- Dedupe por recurso con `SET NX EX` (`dedupe:resource:{site}:{resource}`).
- Reconciliacion de jobs `processing` con `FOR UPDATE SKIP LOCKED`.

Evidencia:
- [`core/redis_streams_queue_gateway.py`](../core/redis_streams_queue_gateway.py): lineas 110, 266, 279, 340.
- [`shared/queue/redis_streams.py`](../shared/queue/redis_streams.py): lineas 56, 101, 136.
- [`core/pg_runtime_store.py`](../core/pg_runtime_store.py): linea 549.

## Investigacion en internet (fuentes oficiales)

- Playwright (Python) indica para `launch_persistent_context` que los navegadores no permiten multiples instancias con el mismo `User Data Directory`:  
  https://playwright.dev/python/docs/api/class-browsertype
- Playwright recomienda aislamiento por BrowserContext para ejecucion paralela segura:  
  https://playwright.dev/python/docs/browser-contexts
- Redis Streams comandos de consumo/ack/recuperacion pendientes:  
  https://redis.io/docs/latest/commands/xreadgroup/  
  https://redis.io/docs/latest/commands/xack/  
  https://redis.io/docs/latest/commands/xautoclaim/
- Uvicorn opciones de concurrencia/procesos (`--workers`, `--limit-concurrency`):  
  https://www.uvicorn.org/settings/
- Docker Compose: `--scale` y limitacion con `container_name`:  
  https://docs.docker.com/reference/cli/docker/compose/up/  
  https://docs.docker.com/reference/compose-file/services/#container_name

## Respuesta a tu pregunta: se puede habilitar "berserker x4"?

Si, **pero no con un switch directo hoy**. Con el codigo actual, activar paralelismo 4x tiene alto riesgo de romper:
- consistencia de temporales/documentos,
- canal de firma,
- trazabilidad por job.

## Diseno recomendado de "berserker x4" (seguro)

### Fase 1: Aislamiento obligatorio

- Cambiar `tmp` global por `tmp/jobs/<job_id>/...` en todo el flujo.
- Eliminar limpieza global de `tmp`; limpiar solo carpeta del job.
- Namespaces de AutoFirma por job/worker (`XALOC_AFIRMA_URI_*` con sufijo `job_id` o `worker_id`).
- Guardado de justificante atomico (crear archivo con nombre unico sin carrera).

### Fase 2: Concurrencia controlada

- Mantener 1 tramite por worker y escalar horizontalmente a 4 workers.
- Quitar singleton (`WORKER_ENFORCE_SINGLETON=0`) solo cuando fase 1 este cerrada.
- Escalar runner a 4 replicas.
- Quitar `container_name` de servicios que se quieran escalar.

### Fase 3: Protecciones operativas

- Límite por site si algun portal no tolera paralelismo.
- Circuit breaker para firma (si falla proxy/handler, pausar solo ese site).
- Metricas por `job_id`: `queue lag`, `time to complete`, `doc write failures`, `xvia complete failures`.

## Configuracion objetivo (conceptual)

- `BERSERKER_MODE=1`
- `BERSERKER_CONCURRENCY=4`
- `WORKER_ENFORCE_SINGLETON=0`
- `docker compose up --scale worker-orchestrator-service=4 --scale playwright-runner-service=4`

Importante:
- Antes de escalar, remover `container_name` en servicios escalables.
- Si no se elimina `_EXECUTE_LOCK`, cada replica de runner seguira siendo 1x (lo cual puede ser aceptable si hay 4 replicas).

## Checklist minimo antes de activar x4

- [ ] `tmp` aislado por job, sin borrado global.
- [ ] Canales/archivos AutoFirma aislados por job o worker.
- [ ] Escritura de justificantes atomica y sin colision.
- [ ] Prueba de carga: 4 tramites simultaneos durante 100+ jobs.
- [ ] Cero duplicados de `idRecurso` en estado `processing`.
- [ ] Cero perdidas de justificantes y 100% trazabilidad `job_id -> archivo -> xvia`.

## Conclusion final

- Lo que ves como "4 desktops" no es paralelismo real de tramites.
- Ahora mismo el sistema esta diseñado para ejecucion principalmente serial.
- El "modo berserker x4" es viable, pero requiere primero aislamiento de temporales/firma y luego escalado controlado de worker+runner.
