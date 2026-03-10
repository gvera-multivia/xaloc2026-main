# Integration Checklist

## Input Checklist

Confirm before coding:

1. `site_id` definitivo.
2. URL base y pasos Playwright en orden.
3. Selectores confiables por paso.
4. Punto exacto de parada (si no se debe enviar/finalizar).
5. Campos SQL Server mínimos para:
- seleccionar recurso
- completar formulario
- adjuntar documentos

## Implementation Checklist

1. Scaffold site:
- `sites/<site_id>/config.py`
- `sites/<site_id>/data_models.py`
- `sites/<site_id>/controller.py`
- `sites/<site_id>/automation.py`
- `sites/<site_id>/flows/*.py`

2. Register site:
- `core/site_registry.py`

3. Create adapter:
- `sites/adapters/<site_id>.py`
- export in `sites/adapters/__init__.py`

4. Wire adapter in claim service:
- `services/brain_claim/app.py`

5. Seed config:
- append `site_id` block in `organismo_config.json`

6. Frontend/admin visibility:
- validate `dashboard-frontend/app/gestion/page.tsx` (`KNOWN_SITES`)
- verify `/api/config` surfaces new site

## Validation Checklist

1. Syntax/import checks for new files.
2. `core/site_registry.py` contains new key.
3. `BrainClaimService.adapters` contains new key.
4. `GET /api/config` includes new `site_id` after seed/sync.
5. Admin page displays/accepts activate-deactivate for new site.
6. One dry-run execution reaches expected safe stop.

## Recommended Command Sequence

```powershell
python -m py_compile sites\<site_id>\automation.py
python -m py_compile sites\adapters\<site_id>.py
python -m py_compile services\brain_claim\app.py
python -m py_compile core\site_registry.py
```

Then run the local orchestrated flow used by your environment to confirm registration and queue visibility.
