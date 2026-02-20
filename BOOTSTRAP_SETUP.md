# Bootstrap y .env (Fase 6)

Este documento deja el proyecto listo para arrancar desde cero con la arquitectura final:

- `USE_PG_SOURCE_OF_TRUTH=1`
- `QUEUE_MODE=redis_streams`
- Persistencia runtime solo en PostgreSQL + Redis
- Frontend conectado solo al `api-gateway`

## 1. Requisitos previos

## Sistema y herramientas

- Windows 10/11, Linux o macOS.
- Git.
- Python `3.11.x`.
- Node.js `20.x` o superior + npm.
- Docker Desktop + Docker Compose v2.

## Credenciales y accesos

- XVIA:
  - `XVIA_EMAIL`
  - `XVIA_PASSWORD`
- SQL Server (lectura de recursos):
  - `SQLSERVER_CONNECTION_STRING` (recomendado)
  - o `SQLSERVER_SERVER`, `SQLSERVER_DATABASE`, `SQLSERVER_USERNAME`, `SQLSERVER_PASSWORD` (+ opcional `SQLSERVER_DRIVER`, `SQLSERVER_TRUSTED_CONNECTION`, `SQLSERVER_PORT`, `SQLSERVER_TDS_VERSION`)
- GESDOC (si se usa documentacion obligatoria):
  - `GESDOC_USER`
  - `GESDOC_PWD`

## Certificado de firma

- Tipo: **PKCS#12** (`.pfx` o `.p12`).
- Ruta host esperada (en tu maquina): `<ROOT_DEL_REPO>/certificates/certificate.pfx`
- Ruta dentro del contenedor: `/data/certificates/certificate.pfx`
- En `docker-compose.microservices.yml` ya esta montado como solo lectura:
  - `../../certificates:/data/certificates:ro`

Si tu certificado es `.p12`, copialo con nombre `certificate.pfx`.

## Aclaracion de rutas (importante)

- `../../certificates` se evalua **relativo al archivo compose**:
  - Compose: `infra/docker/docker-compose.microservices.yml`
  - `infra/docker/../../certificates` => `<ROOT_DEL_REPO>/certificates`
- Por tanto:
  - En host debes tener: `<ROOT_DEL_REPO>/certificates/certificate.pfx`
  - En contenedor se vera como: `/data/certificates/certificate.pfx`

## Pasos exactos para instalar el certificado

1. Crea la carpeta en la raiz del repo:
   - `certificates/`
2. Copia tu certificado PKCS#12 dentro:
   - Si ya es `.pfx`: `certificates/certificate.pfx`
   - Si es `.p12`: copialo/renombralo a `certificates/certificate.pfx`
3. Verifica que existe el archivo:
   - Windows PowerShell:
     ```powershell
     Test-Path .\certificates\certificate.pfx
     ```
   - Linux/macOS:
     ```bash
     test -f ./certificates/certificate.pfx && echo OK
     ```
4. Arranca contenedores:
   ```powershell
   docker compose -f infra/docker/docker-compose.microservices.yml up -d
   ```
5. Verifica que el `signing-service` ve el certificado:
   ```powershell
   docker compose -f infra/docker/docker-compose.microservices.yml exec signing-service sh -lc "ls -l /data/certificates"
   ```
   Debes ver `certificate.pfx`.

## Nota SQL Server + pyodbc

`brain-claim-service` usa `pyodbc` dentro del contenedor.

En contenedores Linux de este proyecto se usa mejor `FreeTDS`:

- `.env`: `SQLSERVER_DRIVER=FreeTDS`
- `.env`: `SQLSERVER_PORT=1433`
- `.env`: `SQLSERVER_TDS_VERSION=7.4`
- si ejecutas scripts locales en Windows, puedes mantener `SQLSERVER_DRIVER={ODBC Driver 17 for SQL Server}`.
- En Docker, usa preferiblemente IP en `SQLSERVER_SERVER` (ej. `192.168.x.y`) en lugar de nombres NetBIOS como `BD-SERVER`.

## 2. Estructura minima esperada

En la raiz del repo:

- `.env`
- `certificates/certificate.pfx`
- `db/` (se crea sola si no existe)

## 3. .env completo recomendado

Crea `.env` en la raiz con este contenido base:

