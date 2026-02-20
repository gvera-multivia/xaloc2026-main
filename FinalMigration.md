# Final Migration Plan (SQLite -> PostgreSQL + Redis)

## 1. Objetivo y criterio de exito

Este plan define la migracion completa para eliminar cualquier dependencia funcional de SQLite y dejar la plataforma operativa al 100% con:

- Persistencia: PostgreSQL
- Coordinacion/colas: Redis (Streams)
- Sin rutas de negocio en SQLite
- Sin endpoints “legacy/no disponible” en flujos activos de UI

Se considera migracion completada cuando:

- Ningun servicio del `docker-compose.microservices.yml` requiere SQLite para operar.
- Todos los endpoints consumidos por frontend devuelven respuestas funcionales (no stubs).
- No quedan imports activos de `core.sqlite_db` en rutas runtime.
- Smoke tests de colas, control, auth, gestion y procesamiento pasan en entorno limpio.

---

## 2. Estado actual (gap real)

### 2.1 Pendientes de autorizacion (`pending-auth`)

Actualmente:

- `GET /api/pending-auth` devuelve vacio forzado.
- `POST /api/pending-auth/{id}/approve` y `reject` no operan (legacy).
- No existe tabla PG para esta cola de autorizaciones.

Impacto:

- Pantalla de gestion no tiene flujo real de autorizaciones.

### 2.2 Endpoint de eliminacion de item en cola

Actualmente:

- `DELETE /api/queue/items/{site_id}/{resource_id}` retorna error de legado eliminado.

Impacto:

- Accion de operacion incompleta en backend.

### 2.3 Codigo legacy fuera del path principal

Existen modulos legacy con dependencia SQLite (`core/brain/orchestrator.py`, `core/execution_report.py`) que no estan en el compose activo, pero deben quedar migrados o retirados para evitar regresiones futuras.

---

## 3. Estrategia de migracion

Aplicar migracion en 4 ondas:

1. **Modelo de datos y repositorios PG**
2. **Servicios/API (backend)**
3. **Integracion de productores/consumidores**
4. **Hardening + retirada total de legado**

Principio clave:

- No cortar endpoints primero; migrar implementacion debajo y mantener contrato API estable para frontend.

---

## 4. Plan tecnico por fases

## Fase A: Esquema y capa de datos

### A.1 Crear esquema PG para `pending_authorization_queue`

Agregar migration SQL en `infra/postgres/init/` (nuevo archivo, siguiente secuencia) con:

- Tabla `pending_authorization_queue`
  - `id bigserial pk`
  - `site_id text not null`
  - `resource_id bigint not null`
  - `payload_json jsonb not null`
  - `authorization_type text not null default 'gesdoc'`
  - `reason text null`
  - `status text not null default 'pending'` (`pending|approved|rejected|moved_to_queue`)
  - `authorized_by text null`
  - `authorized_at timestamptz null`
  - `notes text null`
  - `created_at timestamptz default now()`
  - `updated_at timestamptz default now()`
- Indice unico parcial para dedupe de pendientes:
  - `(site_id, resource_id)` where `status='pending'`
- Indices por consulta:
  - `(status, created_at)`
  - `(authorization_type, status, created_at)`

### A.2 Crear repositorio PG dedicado

Nuevo modulo en `dashboard/` o `core/` (segun convencion actual) con operaciones:

- `insert_pending_authorization(...)`
- `list_pending_authorizations(authorization_type=None)`
- `approve_pending_authorization(id, authorized_by)`
- `reject_pending_authorization(id, reason, rejected_by)`
- `count_pending_authorizations(...)`

Con:

- SQL parametrizado
- transacciones explicitas
- dedupe consistente
- respuestas tipadas para API

---

## Fase B: Backend dashboard y contratos API

### B.1 Migrar `dashboard/services.py`

Reemplazar implementacion temporal de:

- `list_pending_authorizations`
- `approve_pending_authorization`
- `reject_pending_authorization`

por llamadas al repositorio PG real.

### B.2 Endpoint de eliminar item en cola

Implementar `remove_queue_item(...)` con comportamiento operativo sobre PG/Redis:

- recuperar lock/estado si aplica
- marcar/cancelar item en ledger PG
- liberar claim en XVIA solo cuando corresponda
- respuesta determinista (`removed`, `reason`, `recovery_attempted`, etc.)

Mantener contrato actual de `dashboard_api.py`.

### B.3 Manejo de errores y codigos HTTP

Estandarizar:

- 400 para validacion
- 404 para recurso inexistente
- 409 para conflictos de estado
- 500 solo para fallo inesperado real

Eliminar `ValueError` legacy de rutas expuestas.

---

## Fase C: Productores/flujo de negocio

### C.1 Brain/origen de `pending-auth`

Definir un unico productor activo:

