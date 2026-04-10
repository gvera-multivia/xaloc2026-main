# Log Sources And Service Meaning

## Logs estables locales

- `logs/worker_out.log`
- `logs/brain_out.log`
- `logs/playwright_runner_out.log`
- `logs/frontend_out.log`

## Logs importantes por sintoma

### Brain

- candidate selection
- sync de `organismo_config`
- descartes tempranos
- publicacion a streams

### Worker

- consumo de job
- orchestration
- ACK/NACK
- errores de precondiciones, subida, justificante y completado

### Playwright runner

- request resumida por `site_id`
- inputs faltantes
- error de `execute_browser_flow`
- traceback del flujo real

### Payload validator / batcher dispatcher

- cuando el fallo parece ocurrir antes de worker
- si no hay archivo local util, usar `docker compose logs` del servicio

## Comandos utiles

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=200 brain-claim-service payload-validator-service batcher-dispatcher-service worker-orchestrator-service playwright-runner-service
```

## Regla practica

- si `job_draft` existe pero `job` no, mirar validator/batcher
- si `job` existe y no avanza, mirar worker/runtime
- si worker arranca y runner falla, mirar Playwright/site flow
- si la web completa pero XVIA no, mirar post-proceso y completado