```env
# =========================
# FASE 6 (defaults finales)
# =========================
USE_PG_SOURCE_OF_TRUTH=1
QUEUE_MODE=redis_streams

# =========================
# Postgres / Redis
# =========================
REPORT_PG_DSN=postgresql://xaloc:xaloc_dev_password@postgres:5432/xaloc
PG_DSN=postgresql://xaloc:xaloc_dev_password@postgres:5432/xaloc

REDIS_ENABLED=1
REDIS_URL=redis://redis:6379/0

# =========================
# SQL Server
# (usa esta linea o las 4 de abajo)
# =========================
SQLSERVER_CONNECTION_STRING=DRIVER={ODBC Driver 17 for SQL Server};SERVER=TU_SERVER;DATABASE=TU_DB;UID=TU_USER;PWD=TU_PASS;TrustServerCertificate=yes
# SQLSERVER_DRIVER={ODBC Driver 17 for SQL Server}
# SQLSERVER_SERVER=TU_SERVER
# SQLSERVER_DATABASE=TU_DB
# SQLSERVER_USERNAME=TU_USER
# SQLSERVER_PASSWORD=TU_PASS
# SQLSERVER_TRUSTED_CONNECTION=1

# =========================
# XVIA / GESDOC
# =========================
XVIA_EMAIL=tu_email_xvia
XVIA_PASSWORD=tu_password_xvia

GESDOC_USER=tu_usuario_gesdoc
GESDOC_PWD=tu_password_gesdoc

# =========================
# Auth/RBAC y Gateway
# =========================
SECRET_KEY=cambia_esta_clave_por_una_larga_y_segura
DASHBOARD_JWT_ISSUER=xaloc-dashboard
DASHBOARD_JWT_AUDIENCE=xaloc-dashboard-clients
DASHBOARD_TOKEN_EXPIRE_MINUTES=480

DASHBOARD_ADMIN_USERNAME=admin
DASHBOARD_ADMIN_PASSWORD=cambiar_admin_password

AUTH_RBAC_SERVICE_URL=http://localhost:8101
DASHBOARD_BACKEND_URL=http://localhost:8788

DASHBOARD_CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
DASHBOARD_AUTH_COOKIE_SECURE=0
DASHBOARD_ENABLE_WS=1

# =========================
# Frontend/Gateway local
# =========================
DASHBOARD_FRONTEND_DEV=1
DASHBOARD_FRONTEND_HOST=127.0.0.1
DASHBOARD_FRONTEND_PORT=3000
API_GATEWAY_HOST=0.0.0.0
API_GATEWAY_PORT=8080

# =========================
# Streams (Control + Execution plane)
# =========================
CANDIDATES_STREAM_KEY=candidates
VALIDATED_STREAM_KEY=validated
QUEUE_STREAM_JOBS_KEY=jobs
QUEUE_STREAM_DLQ_KEY=dlq:jobs
DLQ_CANDIDATES_STREAM_KEY=dlq:candidates
DLQ_VALIDATED_STREAM_KEY=dlq:validated
DLQ_STREAM_MAXLEN=200000

VALIDATOR_STREAM_GROUP=validator_group
BATCHER_STREAM_GROUP=batcher_group
QUEUE_STREAM_GROUP=worker_group

VALIDATOR_BLOCK_MS=5000
BATCHER_BLOCK_MS=2000
BATCH_WINDOW_SECONDS=30
BATCH_MAX_SIZE=200
QUEUE_STREAM_MAXLEN=200000
QUEUE_MAX_ATTEMPTS=3
QUEUE_STREAM_DELETE_ON_ACK=1
QUEUE_DEDUPE_TTL_SECONDS=86400

# =========================
# Worker / Runner / Signing
# =========================
USE_PLAYWRIGHT_RUNNER_SERVICE=1
PLAYWRIGHT_RUNNER_URL=http://localhost:8111
PLAYWRIGHT_RUNNER_TIMEOUT_SECONDS=900
SIGNING_CERT_PATH=/data/certificates/certificate.pfx

WORKER_HEARTBEAT_SECONDS=5
WORKER_HEARTBEAT_TIMEOUT_SECONDS=90
WORKER_RECONCILE_INTERVAL_SECONDS=20
WORKER_RECONCILE_BATCH_SIZE=200

XALOC_HEADLESS=1
REQUIRE_CLIENT_DOCS=1
CLIENT_DOCS_MERGE=0
CLIENT_DOCS_BASE_PATH=\\\\SERVER-DOC\\clientes

# =========================
# Brain claim
# =========================
BRAIN_SYNC_INTERVAL=500
BRAIN_TICK_SECONDS=5
BRAIN_MAX_CLAIMS=999999
BRAIN_ENABLED_SITES=
BRAIN_CLAIM_MAX_PER_TICK=500
BRAIN_CLAIM_SYNC_SECONDS=30
```

## 4. Instalacion del proyecto

Desde la raiz:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

Frontend:

```powershell
cd dashboard-frontend
npm install
cd ..
```

## 5. Arranque recomendado (microservicios)

## 5.1 Levantar stack Docker

```powershell
docker compose -f infra/docker/docker-compose.microservices.yml up -d
```

Modo por defecto actual: **Docker completo**.
Se levanta todo en Docker con un unico comando:

```powershell
docker compose -f infra/docker/docker-compose.microservices.yml up -d
```

## 5.2 Accesos

- Gateway + frontend: `http://localhost:8080`
- Auth RBAC: `http://localhost:8101/health`
- Dashboard backend interno: `http://localhost:8788/docs`
- Jobs service: `http://localhost:8103/docs`
- Playwright runner: `http://localhost:8111/health`
- Signing service: `http://localhost:8112/health`

