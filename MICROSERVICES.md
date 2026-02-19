# MICROSERVICES.md

## 1. Objetivo y alcance

Este documento define un plan de accion **especifico, incremental y ejecutable** para migrar el sistema actual de `xaloc2026-main` (brain + worker + dashboard, con estado principal en SQLite y cola SQLite/Redis-list) a una arquitectura local de microservicios con:

- **PostgreSQL** como fuente de verdad de negocio.
- **Redis Streams** como cola confiable (consumer groups, ack, retry, DLQ).
- **Playwright** en contenedores Linux desacoplados del backend.
- **Signing Service** como unico limite con acceso a certificado.
- **Batching** en plano de control para reducir latencia de ciclo.

El plan preserva continuidad operativa y evita "big bang".

## 2. Estado actual del repositorio (as-is)

### 2.1 Ejecutables principales actuales

- `brain.py`: arranca `core/brain/orchestrator.py`.
- `worker.py`: arranca `core/worker/consumer.py`.
- `dashboard_api.py`: API FastAPI + auth + control de procesos + proxy frontend + realtime websocket.
- `run_dashboard.py`: levanta `dashboard_api.py` con uvicorn.

### 2.2 Persistencia y colas actuales

- `core/sqlite_db.py` + `db/schema.sql` + `db/schema_job_runs.sql`:
  - Cola `tramite_queue`.
  - Config `organismo_config`.
  - `job_runs`, `worker_runtime`, `pending_authorization_queue`, locks/incidencias/pausas.
- `core/queue_gateway.py`:
  - `SQLiteQueueGateway` y factory por `QUEUE_BACKEND`.
- `core/redis_queue_gateway.py`:
  - Redis actual en modo **List + Hash + ZSET lease**, no Streams.
- `core/realtime_store.py`:
  - ya soporta SQLite o PostgreSQL para `realtime_task_results` y `realtime_incidents`.

### 2.3 Automatizacion browser y sites

- `core/base_automation.py`: contexto Playwright persistente, screencast, restart.
- `core/site_registry.py`: registro de `xaloc_girona`, `base_online`, `madrid`, `ayunta_palma`.
- `sites/*`: controllers, data models y flows por organismo.
- `core/worker/processor.py`: descarga documentos, valida docs cliente, mapea payload, ejecuta site, marca completado.

### 2.4 Dashboard y auth actuales

- `dashboard_api.py`: muchas responsabilidades en un servicio unico.
- `dashboard/auth.py`: RBAC actual con roles `admin|user`.
- `dashboard/services.py` + `dashboard/repositories.py`: mezcla de lecturas SQLite/SQLServer/PostgreSQL.

### 2.5 Gap contra objetivo propuesto

1. Fuente de verdad repartida (SQLite + SQLServer + opcional PG realtime).
2. Cola Redis sin Streams ni consumer groups.
3. API gateway no separado de auth/jobs/rules/audit.
4. Worker ejecuta logica de orquestacion + navegador en el mismo proceso.
5. Certificado no encapsulado en un servicio dedicado.
6. Falta batching explicito (ventana temporal + agrupacion).

## 3. Arquitectura objetivo (to-be)

## 3.1 Servicios

1. **api-gateway** (FastAPI)
2. **auth-rbac-service** (FastAPI)
3. **org-rules-service** (FastAPI)
4. **jobs-service** (FastAPI + state machine)
5. **audit-events-service** (FastAPI/worker de eventos)
6. **brain-claim-service** (worker async)
7. **payload-validator-service** (worker async)
8. **batcher-dispatcher-service** (worker async)
9. **worker-orchestrator-service** (worker async)
10. **playwright-runner-service** (FastAPI/gRPC interno)
11. **signing-service** (FastAPI interno, acceso exclusivo al cert volume)

## 3.2 Infra local

- `postgres:16`
- `redis:7`
- Volumen artefactos: `/data/artifacts`
- Volumen certificado: `/data/certificates` (solo en signing-service)
- Red docker interna para trafico entre servicios

## 3.3 Contratos de datos

