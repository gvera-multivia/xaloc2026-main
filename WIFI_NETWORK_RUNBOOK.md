# RUNBOOK: Exponer Xaloc2026 al WiFi local

> **Objetivo**: Que cualquier dispositivo en la red WiFi pueda acceder al dashboard, la API y el noVNC del stack xaloc2026 que corre en este PC con Docker Compose.

---

## Arquitectura de servicios

Estos son todos los servicios que levanta `infra/docker/docker-compose.microservices.yml` y sus puertos en el host:

| Contenedor | Puerto host | DescripciÃ³n |
|---|---|---|
| `xaloc-api-gateway` | **8080** | ðŸŒ Punto de entrada principal (dashboard + API) |
| `xaloc-dashboard-backend` | 8788 | API interna del dashboard (SSE, WebSocket, jobsâ€¦) |
| `xaloc-auth-rbac` | 8101 | AutenticaciÃ³n / JWT / RBAC |
| `xaloc-jobs-service` | 8103 | Servicio de trabajos |
| `xaloc-playwright-runner` | 8111 | Runner Playwright |
| `xaloc-playwright-runner` | **6080** | ðŸ–¥ï¸ noVNC (ver el navegador en tiempo real) |
| `xaloc-playwright-runner` | 5900 | VNC raw |
| `xaloc-playwright-runner` | 9222 | Chrome DevTools remote |
| `xaloc-signing-service` | 8112 | Firma digital |
| `xaloc-postgres` | 5432 | PostgreSQL |
| `xaloc-redis` | 6379 | Redis |

> **Solo necesitas exponer `8080` y `6080`** al WiFi para uso normal.  
> Los demÃ¡s son internos (se comunican entre contenedores por red Docker).

**URL que usarÃ¡s desde otro dispositivo**: `http://192.168.184.72:8080`

---

## Paso 1 â€” Conoce tu IP local del WiFi

Abre PowerShell y ejecuta:

```powershell
ipconfig
```

Busca el bloque de tu adaptador WiFi (suele llamarse `Wi-Fi` o `Adaptador de LAN inalÃ¡mbrica Wi-Fi`):

```
Adaptador de LAN inalÃ¡mbrica Wi-Fi:
   DirecciÃ³n IPv4. . . . . . . . . . . . . . . : 192.168.1.50   â† esta
   MÃ¡scara de subred . . . . . . . . . . . . . : 255.255.255.0
   Puerta de enlace predeterminada . . . . . . : 192.168.1.1
```

GuÃ¡rdate esa IP. En este runbook usaremos **`192.168.X.Y`** como placeholder, sustitÃºyela por la tuya real.

---

## Paso 2 â€” Modifica el `.env`

Abre `.env` en la raÃ­z del proyecto. Hay **dos cambios obligatorios**:

### 2a. CORS â€” permite peticiones desde la IP WiFi

**Antes (lÃ­nea 60):**
```env
DASHBOARD_CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,http://localhost:5173
```

**DespuÃ©s:**
```env
DASHBOARD_CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,http://localhost:5173,http://192.168.X.Y:8080,http://192.168.X.Y:3000
```

> **Por quÃ©**: El dashboard-backend tiene un middleware CORS que bloquea peticiones de orÃ­genes no listados. Si accedes desde un mÃ³vil o portÃ¡til, el origen del request serÃ¡ `http://192.168.X.Y:8080`, y sin esto darÃ¡ error 403/CORS.

### 2b. URL del backend para el proceso de api-gateway que corre en local (modo no-Docker)

Esto solo importa si arrancas el gateway con `python run_gateway.py` directamente en Windows (no en Docker). Si usas Docker Compose, el gateway ya usa `http://dashboard-backend-service:8788` por red interna de Docker.

**Si usas modo local (run_gateway.py)**, cambia tambiÃ©n:

```env
# Antes:
DASHBOARD_BACKEND_URL=http://localhost:8788

# DespuÃ©s (dÃ©jalo en localhost, el gateway corre en el mismo PC):
DASHBOARD_BACKEND_URL=http://localhost:8788   â† no hay que cambiar esto
```

