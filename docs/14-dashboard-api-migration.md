# 14 - Migracion para eliminar dependencia de `dashboard_api.py`

## Objetivo
Mover el backend de dashboard a la estructura modular (`services/dashboard_backend`) sin depender de `dashboard_api.py` como modulo base compartido.

## Estado actual
- El proceso en Docker levanta `services.dashboard_backend.app:app`.
- `services/dashboard_backend/app.py` importa `app` y utilidades desde `dashboard_api.py`.
- `services/dashboard_backend/routes/auth_ws.py` y `services/dashboard_backend/routes/operations.py` importan `dashboard_api as api`.
- `dashboard_api.py` aun contiene rutas API y helpers operativos.

## Endpoints pendientes de extraer de `dashboard_api.py`
- `GET /api/blacklist`
- `POST /api/blacklist`
- `DELETE /api/blacklist/{site_id}/{resource_id}`
- `GET /api/config`
- `PUT /api/config/{site_id}`
- `POST /api/config/{site_id}/active`
- `GET /api/pending-auth`
- `POST /api/pending-auth/{pending_id}/approve`
- `POST /api/pending-auth/{pending_id}/reject`
- `POST /api/client-folder`
- `GET /api/admin/notifications/templates`
- `POST /api/admin/notifications/templates`
- `PUT /api/admin/notifications/templates/{template_id}`
- `DELETE /api/admin/notifications/templates/{template_id}`
- `GET /api/admin/notifications/debug`
- `POST /api/admin/notifications/debug/publish`
- `POST /api/admin/notifications/broadcast`
- `POST /api/documentos/convert`
- `POST /api/documentos/bundle`
- `POST /api/documentos/compress`
- `GET /api/test` (legacy, candidato a eliminar)
- `GET /api/count` (legacy, candidato a eliminar)

## Fase 1: Crear base compartida interna en `services/dashboard_backend`
1. Crear `services/dashboard_backend/state.py` con:
   - `app = FastAPI(...)`
   - `service` lazy (`DashboardService`)
   - `process_manager`
   - constantes de runtime (`AUTH_COOKIE_NAME`, `ENABLE_WS_REALTIME`, etc).
2. Crear `services/dashboard_backend/deps.py` con:
   - `require_user`
   - `require_admin`
   - helpers de auth (`_auth_introspect`, parse de token/cookie)
3. Crear `services/dashboard_backend/proxy.py` con:
   - `_proxy_auth_service`
   - sesiones `aiohttp` compartidas
4. Crear `services/dashboard_backend/logs.py` con:
   - utilidades `_tail_text_file`, `_merge_tail_text_files`

### Criterio de salida
- `auth_ws.py` y `operations.py` dejan de importar `dashboard_api` y usan `state/deps/proxy/logs`.

## Fase 2: Extraer rutas de negocio restantes
1. Crear `services/dashboard_backend/routes/configuration.py`:
   - blacklist, config, pending-auth, client-folder.
2. Crear `services/dashboard_backend/routes/notifications.py`:
   - templates, broadcast, debug (o eliminar debug si no se usa).
3. Crear `services/dashboard_backend/routes/documents.py`:
   - convert, bundle, compress.
4. Mover startup hooks de notificaciones a `notifications.py` o a `app.py`.

### Criterio de salida
- Todas las rutas `@app.<method>` de `dashboard_api.py` quedan trasladadas o eliminadas.

## Fase 3: Limpieza de legacy
1. Eliminar `/api/test` y `/api/count` (o moverlas a endpoint interno de ops protegido por admin + env).
2. Eliminar credenciales hardcodeadas y forzar variables de entorno.
3. Eliminar catch-all de frontend en `dashboard_api.py` si ya no se usa ese entrypoint.

### Criterio de salida
- `dashboard_api.py` no define rutas API operativas.

## Fase 4: Corte definitivo
1. Cambiar `services/dashboard_backend/app.py` para instanciar app desde `services/dashboard_backend/state.py`.
2. Eliminar imports transversales a `dashboard_api`.
3. Dejar `dashboard_api.py` como shim temporal (deprecated) o eliminar archivo.

### Criterio de salida
- `rg "import dashboard_api|from dashboard_api" services/dashboard_backend services` devuelve 0 coincidencias en runtime dashboard.

## Validacion recomendada por fase
1. `GET /api/control/status`, `GET /api/logs/worker` (control y logs).
2. Login + websocket (`/api/auth/me`, `/ws/dashboard`).
3. Historial + detalle PostgreSQL.
4. Gestion (`pause/unpause/recover`).
5. Documentos (`convert/bundle/compress`).

## Riesgos principales
- Cambios en orden de registro de rutas (colisiones existentes).
- Pérdida de helpers internos al mover imports cruzados.
- Diferencias de contrato en endpoints de notificaciones (schema con `design_code`).

## Estrategia de despliegue
1. Migrar por modulo y desplegar tras cada fase.
2. Mantener tests de humo HTTP por endpoint crítico.
3. Activar logs de comparación durante transición (ruta antigua vs nueva) solo en staging.
