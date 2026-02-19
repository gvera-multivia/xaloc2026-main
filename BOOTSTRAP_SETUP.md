# Bootstrap y .env (Fase 6)

Este documento deja el proyecto listo para arrancar desde cero con la arquitectura final:

- `USE_PG_SOURCE_OF_TRUTH=1`
- `QUEUE_MODE=redis_streams`
- SQLite congelada como respaldo (`SQLITE_WRITES_ENABLED=0`)
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
  - o `SQLSERVER_SERVER`, `SQLSERVER_DATABASE`, `SQLSERVER_USERNAME`, `SQLSERVER_PASSWORD` (+ opcional `SQLSERVER_DRIVER`, `SQLSERVER_TRUSTED_CONNECTION`)
- GESDOC (si se usa documentacion obligatoria):
  - `GESDOC_USER`
  - `GESDOC_PWD`

## Certificado de firma

- Tipo: **PKCS#12** (`.pfx` o `.p12`).
- Ruta host esperada: `certificates/certificate.pfx`
- Ruta dentro del contenedor: `/data/certificates/certificate.pfx`
- En `docker-compose.microservices.yml` ya esta montado como solo lectura:
  - `../../certificates:/data/certificates:ro`

Si tu certificado es `.p12`, copialo con nombre `certificate.pfx`.

## Nota SQL Server + pyodbc

`brain-claim-service` usa `pyodbc`. Si lo corres fuera de Docker en Windows, instala ODBC Driver 17/18 de SQL Server.

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
SQLITE_WRITES_ENABLED=0

# Solo para rollback temporal (no usar en normal)
# ALLOW_LEGACY_SQLITE_QUEUE=1

# =========================
# Postgres / Redis
# =========================
REPORT_PG_DSN=postgresql://xaloc:xaloc_dev_password@localhost:5432/xaloc
PG_DSN=postgresql://xaloc:xaloc_dev_password@localhost:5432/xaloc

REDIS_ENABLED=1
REDIS_URL=redis://localhost:6379/0

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

AUTH_RBAC_DB_PATH=db/auth_rbac.db
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

## 6. Congelar SQLite como backup temporal

Si quieres congelar fisicamente el archivo SQLite:

```powershell
python scripts/freeze_sqlite_readonly.py --db db/xaloc_database.db
```

Nota: el sistema ya va con writers SQLite desactivados por `SQLITE_WRITES_ENABLED=0`.

## 7. Comprobacion rapida de salud

```powershell
docker compose -f infra/docker/docker-compose.microservices.yml ps
docker compose -f infra/docker/docker-compose.microservices.yml logs -f --tail=100
```

## 8. Troubleshooting minimo

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

## 9. Ejecucion local alternativa (sin Docker completo)

Puedes ejecutar servicios sueltos en local:

```powershell
python run_gateway.py
```

o:

```powershell
uvicorn services.auth_rbac.app:app --host 0.0.0.0 --port 8101
uvicorn services.dashboard_backend.app:app --host 0.0.0.0 --port 8788
uvicorn services.api_gateway.app:app --host 0.0.0.0 --port 8080
```

Para pipeline completo, manten Postgres/Redis activos y levanta los workers/planes que necesites.
