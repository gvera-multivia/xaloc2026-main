# MORRIGAN Electron - Notificaciones Actuales (Estado Real)

Documento operativo del sistema de notificaciones en produccion para Morrigan Electron.

## 1. Tipos de notificacion que existen hoy

### 1.1 Notificaciones de incidencias (automaticas)
- Origen: eventos WS de backend relacionados con incidencias.
- Deteccion en cliente: `DashboardView` marca como incidencia cuando:
  - `ev.type` contiene `incident`
  - `ev.type` contiene `error`
  - `ev.type === "job.failed"`
- Efecto:
  - refresca la tabla de incidencias
  - lanza overlay de escritorio en Electron

Mapeo visual actual (incidencias):
- `red-large`: cuando texto sugiere `aut` o `carpeta`
- `green`: cuando texto sugiere `recurso` o `hacer`
- `purple`: cuando texto sugiere `bloqueo`
- `default`: resto de casos

### 1.2 Notificaciones administrativas (broadcast)
- Origen: panel admin (`/descargas`) -> `POST /api/admin/notifications/broadcast`.
- Evento emitido: `admin.alert`.
- Payload soportado:
  - `title`
  - `body`
  - `level` (`info`, `warning`, `critical`)
  - `template_id` (opcional)
  - `internal_note` (opcional, trazabilidad)
  - `design_code` (opcional, CSS personalizado)

Mapeo visual actual (admin.alert):
- `critical` -> `red-large`
- `info` -> `green`
- `warning` -> `default`

Ademas se antepone icono textual en el titulo:
- `critical` -> `🚨 `
- `warning` -> `⚠️ `
- `info` -> `ℹ️ `

### 1.3 Notificacion local de prueba
- Boton en UI Electron: "Probar Noti".
- No depende de backend ni Redis.
- Sirve para validar solo render overlay/estilos.

## 2. Flujo end-to-end real

1. Admin envia alerta en Dashboard.
2. Backend publica en Redis `channel:ui_updates`.
3. Cliente Electron mantiene WS en `/ws/dashboard?token=...`.
4. Renderer procesa evento y llama `window.morrigan.auth.notify(...)`.
5. Main process abre `notification.html` en ventana overlay siempre encima.

Si `published_to_subscribers = 0`, no hay clientes WS aceptados en ese instante.
Si hay WS pero no se ve nada, revisar carga de `notification.html` y logs de `did-fail-load`.

## 3. Plantillas y CSS dinamico

Cada plantilla puede tener:
- `id`, `label`, `title`, `body`, `level`
- `design_code` (CSS inyectado en la ventana de notificacion)

Selectores utiles:
- `.toast`
- `.toast-header`
- `.alert-icon`
- `.toast-title`
- `.toast-body`
- `.toast-footer`
- `.toast-time`
- `.progress-bar`

Reglas:
- usar `!important` para sobreescribir base
- no scripts, solo CSS
- ventana fija (no redimensionable)

## 4. Casos reales recomendados

### Caso A - Mantenimiento programado (warning)
Objetivo:
- Avisar sin generar panico.

Payload ejemplo:
```json
{
  "title": "Mantenimiento en 15 minutos",
  "body": "Se aplicara mantenimiento del servicio de tramites. Guarda cambios.",
  "level": "warning",
  "template_id": "maintenance"
}
```

Como se ve:
- estilo base `default`
- icono de cabecera `⚠️`
- tono neutro de advertencia

Que deberia hacer el operador:
- guardar trabajo
- evitar iniciar operaciones largas

### Caso B - Incidencia critica de operacion (critical)
Objetivo:
- Forzar atencion inmediata.

Payload ejemplo:
```json
{
  "title": "Servicio caido",
  "body": "No se pueden presentar expedientes. Escalado a soporte N2.",
  "level": "critical",
  "template_id": "incident"
}
```

Como se ve:
- `red-large`
- icono `🚨`
- mayor impacto visual

Que deberia hacer el operador:
- detener nuevas operaciones
- seguir runbook de contingencia
- registrar ticket/incidente

### Caso C - Comunicado informativo (info + branding CSS)
Objetivo:
- Mensaje interno sin tono de alarma.

Payload ejemplo:
```json
{
  "title": "Cambio operativo",
  "body": "Nuevo horario de corte aplicado desde hoy.",
  "level": "info",
  "template_id": "info",
  "design_code": ".toast{border-color:#22c55e!important}.toast-title{color:#4ade80!important}"
}
```

Como se ve:
- base `green`
- override visual con CSS

Que deberia hacer el operador:
- confirmar lectura
- aplicar nueva operativa

## 5. Que cambiar segun objetivo

