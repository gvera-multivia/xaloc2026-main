# Production Integration Workflow

## Scope

Usar este runbook para pasar de `main_<site>_payload_by_id.py` a integracion productiva completa.

## Step 1: Baseline de standalone

1. Confirmar que `main_<site>_payload_by_id.py --id <id> --dump-only` genera payload valido.
2. Confirmar que `--run-flow` llega al punto de parada esperado.
3. Guardar ejemplo real de payload final (tmp JSON) para comparar con adapter.

## Step 2: Site runtime

1. Verificar carpeta `sites/<site_id>/`.
2. Registrar `site_id` en `core/site_registry.py`.
3. Validar imports:
- `python -m py_compile sites/<site_id>/automation.py`
- `python -m py_compile sites/<site_id>/controller.py`

## Step 3: Adapter + brain

1. Crear `sites/adapters/<site_id>.py` implementando:
- `fetch_candidates(...)`
- `build_payloads(...)`
2. Exportar en `sites/adapters/__init__.py`.
3. Registrar en `services/brain_claim/app.py` (`self.adapters`).
4. Anadir config inicial en `organismo_config.json`.

## Step 4: Worker confirmacion

1. Verificar que payload conserva `idRecurso`.
2. Verificar que `core/worker_execution/task_orchestrator.py` ejecuta `mark_resource_complete(...)` cuando `outcome.success`.
3. Si el site requiere excepcion de completado automatico, documentarla y condicionar por `site_id`.

## Step 5: Dashboard

1. Comprobar `GET /api/config` en backend.
2. Comprobar `dashboard-frontend/app/gestion/page.tsx` (`KNOWN_SITES` si aplica).
3. Validar que el site se puede activar/desactivar.

## Step 6: Certificado de login

Actualizar lista de patrones/origenes en los 3 puntos:

1. `core/base_automation.py`
2. `infra/docker/playwright-runner-entrypoint.sh`
3. `url-cert-config.bat`

## Step 7: Validacion final

1. Compilar archivos tocados.
2. Ejecutar tick controlado de brain/worker.
3. Verificar:
- candidato publicado en stream
- procesamiento worker exitoso
- recurso marcado completado en XVIA
