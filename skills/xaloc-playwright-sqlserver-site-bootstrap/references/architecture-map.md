# Architecture Map

## Scope

Use this map to integrate a new `site_id` across Playwright automation, SQL extraction, queue pipeline, and dashboard surfaces.

## 1) Playwright Site Layer (`/sites`)

- Create `sites/<site_id>/` with:
  - `config.py`
  - `data_models.py`
  - `controller.py`
  - `automation.py`
  - `flows/__init__.py` plus stage files (`login.py`, `formulario.py`, `documentos.py`, `confirmacion.py`)
- Register site in:
  - `core/site_registry.py` (`SITES` dictionary)

Existing references:
- `sites/AGENTS.md`
- `sites/madrid/`
- `sites/ayunta_palma/`

## 2) Adapter Layer (`/sites/adapters`)

- Create `sites/adapters/<site_id>.py` implementing:
  - `fetch_candidates(...)`
  - `build_payloads(...)`
- Export adapter in:
  - `sites/adapters/__init__.py`

Base contract:
- `sites/adapters/site_adapter.py`

## 3) Brain Claim Registration (`/services/brain_claim`)

- Add adapter import in:
  - `services/brain_claim/app.py`
- Register instance inside `BrainClaimService.__init__` in `self.adapters`.

If missing here, the new site never enters candidate claim flow.

## 4) Config and Dashboard Backend

Configuration paths:
- Seed source: `organismo_config.json`
- PostgreSQL schema: `infra/postgres/init/003_admin_schema.sql` (`organismo_config`, `blocked_resources`)
- Store: `core/pg_admin_store.py`

Dashboard API routes:
- `dashboard_api.py`
  - `GET /api/config`
  - `PUT /api/config/{site_id}`
  - `POST /api/config/{site_id}/active`

## 5) Frontend Visibility (`/dashboard-frontend`)

Main management UI:
- `dashboard-frontend/app/gestion/page.tsx`
  - `KNOWN_SITES` list drives explicit UI ordering/presence.

Types:
- `dashboard-frontend/lib/types.ts`
  - `SiteID` already allows `string`, but still validate hardcoded site lists.

API client:
- `dashboard-frontend/lib/api.ts`

## 6) Runtime / Infra

Container topology:
- `infra/docker/docker-compose.microservices.yml`

Core services to verify:
- `brain-claim-service`
- `payload-validator-service`
- `batcher-dispatcher-service`
- `worker-orchestrator-service`
- `playwright-runner-service`
- `dashboard-backend-service`
- `api-gateway`

## 7) Minimum Integration Diff Checklist

1. New site package under `/sites/<site_id>`.
2. `core/site_registry.py` entry.
3. New adapter file under `/sites/adapters/<site_id>.py`.
4. Adapter exported in `sites/adapters/__init__.py`.
5. Adapter registered in `services/brain_claim/app.py`.
6. `organismo_config.json` entry for new `site_id`.
7. Optional: `KNOWN_SITES` update in frontend management page.