> El gateway hace la peticiÃ³n backend-to-backend, siempre desde el mismo PC, asÃ­ que `localhost` estÃ¡ bien aquÃ­.

### 2c. (Opcional) noVNC URL pÃºblica

Si quieres que el noVNC sea accesible y que el dashboard apunte a la URL correcta al mostrarlo en otros dispositivos:

```env
XALOC_NOVNC_PUBLIC_URL=http://192.168.X.Y/vnc/vnc.html?autoconnect=1&quality=9&compression=0
```

---

## Paso 3 â€” CÃ³mo afecta `next.config.ts` (Next.js frontend)

En `dashboard-frontend/next.config.ts` el frontend Next.js hace un **rewrite** de `/api/*` hacia el backend:

```ts
// dashboard-frontend/next.config.ts (lÃ­nea 3)
const backendHost = (process.env.DASHBOARD_BACKEND_HOST || "127.0.0.1").trim() || "127.0.0.1";
```

Esto funciona bien **cuando el Next.js dev server corre en el mismo PC que el backend**, porque el proxy es server-to-server (PC â†’ PC). El browser del cliente remoto nunca habla directamente al puerto 8788; habla al 8080 â†’ el gateway/Next.js hace el proxy internamente.

**ConclusiÃ³n: no hay que cambiar `next.config.ts`**. Todo el trÃ¡fico entra por el puerto 8080.

---

## Paso 4 â€” Abre el Firewall de Windows

Por defecto, Windows bloquea conexiones entrantes a puertos que no haya abierto explÃ­citamente.

Abre **PowerShell como Administrador** y ejecuta:

```powershell
# Puerto principal: Dashboard + API Gateway
New-NetFirewallRule `
  -DisplayName "Xaloc - API Gateway (8080)" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8080 `
  -Action Allow

# Puerto noVNC: ver el navegador en tiempo real
New-NetFirewallRule `
  -DisplayName "Xaloc - noVNC (6080)" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 6080 `
  -Action Allow
```

Para verificar que la regla existe:

```powershell
Get-NetFirewallRule -DisplayName "Xaloc*" | Select-Object DisplayName, Enabled, Direction, Action
```

Para eliminar las reglas si ya no las necesitas:

```powershell
Remove-NetFirewallRule -DisplayName "Xaloc - API Gateway (8080)"
Remove-NetFirewallRule -DisplayName "Xaloc - noVNC (6080)"
```

### 4b. Ver puertos en uso y cerrar un puerto antiguo (ejemplo `8787`)

Si tenÃ­as una versiÃ³n vieja escuchando en `8787`, haz esto en **PowerShell**:

```powershell
# Ver quÃ© proceso estÃ¡ usando el puerto 8787
Get-NetTCPConnection -LocalPort 8787 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess, State

# Ver detalles del proceso (si existe)
Get-Process -Id (Get-NetTCPConnection -LocalPort 8787 -State Listen).OwningProcess
```

Alternativa clÃ¡sica:

```powershell
netstat -ano | findstr :8787
tasklist /FI "PID eq <PID>"
```

Si quieres cerrar ese proceso:

```powershell
Stop-Process -Id <PID> -Force
# o
taskkill /PID <PID> /F
```

Y para cerrar el puerto en Firewall (quitar la regla que lo abrÃ­a):

```powershell
# Busca reglas que incluyan el puerto 8787
Get-NetFirewallPortFilter -Protocol TCP | Where-Object { $_.LocalPort -eq "8787" } |
  Get-NetFirewallRule |
  Select-Object DisplayName, Enabled, Direction, Action

# Elimina una regla concreta por nombre (ejemplo)
Remove-NetFirewallRule -DisplayName "Xaloc - Puerto antiguo (8787)"
```

Si no recuerdas el nombre exacto de la regla:

```powershell
Get-NetFirewallRule | Where-Object DisplayName -like "*8787*" | Select-Object DisplayName
```

### 4c. Inventario completo antes de abrir puertos nuevos (evitar sobrescribir)

Para no pisar puertos/reglas existentes, revisa primero este inventario.

**1) Todos los puertos en escucha en este PC (TCP):**

```powershell
Get-NetTCPConnection -State Listen |
  Sort-Object LocalPort |
  Select-Object LocalAddress, LocalPort, OwningProcess, State
```

