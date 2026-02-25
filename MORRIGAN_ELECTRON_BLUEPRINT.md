# Morrigan Electron Blueprint

Documento de referencia para construir la app de escritorio **Morrigan** sobre el stack actual de Xaloc.

## 1. Objetivo

Crear una aplicación Electron para operación interna que:

- consuma el backend existente via `api-gateway` (`http://localhost:8080`)
- gestione cola, incidencias, control de procesos, logs y configuración
- soporte realtime por WebSocket
- sea segura por defecto (`contextIsolation`, `preload`, IPC mínimo)

## 2. Stack recomendado

- Electron `^31`
- TypeScript `^5`
- UI: React `^18` + Vite
- Estado remoto: TanStack Query
- Estado local/UI: Zustand
- HTTP: Axios
- Validación runtime: Zod
- Routing: React Router
- Build/packaging: electron-builder
- Lint/format: ESLint + Prettier
- Tests: Vitest + Playwright (E2E)

## 3. Arquitectura

Separar en 3 capas:

1. `main` (Node/Electron)
- ciclo de vida de ventanas
- actualización de app
- filesystem/shell (controlado)
- bridge IPC seguro

2. `preload`
- expone API estricta al renderer (`window.morrigan`)
- sin exponer módulos Node completos

3. `renderer` (React SPA)
- vistas y flujos de negocio
- cliente API REST/WS
- estado y cache

## 4. Estructura de carpetas (concreta)

```text
morrigan-electron/
  package.json
  tsconfig.json
  tsconfig.node.json
  .env.example
  electron-builder.yml
  vite.config.ts

  src/
    main/
      index.ts
      window.ts
      ipc/
        app.ipc.ts
        shell.ipc.ts
      services/
        logger.ts
        updater.ts
      security/
        csp.ts

    preload/
      index.ts
      types.d.ts

    renderer/
      index.html
      main.tsx
      app/
        App.tsx
        routes.tsx
        providers.tsx
      core/
        config/
          env.ts
        api/
          client.ts
          endpoints.ts
          ws.ts
          schemas.ts
        auth/
          auth.store.ts
          auth.guard.tsx
      modules/
        dashboard/
          DashboardPage.tsx
        queue/
          QueuePage.tsx
          QueueTable.tsx
          queue.api.ts
          queue.types.ts
        incidents/
          IncidentsPage.tsx
          incidents.api.ts
          incidents.types.ts
        control/
          ControlPage.tsx
          control.api.ts
        logs/
          LogsPage.tsx
          logs.api.ts
        config/
          ConfigPage.tsx
          config.api.ts
      shared/
        ui/
        hooks/
        utils/
      styles/
        globals.css

  tests/
    unit/
    e2e/
```

## 5. Variables de entorno

Crear `.env.example`:

```env
MORRIGAN_API_BASE_URL=http://localhost:8080
MORRIGAN_WS_URL=ws://localhost:8080/ws/dashboard
MORRIGAN_APP_NAME=Morrigan
MORRIGAN_LOG_LEVEL=info
```

Resolución:

- `renderer`: usar `import.meta.env`
- `main`: usar `process.env`
- en producción, permitir override via archivo local (`config.json`) leído por `main`

## 6. Seguridad Electron (obligatorio)

En creación de BrowserWindow:

- `contextIsolation: true`
- `nodeIntegration: false`
- `sandbox: true`
- `webSecurity: true`
- `preload: <path seguro>`
- bloquear navegación externa no permitida
- abrir links externos con `shell.openExternal` controlado

En preload:

- exponer solo métodos necesarios:
  - `app.getVersion()`
  - `shell.openPath(path)`
  - `diag.getRuntimeInfo()`

## 7. Conexión API (contrato actual)

Base URL: `http://localhost:8080`

