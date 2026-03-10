---
name: xaloc-standalone-to-production-xvia-integration
description: Integrar un flujo standalone basado en `main_<site>_payload_by_id.py` al flujo productivo completo de Xaloc (Docker + brain + worker + dashboard + XVIA). Usar cuando ya existe automatizacion Playwright util para un organismo y hay que pasarla a produccion con seleccion/reclamacion de recursos en XVIA, reglas de organismo sancionador y expedientes validos en adapter, registro en site registry/brain claim, y actualizacion de listas de webs con inyeccion de certificado en login.
---

# Xaloc Standalone To Production Xvia Integration

## Overview

Convertir un site ya validado en standalone a una integracion productiva real dentro de este repo. Aplicar una secuencia fija para que no falte ningun punto de acoplamiento: site runtime, adapter SQL/XVIA, brain claim, worker, dashboard y politicas de certificado.

## Workflow

1. Confirmar entrada minima antes de tocar codigo.
- `site_id` definitivo.
- script standalone disponible (`main_<site>_payload_by_id.py`) y ejemplo real de `idRecurso`.
- criterio de seleccion por organismo sancionador en XVIA.
- lista de formatos de expediente validos (regex o reglas concretas).

2. Integrar el site runtime (Playwright).
- Verificar `sites/<site_id>/` con `config.py`, `data_models.py`, `controller.py`, `automation.py`, `flows/`.
- Registrar `site_id` en `core/site_registry.py`.
- Confirmar que `core/worker_execution/browser_executor.py` lo puede resolver por `get_site/get_site_controller`.

3. Integrar seleccion y reclamacion en brain (XVIA).
- Crear `sites/adapters/<site_id>.py` implementando:
  - `fetch_candidates(...)` con filtro de organismo sancionador y descartes trazables por `on_discard`.
  - `build_payloads(...)` con mapeo SQL -> payload productivo.
- Exportar adapter en `sites/adapters/__init__.py`.
- Registrar adapter en `services/brain_claim/app.py` dentro de `self.adapters`.
- Sembrar configuracion en `organismo_config.json` (`query_organisme`, `filtro_texp`, `regex_expediente`, `login_url`, `recursos_url`, `active`).

4. Integrar confirmacion de recurso en worker.
- Confirmar que el payload final incluye `idRecurso`.
- Verificar en `core/worker_execution/task_orchestrator.py` que tras `outcome.success` se ejecuta `mark_resource_complete(...)` para el site.
- Si el site necesita excepcion (como `base_online`), documentar la condicion explicita.

5. Integrar dashboard y visibilidad operativa.
- Revisar backend (`dashboard_api.py`) para asegurar que `/api/config` muestra el site.
- Revisar frontend:
  - `dashboard-frontend/app/gestion/page.tsx` (`KNOWN_SITES` si aplica orden fijo).
  - `dashboard-frontend/lib/types.ts` (normalmente no requiere cambio porque `SiteID` ya soporta `string`).

6. Actualizar inyeccion de certificado para nuevas webs de login.
- Actualizar patrones en:
  - `core/base_automation.py` (`_DEFAULT_CERT_PATTERNS` y `_DEFAULT_CLIENT_CERT_ORIGINS`).
  - `infra/docker/playwright-runner-entrypoint.sh` (`default_patterns` de policy).
  - `url-cert-config.bat` (entorno Windows local).
- Si hay mas de un host de login, incluir todos (dominio principal + subdominios de login/cert).

7. Validar end-to-end.
- Compilar archivos tocados.
- Ejecutar smoke local por `idRecurso`.
- Verificar que el recurso entra en candidatos brain, se publica a stream, se procesa en worker y queda confirmado en XVIA.

## Required References

- Flujo de integracion y checklist por capas:
  - `references/production-integration-workflow.md`
- Reglas de organismo sancionador y expedientes validos:
  - `references/xvia-organism-and-expediente-rules.md`
- Sitios con inyeccion de certificado en login:
  - `references/certificate-injection-sites.md`

## Script

- Generar checklist de integracion para un site:
  - `python skills/xaloc-standalone-to-production-xvia-integration/scripts/create_integration_checklist.py --site-id <site_id> --main-script main_<site_id>_payload_by_id.py`

## Output Contract

Al cerrar una ejecucion con esta skill, devolver:

1. Archivos creados/modificados por capa (`sites`, `adapters`, `brain`, `worker`, `dashboard`, `infra`).
2. Regla final de organismo sancionador (patrones XVIA) y lista de expedientes validos.
3. Cambios aplicados en lista de webs de certificado.
4. Resultado de validaciones ejecutadas y riesgos pendientes.

## Non-goals

- No mantener el site solo en standalone.
- No dejar un site en `core/site_registry.py` sin adapter registrado en brain.
- No desplegar un site nuevo sin actualizar politicas de certificado cuando su login usa certificado cliente.