Con nombre de proceso:

```powershell
$listening = Get-NetTCPConnection -State Listen
$listening | ForEach-Object {
  [PSCustomObject]@{
    LocalAddress = $_.LocalAddress
    LocalPort    = $_.LocalPort
    PID          = $_.OwningProcess
    ProcessName  = (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName
  }
} | Sort-Object LocalPort | Format-Table -AutoSize
```

**2) Todos los puertos UDP en escucha:**

```powershell
Get-NetUDPEndpoint |
  Sort-Object LocalPort |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

**3) Todas las reglas Firewall habilitadas de entrada (Allow):**

```powershell
Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow |
  Select-Object DisplayName, Profile |
  Sort-Object DisplayName
```

**4) Puertos asociados a esas reglas (TCP/UDP):**

```powershell
Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow |
  Get-NetFirewallPortFilter |
  Select-Object Protocol, LocalPort, RemotePort, IcmpType |
  Sort-Object Protocol, LocalPort
```

**5) Verificar si un puerto concreto ya estÃ¡ ocupado o permitido (ejemplo `8080`):**

```powershell
# Â¿Lo usa algÃºn proceso?
Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue

# Â¿Hay regla de firewall para ese puerto?
Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow |
  Get-NetFirewallPortFilter |
  Where-Object { $_.Protocol -eq "TCP" -and $_.LocalPort -eq "8080" }
```

> Nota: estos comandos muestran puertos del **PC actual** (servicios locales + firewall local).  
> No listan automÃ¡ticamente puertos abiertos de otros equipos del WiFi.

---

## Paso 5 â€” Levanta el stack con Docker Compose

Desde la raÃ­z del proyecto (donde estÃ¡ `.env`):

```powershell
cd infra\docker
docker compose -f docker-compose.microservices.yml --env-file ..\..\\.env up -d
```

> El flag `--env-file` asegura que el `.env` de la raÃ­z se cargue correctamente (el compose estÃ¡ dos niveles dentro del proyecto).

Para ver los logs de todos los servicios en tiempo real:

```powershell
docker compose -f docker-compose.microservices.yml logs -f
```

Para logs de un servicio especÃ­fico:

```powershell
docker compose -f docker-compose.microservices.yml logs -f api-gateway
docker compose -f docker-compose.microservices.yml logs -f dashboard-backend-service
```

Para parar todo:

```powershell
docker compose -f docker-compose.microservices.yml down
```

---

## Paso 6 â€” Arranca el frontend Next.js (si usas modo dev)

Si `DASHBOARD_FRONTEND_DEV=1` en `.env`, el api-gateway espera que Next.js corra en `localhost:3000` como proceso separado. Tienes dos opciones:

### OpciÃ³n A: Next.js en Docker (modo producciÃ³n, recomendado para compartir por WiFi)

Cambia en `.env`:
```env
DASHBOARD_FRONTEND_DEV=0
```

El contenedor `api-gateway` arrancarÃ¡ Next.js en modo `build` automÃ¡ticamente (hace `npm install` + `npm run build` si no hay `.next`). Es mÃ¡s lento la primera vez pero no necesita ningÃºn proceso externo.

### OpciÃ³n B: Next.js en modo dev en Windows (mÃ¡s rÃ¡pido para desarrollo)

```powershell
cd dashboard-frontend
npm install
npm run dev -- --hostname 0.0.0.0 --port 3000
```

> **IMPORTANTE**: el `--hostname 0.0.0.0` hace que Next.js escuche en todas las interfaces.  
> Sin esto, el dev server solo acepta conexiones de `localhost` y el api-gateway no puede proxy-earlo si estÃ¡ en Docker.

---

## Paso 7 â€” Verifica que todo funciona

### Desde el mismo PC (localhost):

```powershell
# Â¿El api-gateway responde?
curl http://localhost:8080/api/health

# Â¿El dashboard-backend responde?
curl http://localhost:8788/api/health

# Â¿El auth-rbac responde?
curl http://localhost:8101/health
```

### Desde otro dispositivo del WiFi:

Abre el navegador y ve a:

- **Dashboard**: `http://192.168.X.Y:8080`
- **noVNC** (ver el runner en vivo): `http://192.168.X.Y:6080/vnc.html`

