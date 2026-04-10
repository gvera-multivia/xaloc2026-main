# Postgres Debug Map

## Objetivo

Recordar que tablas y repositorios consultar primero cuando un recurso o job falla.

## Fuentes principales

### 1. `jobs`

- estado final o intermedio del job
- `error_message`
- `payload_json`
- `result_json`
- timestamps `queued_at`, `started_at`, `finished_at`
- acceso rapido via `services/jobs/repository.py`

### 2. `job_drafts`

- evidencia de pre-worker
- payload normalizado, `last_error`, `dedup_key`, `cert_profile`, `priority`
- aparece en el detalle PG si la tabla existe

### 3. `realtime_task_results`

- resultados o estados ligados a `site_id` + `resource_id`
- `payload` y `result` ayudan a ver si el fallo fue antes o despues del runner

### 4. `realtime_incidents`

- incidencias operativas
- `incident_type`, `reason`, `expediente`
- muy utiles para distinguir descartes de validacion frente a fallos de ejecucion

## API/repositorios ya existentes

- `dashboard.repositories.PostgresHistoryRepository.list_postgres_details(...)`
- `dashboard.services.DashboardService.get_history_postgres_details(...)`
- `core.pg_runtime_store.PgRuntimeStore`
- `core.pg_control_plane_store.PgControlPlaneStore`

## Lectura recomendada

1. mirar detalle PG por `site_id` + `resource_id`
2. extraer `job_id` y estado
3. revisar si hay incidente previo que explique el fallo
4. correlacionar timestamps con logs de servicio