### Quiero otro look por severidad
- Cambiar mapeo en `DashboardView.tsx` (`level` -> `adminNotifType`).
- Opcional: ajustar estilos base en `notification.html`.

### Quiero nuevos templates globales por defecto
- Anadir seeds en backend (`_DEFAULT_ALERT_TEMPLATES`).
- Reiniciar backend.

### Quiero mas campos (ej: CTA, enlace runbook)
- Extender payload backend `broadcast`.
- Extender schema/event parse en renderer.
- Pintar campo en `notification.html`.

### Quiero duracion distinta por tipo
- Pasar `duration` en `notify(...)`.
- Ajustar default en main (`renderer:notify` usa 7000ms si no se informa).

## 6. Checklist de verificacion rapida

1. Login Electron valido (token fresco).
2. `GET /api/admin/notifications/debug`:
   - `ws_active_connections > 0`
   - `numsub > 0`
3. Enviar `broadcast`.
4. Confirmar:
   - `published_to_subscribers > 0`
   - overlay visible en cliente
5. Si falla:
   - revisar `403` en `/ws/dashboard`
   - revisar logs de `did-fail-load` de notificacion

## 7. Publicacion de nueva version Electron

### 7.1 Publicacion tecnica real (instalador + latest.yml)
Objetivo:
- generar una version actualizable por `electron-updater` (no solo aviso visual).

Pasos:
1. subir version en `morrigan-electron/package.json` (ej: `0.1.8`).
2. ejecutar en `morrigan-electron`:
   - `npm.cmd run dist:nsis`
3. verificar artefactos en `morrigan-electron/release`:
   - `latest.yml`
   - `Morrigan Setup X.Y.Z.exe`
   - `Morrigan Setup X.Y.Z.exe.blockmap`

Resultado:
- `/updates/latest.yml` apunta a la nueva version.
- Electron clientes pueden detectar/descargar update diferencial.

### 7.2 Que hace "Publicar nueva version" en frontend (pagina Descargas)
El boton de frontend en `dashboard-frontend/app/descargas/page.tsx`:
- NO compila binarios.
- NO genera `latest.yml`.
- NO sube instaladores.
- SI envia un broadcast `admin.alert` para avisar a clientes conectados.

Es decir:
- "Publicar nueva version" (frontend) = anuncio operativo a usuarios.
- "dist:nsis" = publicacion tecnica real para auto-update.

### 7.3 Pipeline integrado (boton desde Electron admin)
En la vista admin de Electron (DashboardView), el flujo "Publicar Version":
- llama al endpoint `POST /api/admin/electron/release/build`
- ejecuta en servidor `npm run dist:nsis`
- deja artefactos en `release` y por tanto en `/updates`
- se puede seguir por `GET /api/admin/electron/release/status` (logs + estado).

## 8. Automatizacion CI/CD (nuevo)

### 8.1 Workflow incluido
Se ha anadido:
- `.github/workflows/morrigan-electron-release.yml`

Que hace:
1. Instala dependencias de `morrigan-electron`.
2. Opcionalmente aplica version (`workflow_dispatch` -> `version`).
3. Ejecuta `npm run dist:nsis`.
4. Valida artefactos de update:
   - `release/latest.yml`
   - `release/*.exe`
   - `release/*.blockmap`
5. Sube artefactos a GitHub Actions.
6. Publica GitHub Release automaticamente (tag o dispatch).

Triggers:
- Manual (`workflow_dispatch`) para releases operativas.
- Por tag `morrigan-v*` (ej: `morrigan-v0.1.9`).

### 8.2 Comando operativo recomendado (manual desde Git)
Ejemplo de tag para release:
```bash
git tag morrigan-v0.1.9
git push origin morrigan-v0.1.9
```

Con eso se dispara el pipeline y deja los binarios listos como release en GitHub.

### 8.3 Como conectarlo con tu `/updates` real
Tu auto-update en produccion lee de:
- `/updates/latest.yml` (servido por `api-gateway` desde `morrigan-electron/release`)

Por tanto, tienes 2 estrategias:

1. Runner self-hosted en el mismo servidor de despliegue (recomendado).
   - El workflow compila directamente en ese host y los artefactos quedan ya en `morrigan-electron/release`.
   - No hay paso manual de copia.

2. Runner GitHub hospedado + despliegue posterior.
   - Descargas artefactos del workflow y los copias al `release` del servidor.
   - Luego `restart` del stack para refrescar estado si aplica.

### 8.4 Que NO hace este CI por si solo
- No envia broadcast a usuarios.
- No reinicia contenedores automaticamente.
- No reemplaza el boton "Publicar nueva version" del frontend (ese boton solo avisa).

En resumen:
- CI/CD = genera y publica binarios versionados.
- Frontend "Publicar" = comunicacion operativa a usuarios.