### Auth
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`

### Cola
- `GET /api/queue/current`
- `POST /api/queue/recover-stuck`
- `DELETE /api/queue/items/{site_id}/{resource_id}`
- `POST /api/queue/items/{site_id}/{resource_id}/recover`

### Incidencias
- `GET /api/incidents`
- `POST /api/incidents/{id}/claim`
- `POST /api/incidents/{id}/release`

### Control
- `GET /api/control/status`
- `POST /api/control/{process_name}/start`
- `POST /api/control/{process_name}/stop`
- `POST /api/control/{process_name}/restart`

### Logs
- `GET /api/logs/{process_name}?lines=...`

### Config
- `GET /api/config`
- `PUT /api/config/{site_id}`
- `POST /api/config/{site_id}/active`

### Realtime
- `WS /ws/dashboard`

## 8. Cliente HTTP (patrón)

`src/renderer/core/api/client.ts`:

- instancia Axios única
- `withCredentials: true`
- timeout global (ej. 20s)
- interceptor de errores:
  - `401` => limpiar sesión y redirigir login
  - `409` => mostrar conflicto funcional
  - `5xx` => toast + retry selectivo

## 9. WebSocket (patrón)

`src/renderer/core/api/ws.ts`:

- conexión única a `/ws/dashboard`
- reconexión exponencial (`1s`, `2s`, `5s`, `10s`, max `30s`)
- heartbeat de aplicación (si procede)
- publish interno hacia Zustand/event bus

## 10. Modelo de datos frontend

```ts
type UserSession = {
  sub: string
  username: string
  role: "admin" | "user" | string
}

type QueueItem = {
  site_id: string
  resource_id: number
  protocol?: string
  state?: string
  started_at?: string
}

type IncidentItem = {
  id: string
  site_id: string
  resource_id?: number
  incident_type: string
  error_code?: string
  reason?: string
  status?: "NEW" | "REVIEWED" | "RESOLVED"
  updated_at?: string
}
```

## 11. Módulos funcionales (MVP)

1. Login/Sesión
- formulario login
- persistencia de sesión por cookie
- perfil y logout

2. Queue
- lista de cola actual
- acciones: recover item, recover stuck, delete item

3. Incidents
- lista de incidencias
- claim/release
- filtros por site/tipo/estado

4. Control
- estado `brain` / `worker`
- start/stop/restart

5. Logs
- visor de logs por proceso (`brain`, `worker`, `frontend`)
- auto-refresh (polling configurable)

6. Config
- tabla de `organismo_config`
- edición `query_organisme`, `filtro_texp`, `regex_expediente`, `active`

## 12. Permisos por rol

- `admin`: acceso completo (control, config, logs, usuarios)
- `user`: lectura operativa + acciones permitidas en cola/incidencias

Implementar guardas en frontend:

- rutas protegidas por `role`
- ocultación de acciones no autorizadas

## 13. Plan de implementación por fases

### Fase 0: Bootstrap técnico
- crear proyecto electron + react + typescript
- wiring `main/preload/renderer`
- lint + test base + scripts build

### Fase 1: Auth + layout
- login/me/logout
- shell base con navegación lateral
- guardas de sesión/rol

### Fase 2: Queue + Incidents
- pages y APIs de cola/incidencias
- acciones críticas con modal de confirmación

### Fase 3: Control + Logs + Config
- control procesos
- logs viewer
- edición config organismos

### Fase 4: Realtime y UX operativa
- socket + invalidación de queries
- badges de eventos
- notificaciones de error/retry

### Fase 5: Packaging y despliegue
- build Windows installer
- firma de app (si aplica)
- canal de updates interno

## 14. Scripts recomendados (`package.json`)

```json
{
  "scripts": {
    "dev": "concurrently \"vite\" \"electron .\"",
    "dev:renderer": "vite",
    "dev:electron": "electron .",
    "build:renderer": "vite build",
    "build:electron": "tsc -p tsconfig.node.json",
    "build": "npm run build:renderer && npm run build:electron",
    "dist": "npm run build && electron-builder",
    "test": "vitest run",
    "test:e2e": "playwright test"
  }
}
```

## 15. Checklist de aceptación

- login/logout funcional contra `api-gateway`
- módulos MVP operativos
- WebSocket conectado y reconectando
- sin warnings de seguridad críticos en Electron
- instalador generado y ejecutable
- runbook operativo para soporte interno

## 16. Riesgos y mitigaciones

1. CORS/cookies
- usar `withCredentials` y validar dominio/puerto únicos por entorno

2. Desalineación contratos API
- centralizar schemas Zod y fallback seguro

3. UX en caídas de backend
- estados offline, retry y mensajes claros

4. Seguridad desktop
- no exponer APIs Node al renderer
- auditar IPC y permisos

## 17. Próximo paso sugerido

Crear un esqueleto inicial del proyecto con:

- `main/index.ts`
- `preload/index.ts`
- `renderer/main.tsx`
- cliente API base + módulo Auth listo

Con eso se puede empezar a iterar funcionalidad en 1-2 días.
