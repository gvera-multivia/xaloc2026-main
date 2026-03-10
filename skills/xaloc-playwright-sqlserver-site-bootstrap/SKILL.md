---
name: xaloc-playwright-sqlserver-site-bootstrap
description: Crear e integrar en este repositorio un nuevo site de Playwright conectado a SQL Server, cola de microservicios y dashboard (backend/frontend). Usar cuando el usuario entregue pasos Playwright (o un .md con flujo), campos SQL Server requeridos para extraer recursos, y se necesite dejar el site operativo de punta a punta en /sites, /infra, /dashboard y /dashboard-frontend.
---

# Xaloc Playwright SQL Server Site Bootstrap

## Overview

Implementar un workflow reproducible para convertir un "prompt Playwright + campos SQL" en un site nuevo, con adapter, registro en brain-claim, configuración en `organismo_config` y visibilidad en dashboard.

## Workflow

1. Normalizar entradas antes de codificar.
- Extraer `site_id` en snake_case.
- Extraer URL base, pasos Playwright secuenciales, selectores estables y punto de parada seguro.
- Extraer campos SQL obligatorios para `fetch_candidates` y campos finales para payload del worker.

2. Generar scaffold local.
- Ejecutar `python skills/xaloc-playwright-sqlserver-site-bootstrap/scripts/create_site_scaffold.py --site-id <site_id> --display-name "<Nombre>"`.
- Si ya existe un sitio parcial, ejecutar con `--dry-run` primero y luego adaptar manualmente.

3. Implementar lógica Playwright en `sites/<site_id>/flows`.
- Mantener funciones pequeñas por etapa (`login`, `formulario`, `documentos`, `confirmacion`).
- Reutilizar `BaseAutomation` y no duplicar lógica de infraestructura.
- Capturar evidencias y errores en cada etapa crítica.

4. Implementar adapter SQL Server en `sites/adapters/<site_id>.py`.
- Definir `fetch_candidates` con reglas de descarte y trazabilidad (`on_discard`).
- Definir `build_payloads` con mapeo explícito de campos y defaults seguros.
- Mantener consistencia de claves usadas por worker/documentación cliente.

5. Integrar backend y runtime.
- Registrar en `core/site_registry.py`.
- Exportar adapter en `sites/adapters/__init__.py`.
- Registrar adapter en `services/brain_claim/app.py` dentro de `self.adapters`.
- Añadir entrada en `organismo_config.json` para sembrado en PostgreSQL.

6. Integrar dashboard frontend/backend.
- Verificar endpoints de configuración en `dashboard_api.py` (`/api/config`, `/api/config/{site_id}/active`).
- Confirmar visibilidad del `site_id` en `dashboard-frontend/app/gestion/page.tsx` (`KNOWN_SITES`), si aplica.
- Confirmar tipos compatibles en `dashboard-frontend/lib/types.ts` (ya permite `string`, pero revisar tablas/filtros específicos).

7. Validar end-to-end.
- Ejecutar validación estática mínima de imports/sintaxis.
- Validar que el site se lista en registry.
- Validar que `brain-claim` reconoce el adapter nuevo.
- Validar que dashboard puede activar/desactivar configuración.

## Required References

- Arquitectura y puntos de integración: `references/architecture-map.md`
- SQL Server, query base y contrato de payload: `references/sqlserver-playbook.md`
- Checklist de implementación/validación: `references/integration-checklist.md`

## Constraints

- No asumir que basta con crear `/sites/<site_id>`; completar también adapter + registro en brain-claim + organismo_config.
- No dejar placeholders en código productivo.
- No introducir lógica de envío final sin confirmación explícita del usuario cuando el flujo de negocio requiera "stop before submit".

## Deliverable Format

Al finalizar una implementación con esta skill, devolver:

1. Lista de archivos creados/modificados.
2. Resumen de mapeo SQL -> payload.
3. Resultado de validaciones ejecutadas.
4. Riesgos pendientes o datos faltantes para producción.
