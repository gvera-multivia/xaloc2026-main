# Brain 2.0 Operations Runbook

Guia operativa para arrancar, migrar y validar el pipeline Brain 2.0:

- `brain-claim-service`
- `payload-validator-service`
- `batcher-dispatcher-service`
- `worker-orchestrator-service`

Incluye comandos para `cmd.exe` (Windows) y notas para PowerShell.

## 1. Requisitos previos

- Docker Desktop activo.
- `.env` configurado.
- Stack compose disponible en `infra/docker/docker-compose.microservices.yml`.

## 2. Arranque completo

Desde la raiz del repo:

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml up -d --build
```

Ver estado:

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml ps
```

## 3. Migracion Incidencias v2

### 3.1 Ejecutar migracion (cmd.exe)

```bat
type db\migrations\20260225_realtime_incidents_v2.sql | docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T postgres psql -U xaloc -d xaloc
```

### 3.2 Validar columnas nuevas

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T postgres psql -U xaloc -d xaloc -c "SELECT column_name FROM information_schema.columns WHERE table_name='realtime_incidents' AND column_name IN ('error_code','status','screenshot_path','resolved_at','resolved_by') ORDER BY column_name;"
```

Resultado esperado: 5 filas.

## 4. Reinicio de servicios del pipeline

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml restart brain-claim-service payload-validator-service batcher-dispatcher-service worker-orchestrator-service dashboard-backend-service
```

## 5. Logs del pipeline

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=150 brain-claim-service payload-validator-service batcher-dispatcher-service worker-orchestrator-service
```

## 6. Verificacion de Redis Streams

### 6.1 Longitud de streams

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T redis redis-cli XLEN candidates && docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T redis redis-cli XLEN validated && docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T redis redis-cli XLEN jobs
```

### 6.2 Estado de consumer groups

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T redis redis-cli XINFO GROUPS candidates && docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T redis redis-cli XINFO GROUPS validated && docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T redis redis-cli XINFO GROUPS jobs
```

## 7. Interpretacion rapida de resultados

### Caso sano

- `candidates`: `lag 0` en `validator_group`.
- `validated`: `lag 0` en `batcher_group`.
- `jobs`: `lag 0` en `worker_group`.

Esto indica que el pipeline consume y drena correctamente.

### Nota importante sobre `XLEN jobs = 0`

No implica fallo si `XINFO GROUPS jobs` muestra actividad y `lag 0`.
Con `QUEUE_STREAM_DELETE_ON_ACK=1`, los mensajes pueden borrarse tras `ACK`.

## 8. Verificacion en PostgreSQL

Estado agregado de jobs:

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T postgres psql -U xaloc -d xaloc -c "SELECT status, count(*) FROM jobs GROUP BY status ORDER BY status;"
```

Ultimos jobs:

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T postgres psql -U xaloc -d xaloc -c "SELECT id, status, dedup_key, queued_at, started_at, finished_at FROM jobs ORDER BY id DESC LIMIT 20;"
```

Incidencias Brain 2.0:

```bat
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T postgres psql -U xaloc -d xaloc -c "SELECT incident_type, error_code, status, count(*) FROM realtime_incidents GROUP BY incident_type, error_code, status ORDER BY count(*) DESC LIMIT 20;"
```

## 9. Errores comunes en Windows (cmd.exe)

### Error: `"#" no se reconoce como un comando`

Motivo: estas en `cmd.exe`; `#` es comentario de PowerShell/bash, no de CMD.

### Error: `Get-Content ...` no funciona

Motivo: `Get-Content` es PowerShell.
En CMD usa `type`.

### Error: `no such service: \``

Motivo: en CMD no existe el backtick `` ` `` para continuar linea.

- En CMD ejecuta comandos en una sola linea.
- Si necesitas multilinea en CMD, usa `^`.

## 10. Equivalente en PowerShell (opcional)

Si usas PowerShell puedes partir linea con backtick:

```powershell
Get-Content .\db\migrations\20260225_realtime_incidents_v2.sql |
  docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec -T postgres `
  psql -U xaloc -d xaloc
```