- PostgreSQL: estado de negocio y auditoria.
- Redis Streams:
  - `candidates`
  - `validated`
  - `jobs`
  - `dlq:<stream>`

## 4. Estructura recomendada en este repo

Crear carpeta nueva `services/` sin romper `core/` ni `sites/` durante migracion.

```text
services/
  api_gateway/
  auth_rbac/
  org_rules/
  jobs/
  audit_events/
  brain_claim/
  payload_validator/
  batcher_dispatcher/
  worker_orchestrator/
  playwright_runner/
  signing/
infra/
  docker/
    docker-compose.microservices.yml
  postgres/
    migrations/
  redis/
    redis.conf
shared/
  contracts/
    events.py
    dto.py
  observability/
    logging.py
  security/
    jwt.py
```

Reutilizacion directa recomendada:

- `sites/` y `core/base_automation.py` para `playwright_runner`.
- validadores de `core/validation/`.
- utilidades SQLServer (`core/sqlserver_utils.py`) en `brain_claim`.
- parte de `core/worker/processor.py` dividida entre `worker_orchestrator`, `playwright_runner` y `signing`.

## 5. Modelo de datos PostgreSQL (fuente de verdad)

## 5.1 Tablas base

1. `users`, `roles`, `scopes`, `user_roles`, `role_scopes`
2. `organisms`
3. `rulesets` (versionado)
4. `jobs`
5. `job_attempts`
6. `job_artifacts`
7. `events` (append-only, particionable)
8. `service_locks` (si se requiere lock persistente)

## 5.2 Indices criticos

- `jobs(dedup_key)` unique.
- `jobs(organism_id, status, created_at desc)`.
- `jobs(priority, status, next_run_at)`.
- `job_attempts(job_id, attempt_no desc)`.
- `events(job_id, created_at)`.
- `events(event_type, created_at)`.

## 5.3 Mapping inicial desde SQLite actual

- `organismo_config` -> `organisms` + primera version `rulesets`.
- `tramite_queue` + `job_runs` -> `jobs` + `job_attempts`.
- `incidencias` + `realtime_incidents` -> `events`.
- `pending_authorization_queue` -> `jobs` en estado `awaiting_authorization`.
- `blocked_resources` -> `jobs` con estado terminal + `events` tipo bloqueo.

## 6. Redis Streams: contratos operativos

## 6.1 Streams y consumer groups

1. `candidates`
   - Group: `validator_group`
2. `validated`
   - Group: `batcher_group`
3. `jobs`
   - Group: `worker_group`
4. `dlq:candidates`, `dlq:validated`, `dlq:jobs`

## 6.2 Payload minimo por stream

### candidates

- `candidate_id`
- `organism_id`
- `external_resource_id`
- `raw_payload_json`
- `claimed_at`
- `trace_id`

### validated

- `job_draft_id`
- `organism_id`
- `job_type`
- `cert_profile`
- `priority`
- `normalized_payload_json`
- `trace_id`

### jobs

- `job_id`
- `attempt`
- `max_attempts`
- `execution_plan_json`
- `artifacts_base_path`
- `trace_id`

## 6.3 Politicas de reintento y DLQ

- Retries con backoff exponencial.
- `XCLAIM/XAUTOCLAIM` para mensajes colgados.
- Al superar max intentos:
  - mover a `dlq:*`
  - actualizar estado PostgreSQL a `DEAD_LETTER`
  - emitir evento en `events`.

## 7. Definicion por servicio (responsabilidades + rutas + dependencias)

## 7.1 api-gateway

Responsabilidad: entrada unica para frontend y operacion.

Rutas publicas (ejemplo):

