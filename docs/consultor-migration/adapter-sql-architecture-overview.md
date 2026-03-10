# adapter-sql-architecture-overview.md

## Purpose
Document the current end-to-end architecture from SQL retrieval to adapter filtering, payload construction, and downstream execution.

## Scope
In-scope:
- `services/brain_claim/app.py` claim pipeline
- `core/repositories/resource_repository.py` centralized SQL retrieval
- `sites/adapters/*.py` candidate filtering + payload building
- `services/payload_validator/app.py` and `core/worker_execution/task_orchestrator.py` re-hydration from SQL
- `core/worker_execution/browser_executor.py` + `sites/*/controller.py` payload consumption

Out-of-scope:
- UI/dashboard SQL unrelated to candidate retrieval
- legacy-only paths not used by `brain-claim-service` runtime (still referenced as risk)

## Relevant Files
- `services/brain_claim/app.py`
- `core/repositories/resource_repository.py`
- `core/domain/resource_domain.py`
- `sites/adapters/base.py`
- `sites/adapters/madrid.py`
- `sites/adapters/xaloc_girona.py`
- `sites/adapters/ayunta_palma.py`
- `sites/adapters/redsara.py`
- `sites/adapters/terrassa.py`
- `services/payload_validator/app.py`
- `core/worker_execution/task_orchestrator.py`
- `core/worker_execution/browser_executor.py`
- `sites/*/controller.py`
- `core/site_registry.py`

## Observed Current Behavior
1. `BrainClaimService.run_tick()` loads active configs and iterates adapters by priority.
2. Each adapter calls `ResourceRepository.get_pending_resources(site_id=..., config=...)` in the primary path.
3. `ResourceRepository` runs a site-specific SQL template from `SQL_BY_SITE`, groups rows by `idRecurso`, and maps rows to `ResourceDomain` (while preserving full `metadata`).
4. Adapter `fetch_candidates()` applies site rules (regex, organismo filtering, ownership, completed-state filters, and business exclusions).
5. Adapter `build_payloads()` converts candidate metadata to site payload shape.
6. Candidate payload is published to Redis Stream (`candidates`) by `brain-claim-service`.
7. `payload-validator-service` may rehydrate payload with an extra `SELECT TOP 1 ... WHERE rs.idRecurso = ?` when identity fields are missing.
8. Worker pulls validated jobs and may again run SQL rehydration fallback (`_backfill_identity_from_sqlserver`) before controller mapping.
9. `browser_executor` maps payload through each site controller (`map_data` + `create_target`) and executes site automation.

## Text Flow Diagram
```text
SQL Server (Recursos.RecursosExp + joins)
  -> core/repositories/resource_repository.py (site SQL template + basic normalization)
  -> services/brain_claim/app.py
     -> sites/adapters/<site>.fetch_candidates() [site selection/filter rules]
     -> sites/adapters/<site>.build_payloads() [payload shaping + derivations]
     -> Redis Stream: candidates
  -> services/payload_validator/app.py
     -> optional SQL rehydrate fallback
     -> Redis Stream: validated
  -> worker loop
     -> core/worker_execution/task_orchestrator.py
        -> optional SQL rehydrate fallback
        -> core/worker_execution/browser_executor.py
           -> sites/<site>/controller.map_data()
           -> sites/<site>/controller.create_target()
           -> sites/<site>/automation + flows
```

## Current Module Boundaries
- Retrieval boundary (partially centralized): `ResourceRepository`.
- Site business selection boundary: `adapter.fetch_candidates`.
- Payload construction boundary: `adapter.build_payloads`.
- Consumer mapping boundary: `controller.map_data` and `controller.create_target`.
- Not cleanly enforced: fallback SQL hydration in validator/worker bypasses repository normalization.

## Findings
- A centralized query layer already exists (`ResourceRepository`) but behaves as a multi-template registry, not a canonical normalized consultor.
- Legacy adapter-local SQL remains in `base.py`, `madrid.py`, `ayunta_palma.py`, `xaloc_girona.py` fallback branches.
- Field semantics are duplicated across three stages:
  - query aliases (`cliente_*`, `rs_*`, `exp_*`, etc.)
  - adapter payload keys (site-specific)
  - controller map aliases (more site-specific + fallback names)
- Downstream consumers still depend on raw/legacy naming patterns, forcing SQL rehydration fallbacks.

## Duplication Hotspots
- SQL field hydration duplicates:
  - `ResourceRepository.SQL_BY_SITE`
  - adapter fallback SQL constants
  - `PayloadValidatorService._hydrate_payload_from_sql`
  - `task_orchestrator._backfill_identity_from_sqlserver`
- Identity and contact mapping duplicates across adapters.
- Plate/document normalization logic duplicated across adapters.
- Motivos text assembly duplicated in several adapters.

## Coupling Hotspots
- Controllers expect site-specific payload shapes and alias combinations.
- Worker fallback logic assumes SQL column naming from direct DB schema.
- Adapter payloads include controller-specific aliases (`exp_*`, `notif_*`, `p1_*`, etc.) directly.

## Assumptions
- Static analysis only; no runtime trace replay was executed in this task.
- Redis/queue behavior and browser flows are inferred from code paths.
- Legacy `core/brain/orchestrator.py` is not the current production claim path but remains a migration risk if still deployed in some environment.

## Risks
- Hidden regressions if canonicalization removes aliases still used by controllers.
- Over-centralization risk: consultor taking payload/business logic accidentally.
- Incomplete migration risk because validator/worker rehydration bypasses adapter outputs.

## Recommendations
- Introduce a dedicated consultor module above `ResourceRepository` to return canonical normalized records.
- Keep adapter responsibilities limited to site selection + site-specific derivations.
- Move generic identity/backfill hydration behind consultor API and remove ad-hoc SQL in validator/worker over time.
- Add explicit compatibility layer that can emit old aliases while new canonical fields roll out.

## Open Questions
- Is `core/brain/orchestrator.py` still active in any production node?
- Are there site-specific SQL constraints not represented in `SQL_BY_SITE` today?
- Which payload aliases are strictly required by each automation vs historical leftovers?

## Exact Next Steps
1. Freeze current field contracts per adapter/controller before any implementation.
2. Define canonical normalized model and a source-column mapping table.
3. Build consultor compatibility mode that emits both canonical and legacy aliases.
4. Add adapter-by-adapter parity tests comparing legacy payload vs consultor-based payload.