- O se mantiene `services/brain_claim/app.py` y se integra ahi la insercion PG de pendientes.
- O se migra/reemplaza definitivamente `core/brain/orchestrator.py` y se retira.

Regla:

- Cualquier caso “requiere GESDOC/autorizacion” debe persistirse en PG, no en SQLite.

### C.2 Integracion approve/reject

Al aprobar:

- mover a cola de trabajo (Redis Streams + ledger PG) con idempotencia.

Al rechazar:

- marcar estado final + metadata de rechazo en PG.

### C.3 Reglas de deduplicacion unificadas

Unificar clave de dedupe entre:

- pending auth
- queue gateway
- runtime ledger

para evitar reapariciones/reclaims incorrectos.

---

## Fase D: retirada total de legado SQLite

### D.1 Codigo

- Eliminar o aislar modulos SQLite no usados en runtime.
- Si se conservan por compatibilidad, que fallen en bootstrap con mensaje claro y que no se importen en rutas activas.

### D.2 Configuracion

- Quitar variables/env de SQLite remanentes.
- Quitar referencias en docs y scripts.

### D.3 Guardrails en CI

Agregar checks automáticos:

- grep fail si aparece `core.sqlite_db` en servicios runtime.
- grep fail si aparecen mensajes `legacy eliminado` en endpoints activos.

---

## 5. Plan de ejecucion recomendado (orden)

1. Migration SQL `pending_authorization_queue`.
2. Repo PG pending-auth + tests unitarios.
3. `dashboard/services.py` y `dashboard_api.py` conectados al repo PG.
4. Implementar `remove_queue_item` en PG/Redis.
5. Integrar productor pending-auth (brain activo).
6. Ajustes frontend si cambia algun campo.
7. End-to-end tests + hardening.
8. Deprecacion/eliminacion definitiva de legado SQLite.

---

## 6. Validacion funcional (checklist)

## 6.1 API

- `GET /api/pending-auth` lista real en PG.
- `POST /api/pending-auth/{id}/approve` mueve a cola real.
- `POST /api/pending-auth/{id}/reject` persiste rechazo.
- `DELETE /api/queue/items/{site}/{resource}` operativo sin legado.

## 6.2 UI

- Pantalla `gestion` carga sin errores.
- Aprobar/rechazar actualiza lista en tiempo real/polling.
- Contadores por site coherentes con backend.

## 6.3 Procesamiento

- Item aprobado termina en worker y se procesa.
- Rechazado no reaparece como pendiente.
- No hay “resurreccion” de items completados.

## 6.4 Observabilidad

- Logs sin trazas de `SQLite` ni `legacy eliminado`.
- Metricas basicas: pending count, approve/reject rate, move-to-queue latency.

---

## 7. Pruebas necesarias

## 7.1 Unitarias

- Repositorio PG pending-auth (CRUD + dedupe + transiciones estado).
- Servicio dashboard para approve/reject/remove.

## 7.2 Integracion

- Flujo brain -> pending PG -> approve -> queue -> worker.
- Flujo reject y no-requeue.

## 7.3 E2E (docker compose)

- `up` limpio con `--env-file .env`.
- Login + gestion + colas + control.
- Comprobacion de salud:
  - `8101`, `8788`, `8080`, `8111`, `8112`.

---

## 8. Riesgos y mitigacion

- **Riesgo**: inconsistencias entre estado PG y mensajes Redis.
  - Mitigacion: transicion con idempotencia por dedupe_key + reconciliador.

- **Riesgo**: doble productor de pendientes (legacy + nuevo).
  - Mitigacion: feature flag de productor y bloqueo del path legacy.

- **Riesgo**: frontend asume campos legacy.
  - Mitigacion: mantener contrato y versionar si cambia payload.

---

## 9. Plan de rollback

Rollback por fases:

- Si falla Fase A/B: revertir migrations no aplicadas y despliegue backend.
- Si falla Fase C: deshabilitar productor nuevo por flag, mantener lectura de pending en PG.
- Mantener backups de PG antes de cambios estructurales.

Nota:

- No reintroducir SQLite como rollback funcional.

---

## 10. Definicion de “100% funcional”

La aplicacion queda 100% funcional cuando:

- Todos los flujos de negocio activos (claim, validacion, batch, worker, dashboard gestion/control/historial/auth) funcionan con PG + Redis.
- No existe ningun endpoint requerido por UI devolviendo stubs/legacy.
- No hay componentes runtime que importen o dependan de SQLite.
- Los tests E2E y smoke en Docker pasan consistentemente.

---

## 11. Entregables finales

1. Migrations PG completas (`infra/postgres/init/*`).
2. Repositorios y servicios migrados.
3. Endpoints estabilizados sin legado.
4. Documentacion actualizada (`BOOTSTRAP_SETUP.md` + runbook operativo).
5. Checklist de corte firmado (API/UI/colas/worker/observabilidad).