- `POST /api/auth/login`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/retry`
- `POST /api/jobs/{job_id}/pause`
- `POST /api/jobs/{job_id}/cancel`
- `GET /api/artifacts/{job_id}`

Dependencias:

- `fastapi`, `uvicorn`, `httpx`, `pydantic`.

Archivos iniciales:

- `services/api_gateway/app.py`
- `services/api_gateway/routes/*.py`
- `services/api_gateway/clients/*.py`

## 7.2 auth-rbac-service

Migrar desde `dashboard/auth.py`.

Cambios clave:

- pasar de roles `admin|user` a `Admin|Consultor|Comercial|Cliente`.
- scopes por organismo/cliente/servicio.

Rutas:

- `POST /auth/login`
- `POST /auth/refresh`
- `GET /auth/me`
- `CRUD /auth/users`
- `CRUD /auth/roles`

## 7.3 org-rules-service

Migrar desde `organismo_config` y reglas actuales dispersas.

Rutas:

- `GET /organisms`
- `POST /organisms`
- `PUT /organisms/{id}`
- `GET /rulesets/{organism_id}`
- `POST /rulesets/{organism_id}/versions`

## 7.4 jobs-service

Nucleo de state machine e idempotencia.

Rutas:

- `POST /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/transition`
- `POST /jobs/{job_id}/retry`
- `POST /jobs/{job_id}/cancel`

Estados sugeridos:

- `CREATED`, `VALIDATED`, `BATCHED`, `QUEUED`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, `DEAD_LETTER`, `CANCELLED`.

## 7.5 audit-events-service

Registro append-only.

Rutas:

- `POST /events`
- `GET /events?job_id=...`
- `GET /events?from=...&to=...&type=...`

## 7.6 brain-claim-service

Extraer desde `core/brain/orchestrator.py` solo la parte de claim:

- escaneo incremental SQLServer.
- claim XVIA.
- emision a `candidates`.

No construir payload final aqui.

## 7.7 payload-validator-service

Entrada: `candidates`.

Salida:

- persistir `job draft` en PG (`VALIDATED_PENDING_BATCH`).
- emitir a `validated`.

Reutilizar:

- `core/validation/*`
- normalizaciones de `core/brain/orchestrator.py` (placa, documento, expediente).

## 7.8 batcher-dispatcher-service

Ventana:

- por tiempo (30s) o volumen (N configurable).

Agrupacion:

- `organism + job_type + cert_profile + priority`.

Salida:

- alta definitiva en `jobs` PG.
- evento en stream `jobs`.

## 7.9 worker-orchestrator-service

Consume `jobs` (consumer groups), coordina intentos y estado en PG.

Invoca:

- `playwright-runner-service`
- `signing-service` (via runner o directo segun paso).

Gestiona:

- artifacts en disco
- `job_artifacts`
- transiciones y auditoria.

## 7.10 playwright-runner-service

Contenedor Linux con Playwright.

Entradas:

- `execution_plan`
- payload normalizado
- metadata de archivos.

Salidas:

- resultado estructurado
- evidencias (ruta artefactos).

Reutilizar:

- `sites/` + `core/base_automation.py` con adaptaciones para entorno container.

## 7.11 signing-service

Unico servicio con mount de certificado.

Funciones:

- operacion firma encapsulada.
- auditoria obligatoria de cada firma.

Seguridad:

- no exponer fuera de red interna.
- autenticacion mTLS o token de servicio corto.

## 8. Artefactos en disco

Estructura:

```text
/data/artifacts/{job_id}/input.json
/data/artifacts/{job_id}/output.pdf
/data/artifacts/{job_id}/screenshots/*.png
/data/artifacts/{job_id}/logs/attempt_{n}.log
```

Politica:

- retencion por dias (`ARTIFACT_RETENTION_DAYS`) o cantidad (`ARTIFACT_MAX_JOBS`).
- job de limpieza diario.
- hash `sha256` guardado en `job_artifacts`.

## 9. Docker local y despliegue

## 9.1 Ficheros a crear

- `infra/docker/docker-compose.microservices.yml`
- `infra/docker/.env.microservices`
- `infra/postgres/migrations/*.sql` (o Alembic)
- `services/*/Dockerfile`

## 9.2 Servicios de compose (minimo)

- `postgres`
- `redis`
- `api-gateway`
- `auth-rbac-service`
- `org-rules-service`
- `jobs-service`
- `audit-events-service`
- `brain-claim-service`
- `payload-validator-service`
- `batcher-dispatcher-service`
- `worker-orchestrator-service`
- `playwright-runner` (N replicas)
- `signing-service`

## 9.3 Dependencias Python por servicio (baseline)

- base API: `fastapi`, `uvicorn`, `pydantic`, `httpx`.
- DB: `psycopg[binary]`, `sqlalchemy` (recomendado), `alembic`.
- Redis: `redis`.
- workers: `aiohttp`, `tenacity`.
- runner: `playwright`.
- seguridad: `pyjwt`, `cryptography`.

Nota: mantener `pyodbc` solo donde se lea SQLServer (brain-claim en fase transitoria).

## 10. Plan de migracion (sin romper lo actual)

## Fase 0 - Preparacion (1 semana)

1. Crear `infra/docker/docker-compose.microservices.yml` con PG+Redis.
2. Crear esquema inicial PG.
3. Introducir libreria compartida `shared/contracts`.
4. Activar feature flags:
   - `USE_PG_SOURCE_OF_TRUTH=0|1`
   - `QUEUE_MODE=sqlite|redis_list|redis_streams`

## Fase 1 - Estado en PostgreSQL (1-2 semanas)

1. Crear `jobs-service` minimo para alta/consulta/transicion.
2. Dual-write desde rutas actuales de `dashboard_api.py`:
   - seguir escribiendo SQLite
   - escribir tambien en PG.
3. Comparador diario SQLite vs PG (script de reconciliacion).

## Fase 2 - Redis Streams (1 semana)

1. Crear gateway de streams (`shared/queue/redis_streams.py`).
2. Mantener paralelo:
   - actual `core/redis_queue_gateway.py` (list/hash)
   - nuevo stream `jobs`.
3. Worker piloto consume streams en entorno de pruebas.

## Fase 3 - Separar control plane (2 semanas)

1. Extraer de `core/brain/orchestrator.py` a:
   - `brain-claim-service`
   - `payload-validator-service`
   - `batcher-dispatcher-service`
2. Brain deja de generar payload final.
3. Validator genera draft y dedup_key en PG.
4. Dispatcher publica a `jobs` stream cada 30s.

## Fase 4 - Separar execution plane (2-3 semanas)

1. Crear `worker-orchestrator-service`.
2. Crear `playwright-runner-service` Linux y mover ejecucion browser.
3. Crear `signing-service` con volumen de cert.
4. Mover responsabilidades de `core/worker/processor.py` por capas.

## Fase 5 - API y RBAC desacoplados (1-2 semanas)

1. Partir `dashboard_api.py` en gateway + servicios internos.
2. Migrar `dashboard/auth.py` a `auth-rbac-service`.
3. Extender roles/scopes por organismo/cliente.
4. Conectar frontend (`dashboard-frontend`) solo al gateway.

## Fase 6 - Corte final y retirada SQLite (1 semana)

1. Desactivar writers SQLite.
2. Congelar tablas SQLite en modo read-only para respaldo temporal.
3. Cambiar defaults:
   - `USE_PG_SOURCE_OF_TRUTH=1`
   - `QUEUE_MODE=redis_streams`
4. Retirar rutas/codigo legado tras ventana de observacion.

## 11. Backlog tecnico detallado (archivos concretos)

## 11.1 Nuevos archivos prioritarios

1. `infra/docker/docker-compose.microservices.yml`
2. `infra/postgres/migrations/001_init.sql`
3. `infra/postgres/migrations/002_jobs.sql`
4. `shared/contracts/events.py`
5. `shared/contracts/job_schema.py`
6. `shared/queue/redis_streams.py`
7. `services/jobs/app.py`
8. `services/brain_claim/app.py`
9. `services/payload_validator/app.py`
10. `services/batcher_dispatcher/app.py`
11. `services/worker_orchestrator/app.py`
12. `services/playwright_runner/app.py`
13. `services/signing/app.py`

## 11.2 Refactors sobre archivos existentes

1. `core/brain/orchestrator.py`
   - dejar solo logica reusable mientras se extrae servicio.
2. `core/worker/processor.py`
   - dividir en modulos reutilizables:
     - `document_fetcher.py`
     - `payload_mapper.py`
     - `execution_client.py`.
3. `dashboard_api.py`
   - adelgazar rutas y mover negocio.
4. `dashboard/services.py`
   - pasar de repos locales a clientes HTTP internos.
5. `core/redis_queue_gateway.py`
   - marcar como legado y preparar deprecacion.

## 12. Observabilidad y operacion

## 12.1 Logging

- JSON logs por servicio.
- campos comunes: `trace_id`, `job_id`, `resource_id`, `service`, `attempt`.

## 12.2 Metricas minimas

- cola por stream (lag por consumer group).
- throughput jobs/min.
- success rate por organismo.
- p95 y p99 de duracion.
- retries y DLQ por organismo.

## 12.3 Health checks

- `/health/live`
- `/health/ready` (valida PG + Redis + dependencias internas).

## 13. Seguridad

1. JWT firmado y scopes por servicio.
2. credenciales por servicio en `.env` segregado.
3. `signing-service` aislado por red y volumen exclusivo.
4. artefactos servidos via gateway con control de permisos.
5. auditoria obligatoria de eventos sensibles:
   - login
   - cambios de reglas
   - reintentos/cancelaciones
   - firma.

## 14. Criterios de aceptacion por fase

1. **Fase 1**: PG refleja >= 99.9% de eventos comparado con SQLite (sin divergencias criticas).
2. **Fase 2**: worker stream procesa con ack/retry y sin perdida en reinicio.
3. **Fase 3**: batching activo con ventana 30s y reduccion medible de latencia.
4. **Fase 4**: navegador aislado en Linux; firma encapsulada.
5. **Fase 5**: gateway + auth/rules/jobs/audit separados y frontend estable.
6. **Fase 6**: SQLite fuera del camino critico.

## 15. Riesgos y mitigaciones

1. **Complejidad de corte de cola**
   - mitigacion: dual-run con comparador y canary worker.
2. **Dependencias Windows/certificados**
   - mitigacion: encapsular firma en servicio unico y contratos claros.
3. **Regresiones de flows Playwright**
   - mitigacion: runner reutiliza `sites/` y test smoke por organismo.
4. **Crecimiento de artefactos**
   - mitigacion: politica de retencion automatica.

## 16. Comandos base (objetivo local)

## 16.1 Infra

```powershell
docker compose -f infra/docker/docker-compose.microservices.yml up -d postgres redis
```

## 16.2 Migraciones

```powershell
python -m alembic upgrade head
```

## 16.3 Servicios (ejemplo)

```powershell
uvicorn services.jobs.app:app --host 0.0.0.0 --port 8103
uvicorn services.api_gateway.app:app --host 0.0.0.0 --port 8080
python -m services.brain_claim.app
python -m services.payload_validator.app
python -m services.batcher_dispatcher.app
python -m services.worker_orchestrator.app
```

## 17. Orden recomendado de ejecucion del proyecto de migracion

1. Infra + contratos compartidos.
2. Jobs-service (state machine) + esquema PG.
3. Cola streams + consumer piloto.
4. Control plane separado (claim/validate/batch).
5. Execution plane separado (orchestrator/runner/signing).
6. API gateway y RBAC completo.
7. Retirada SQLite.

## 18. Estado de implementacion en este repositorio

- Fase 0: completada.
- Fase 1: completada con `services/jobs`, dual-write a PG y script de reconciliacion.
- Fase 2: completada con `shared/queue/redis_streams.py`, gateway paralelo y piloto por flag.
- Fase 3: completada con:
  - `services/brain_claim/app.py`
  - `services/payload_validator/app.py`
  - `services/batcher_dispatcher/app.py`
  - `infra/postgres/init/002_control_plane_schema.sql`
- Fase 4: base implementada con:
  - `services/worker_orchestrator/app.py`
  - `services/playwright_runner/app.py`
  - `services/signing/app.py`
  - capas extraidas de `core/worker/processor.py` a `core/worker_execution/*`
  - compose actualizado con volúmenes `artifacts_data` y `cert_data`.

---

Este plan esta alineado con el estado real del repositorio actual y con tu propuesta de microservicios. El siguiente paso recomendable es implementar **Fase 0 + Fase 1** como primer hito tecnico con entregables en `infra/`, `shared/` y `services/jobs/`.
