# Standalone Architecture

## Goal

Execute and validate a new site without worker/brain integration.

## Components Used

1. `sites/<site_id>/...`
- `config.py`
- `data_models.py`
- `controller.py`
- `automation.py`
- `flows/*.py`

2. `core/site_registry.py`
- Register site so `get_site` and `get_site_controller` can resolve it.

3. `core/worker_execution/browser_executor.py`
- Use `execute_browser_flow(...)` for direct local execution.
- This path runs automation directly and does not require queue consumers.

4. `main_<site_id>_payload_by_id.py`
- Query SQL Server by `idRecurso`.
- Build payload from SQL row.
- Map through controller.
- Optional execution of browser flow (`--run-flow`).

## Not Required for Standalone

- `sites/adapters/<site_id>.py`
- `services/brain_claim/app.py` registration
- `organismo_config` pipeline usage
- queue services / worker loop

## Existing Example Pattern

- `main_redsara_payload_by_id.py`
  - SQL fetch by id
  - build payload
  - controller mapping
  - dumps JSON artifacts for inspection
