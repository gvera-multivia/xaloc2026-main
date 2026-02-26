# Morrigan Electron - Diagnostico Login "NETWORK ERROR"

Fecha analisis: 2026-02-26

## 1) Sintoma observado

En la pantalla de login de Electron aparece:

`ERROR INTERNO LOCAL: NETWORK ERROR`

Ese texto sale de `morrigan-electron/src/renderer/modules/auth/LoginPage.tsx` cuando Axios no recibe respuesta HTTP usable (`!status`).

## 2) Evidencia revisada

### 2.1 Codigo del renderer

- `LoginPage.tsx`:
  - Si `err.response?.status` no existe -> muestra `Error interno local: ${err.message}`.
- `apiClient` usa:
  - `withCredentials: true`
  - `timeout: 20000`
  - `baseURL` dinamico por runtime config.

Conclusion: el error no es de credenciales (401), es de transporte/CORS/conexion.

### 2.2 Conectividad desde esta maquina

Comprobaciones ejecutadas:

1. `Invoke-WebRequest http://192.168.184.72/api/auth/me` -> responde `401 Unauthorized` (host/API alcanzable).
2. `Test-NetConnection 192.168.184.72 -Port 8080` -> `TcpTestSucceeded=False` (puerto 8080 caido o no expuesto).
3. `Invoke-WebRequest http://192.168.184.72/morrigan-config.json` -> devuelve:
   - `apiBaseUrl: http://192.168.184.72`
   - `wsUrl: ws://192.168.184.72/ws/dashboard`

Conclusion: el backend principal por puerto 80 responde, pero 8080 no.

### 2.3 Logs del repositorio

No aparecen errores de login en `logs/` porque este fallo ocurre en el renderer (antes de tener respuesta HTTP valida), y ese tipo de error no se persiste en los logs de worker/brain.

## 3) Causa tecnica (mas probable)

El `NETWORK ERROR` en Electron (Axios) suele ser uno de estos casos:

1. CORS/Origin bloqueado para el origen del renderer.
2. Timeout o rechazo de conexion al host/puerto configurado.
3. Error de proxy inverso sin cabeceras CORS en respuesta de error.

Con las pruebas actuales, hay un riesgo claro de configuraciones mezcladas entre `:80` y `:8080`.
Si alguna parte del flujo de login termina resolviendo `apiBaseUrl` a `http://192.168.184.72:8080`, el request fallara por conexion (como ya muestra `Test-NetConnection`).

## 4) Acciones recomendadas

## A. Correccion inmediata (operativa)

1. Asegurar una unica URL de API para Electron login:
   - `http://192.168.184.72` (sin `:8080`) si ese es el endpoint real activo.
2. Verificar que `/morrigan-config.json` publica exactamente esa misma base URL.
3. Reiniciar Electron y reintentar login.

## B. Validacion de CORS

Permitir explicitamente el origen que usa Electron en dev:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

(en backend/gateway, no solo frontend web de puerto 3000).

## C. Hardening recomendado

1. Loggear en renderer el `apiClient.defaults.baseURL` al arrancar login.
2. Mostrar en UI el `baseURL` activo cuando falla login (modo debug).
3. Registrar en gateway cada `POST /api/auth/login` con upstream status para diferenciar:
   - 401 funcional
   - 5xx upstream
   - fallo de red/CORS

## 5) Resumen ejecutivo

El problema no apunta a usuario/clave incorrecta, sino a fallo de comunicacion HTTP desde renderer.
La evidencia tecnica mas fuerte es la inconsistencia de puertos (80 accesible, 8080 no) y el patron de error Axios sin status.