Si el dashboard carga pero el login falla con error CORS, repasa el **Paso 2a**.

---

## Resumen rÃ¡pido de cambios

| Archivo | QuÃ© cambiar |
|---|---|
| `.env` lÃ­nea 60 | AÃ±adir `http://192.168.X.Y:8080` a `DASHBOARD_CORS_ORIGINS` |
| `.env` (opcional) | `XALOC_NOVNC_PUBLIC_URL=http://192.168.X.Y/vnc/vnc.html?autoconnect=1&quality=9&compression=0` |
| `.env` (opcional) | `DASHBOARD_FRONTEND_DEV=0` para no depender del dev server |
| Windows Firewall | Regla inbound TCP para puertos 8080 y 6080 |

---

## Troubleshooting

### El dashboard carga pero las llamadas a `/api/*` dan CORS error

â†’ Falta la IP en `DASHBOARD_CORS_ORIGINS`. AÃ±Ã¡dela y reinicia el contenedor `dashboard-backend-service`.

```powershell
docker compose -f docker-compose.microservices.yml restart dashboard-backend-service
```

### No se puede conectar al puerto 8080 desde otro dispositivo

â†’ El firewall de Windows estÃ¡ bloqueando. Ejecuta el bloque del Paso 4.  
â†’ Verifica tambiÃ©n que el router no tiene AP Isolation activado (algunos routers WiFi bloquean comunicaciÃ³n entre clientes).

### noVNC no conecta

â†’ Comprueba que el contenedor `playwright-runner-service` estÃ¡ corriendo:
```powershell
docker ps | grep playwright
```
â†’ Verifica que el puerto 6080 estÃ¡ abierto en el firewall (Paso 4).

### El contenedor `api-gateway` falla al hacer build del frontend

â†’ Probablemente el primer arranque tarda mucho haciendo `npm install`. Mira los logs:
```powershell
docker compose -f docker-compose.microservices.yml logs -f api-gateway
```
â†’ Si falla con error de `lightningcss`, el compose ya tiene lÃ³gica para repararlo automÃ¡ticamente.

### `docker compose up` falla con error de volumen SMB (`clientes_smb`)

â†’ El volumen CIFS necesita acceso al servidor `SERVER-DOC`. Si no estÃ¡s en la red corporativa, puedes comentar temporalmente las lÃ­neas del volumen SMB en el compose para los servicios que no lo necesiten (brain-claim, worker-orchestrator, dashboard-backend).

---

## Morrigan Electron (clientes WiFi)

Objetivo: que cualquier PC del WiFi instale Morrigan y funcione sin tocar IP/puerto manualmente.

### 1) Usa IP LAN directa como base

Base actual recomendada: `192.168.184.72`.

- API base: `http://192.168.184.72:8080`
- WS base: `ws://192.168.184.72:8080/ws/dashboard`

### 2) Publica un bootstrap JSON centralizado

Sirve este fichero desde el gateway (ej. `http://192.168.184.72:8080/morrigan-config.json`):

```json
{
  "apiBaseUrl": "http://192.168.184.72:8080",
  "wsUrl": "ws://192.168.184.72:8080/ws/dashboard",
  "refreshIntervalSec": 120
}
```

Cuando cambies puerto/IP, solo actualizas este JSON en el servidor y los clientes se reajustan solos.

### 3) Abre CORS para el hostname estable

En `.env`:

```env
DASHBOARD_CORS_ORIGINS=...,http://192.168.184.72:8080
```

### 4) Instalador Windows

En `morrigan-electron/electron-builder.yml` ya queda listo para operaciÃ³n interna:

- acceso directo de escritorio siempre (`createDesktopShortcut: always`)
- acceso directo menÃº inicio
- ejecuciÃ³n tras instalar
- instalaciÃ³n por mÃ¡quina (`perMachine: true`)

### 5) Autoinicio + sesiÃ³n

La app se configura para iniciar con Windows (`openAtLogin`) y, al arrancar, valida sesiÃ³n real contra `/api/auth/me`.
Si la cookie sigue vigente, entra sola; si no, muestra login.