## 5.3 Usuario inicial

Se crea en `auth-rbac-service` con:

- `DASHBOARD_ADMIN_USERNAME`
- `DASHBOARD_ADMIN_PASSWORD`

## 5.4 Apagado y reinicio tras cambios

Usa esta guia rapida segun el tipo de cambio.

- Cambios en `.env`:
  ```powershell
  docker compose -f infra/docker/docker-compose.microservices.yml up -d --force-recreate
  ```
- Cambios en `docker-compose.microservices.yml`:
  ```powershell
  docker compose -f infra/docker/docker-compose.microservices.yml down
  docker compose -f infra/docker/docker-compose.microservices.yml up -d
  ```
- Cambios en servicios dockerizados (`playwright-runner-service`, `signing-service`):
  ```powershell
  docker compose -f infra/docker/docker-compose.microservices.yml up -d --build playwright-runner-service signing-service
  ```
- Reiniciar solo infraestructura (`postgres`, `redis`):
  ```powershell
  docker compose -f infra/docker/docker-compose.microservices.yml restart postgres redis
  ```
- Apagar todo Docker de este proyecto:
  ```powershell
  docker compose -f infra/docker/docker-compose.microservices.yml down
  ```
- Apagar todo + borrar volúmenes (reset total local):
  ```powershell
  docker compose -f infra/docker/docker-compose.microservices.yml down -v
  ```
  Advertencia: esto borra datos locales de PostgreSQL y Redis.

Chequeo rápido después de reiniciar:

```powershell
docker compose -f infra/docker/docker-compose.microservices.yml ps
curl.exe http://localhost:8101/health
curl.exe http://localhost:8788/health
curl.exe http://localhost:8080/health
curl.exe http://localhost:8111/health
curl.exe http://localhost:8112/health
```

## 6. Persistencia y colas

La persistencia de estado runtime es exclusivamente PostgreSQL y Redis Streams.

## 7. Comprobacion rapida de salud

```powershell
docker compose -f infra/docker/docker-compose.microservices.yml ps
docker compose -f infra/docker/docker-compose.microservices.yml logs -f --tail=100
```

## 8. Troubleshooting minimo

- Montaje de carpeta de clientes en Docker (host Linux):
  - monta primero el SMB en el host, por ejemplo en `/mnt/clientes`.
  - define en `.env`:
    ```env
    CLIENT_DOCS_HOST_PATH=/mnt/clientes
    ```
  - los contenedores usan `CLIENT_DOCS_BASE_PATH=/mnt/clientes`.
  - verifica desde contenedor:
    ```powershell
    docker compose -f infra/docker/docker-compose.microservices.yml exec worker-orchestrator-service sh -lc "ls -la /mnt/clientes | head"
    ```

- Error Redis/cola:
  - revisa `REDIS_ENABLED=1`, `REDIS_URL`.
- Error PostgreSQL:
  - revisa `REPORT_PG_DSN` y que `postgres` este healthy.
- Error certificado en signing:
  - verifica `certificates/certificate.pfx` y `SIGNING_CERT_PATH`.
- Error auth token:
  - revisa `SECRET_KEY`, `DASHBOARD_JWT_ISSUER`, `DASHBOARD_JWT_AUDIENCE`.
- Error SQL Server en brain-claim:
  - valida `SQLSERVER_CONNECTION_STRING` y driver ODBC.
- Error Docker `open //./pipe/dockerDesktopLinuxEngine`:
  - Docker Desktop daemon no esta levantado.
  - abre Docker Desktop y espera a que quede en estado "Engine running".
  - valida con:
    ```powershell
    docker version
    docker info
    docker context use desktop-linux
    ```
  - si sigue igual en Windows:
    ```powershell
    wsl --shutdown
    ```
    luego reinicia Docker Desktop.
- `npm audit fix` en raiz del repo da `ENOLOCK`:
  - correcto: ese comando solo aplica en `dashboard-frontend/` (donde existe `package-lock.json`).
  - usa:
    ```powershell
    cd dashboard-frontend
    npm install
    npm audit
    ```
  - evita `npm audit fix --force` salvo decision consciente (puede romper versiones de ESLint/Next).
- Error `Cannot find module '../lightningcss.linux-x64-gnu.node'` en `api-gateway`:
  - causa habitual: `node_modules` generados en Windows reutilizados dentro de contenedor Linux.
  - este compose ya monta volúmenes Linux para:
    - `/app/dashboard-frontend/node_modules`
    - `/app/dashboard-frontend/.next`
  - reconstruye solo el gateway:
    ```powershell
    docker compose -f infra/docker/docker-compose.microservices.yml up -d --build api-gateway
    ```

## 9. Nota de red en Docker

Dentro de contenedores, usa nombres de servicio Docker:

- PostgreSQL: `postgres:5432`
- Redis: `redis:6379`

No uses `localhost` en DSN/URL de servicios que corren dentro de Docker.
