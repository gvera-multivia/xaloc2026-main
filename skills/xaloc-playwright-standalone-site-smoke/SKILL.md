---
name: xaloc-playwright-standalone-site-smoke
description: Crear un nuevo site Playwright y validarlo en modo standalone local (sin integrar worker ni brain), generando un script tipo main_<site>_payload_by_id.py que consulta SQL Server, construye payload y permite smoke test del flujo para verificar que la automatización funciona antes de la integración completa.
---

# Xaloc Playwright Standalone Site Smoke

## Overview

Construir la base de un site y un runner local de comprobación rápida. Priorizar reproducibilidad de pruebas manuales, sin tocar pipeline de colas ni orquestación de producción.

## Workflow

1. Definir entrada mínima:
- `site_id`
- query SQL por `idRecurso`
- mapeo SQL -> payload para controller
- criterio de éxito del smoke test

2. Generar scaffold de site standalone:
- Ejecutar:
`python skills/xaloc-playwright-standalone-site-smoke/scripts/create_standalone_site_and_main.py --site-id <site_id> --display-name "<Nombre>"`
- El scaffold crea `sites/<site_id>/` y `main_<site_id>_payload_by_id.py`.

3. Implementar automatización Playwright:
- Completar `flows/login.py`, `flows/formulario.py`, `flows/documentos.py`, `flows/confirmacion.py`.
- Mantener captura de screenshot final y errores controlados.

4. Implementar smoke script:
- Completar query SQL y `build_payload_from_row(...)`.
- Usar el script para:
  - validar mapeo (`--dump-only`)
  - ejecutar flujo real (`--run-flow`) sin worker/brain

5. Verificar funcionamiento:
- Ejecutar un `idRecurso` real y revisar artifacts JSON/screenshot.
- Corregir selectores y mapeos hasta llegar al punto de parada esperado.

## Required References

- Arquitectura standalone: `references/standalone-architecture.md`
- Guía de smoke test: `references/smoke-test-runbook.md`

## Explicit Non-Goals

- No registrar adapters en `services/brain_claim/app.py`.
- No modificar `sites/adapters/__init__.py`.
- No añadir `site_id` al pipeline de worker/colas.

## Output Checklist

1. Archivos creados/modificados.
2. SQL -> payload mapping aplicado.
3. Comando exacto del smoke test ejecutado.
4. Resultado observado (JSON + screenshot + error si existe).
