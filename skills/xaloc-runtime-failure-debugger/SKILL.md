---
name: xaloc-runtime-failure-debugger
description: Depurar fallos de ejecucion reales en Xaloc leyendo historico PostgreSQL, jobs, job_drafts, runtime, logs y codigo para determinar por que falla un recurso o job y proponer la solucion correcta. Usar cuando haya incidencias de cola, runner, worker, brain, payload o confirmacion y se necesite causa raiz con evidencia.
---

# Xaloc Runtime Failure Debugger

## Overview

Diagnosticar fallos de ejecucion end-to-end a partir de evidencia real, no de intuicion. Empezar por la traza operativa en PostgreSQL y logs; despues mapear el fallo al codigo exacto y cerrar con hipotesis raiz y fix verificable.

## Workflow

1. Fijar la unidad de analisis.
- `site_id`
- `resource_id`
- `job_id` si ya se conoce
- ventana temporal aproximada

2. Recoger contexto operativo.
- Ejecutar:
`python skills/xaloc-runtime-failure-debugger/scripts/collect_failure_context.py --site-id <site_id> --resource-id <resource_id>`
- Si ya tienes `job_id`:
`python skills/xaloc-runtime-failure-debugger/scripts/collect_failure_context.py --site-id <site_id> --resource-id <resource_id> --job-id <job_id>`

3. Determinar la capa que rompe primero.
- config / candidate selection
- payload validation / job draft
- dispatch / jobs
- worker / runner
- flow Playwright del site
- XVIA / completado / post-proceso

4. Comparar evidencia con codigo.
- `core/worker_execution/*`
- `services/brain_claim/app.py`
- `services/payload_validator/app.py`
- `services/playwright_runner/app.py`
- `sites/<site_id>/*`

5. Proponer arreglo concreto.
- causa raiz
- archivo(s) y condicion exacta
- fix minimo correcto
- validacion posterior al fix

## Required References

- Mapa de datos y consultas utiles:
  - `references/postgres-debug-map.md`
- Fuentes de logs y significado operativo:
  - `references/log-sources-and-service-meaning.md`
- Secuencia de diagnostico y cierre:
  - `references/root-cause-workflow.md`

## Output Contract

Al cerrar una ejecucion con esta skill, devolver:

1. Sintoma observado.
2. Primera capa donde falla realmente.
3. Evidencia concreta usada: tablas, job state, incidencias, logs y codigo.
4. Causa raiz mas probable.
5. Fix propuesto con archivo(s) concretos.
6. Como validar que el fix funciona.

## Non-goals

- No reintentar ni desbloquear recursos sin entender antes la causa raiz.
- No quedarse solo en logs si Postgres/historico contradice la hipotesis.
- No asumir que el error visible en worker es siempre el origen; puede venir de candidate, payload o site flow.
