# consolidated-consultor-migration-master-plan.md

## Purpose
Synthesize all workstreams into one migration-ready plan for replacing fragmented query+mapping logic with a unified consultation layer.

## Scope
- Consolidated current-state diagnosis
- Consolidated target-state architecture
- Implementation slices and file impact
- Test and risk controls

## Relevant Files
- Architecture: `services/brain_claim/app.py`, `core/repositories/resource_repository.py`, `sites/adapters/*.py`
- Consumers: `services/payload_validator/app.py`, `core/worker_execution/task_orchestrator.py`, `sites/*/controller.py`
- Registry/runtime: `core/site_registry.py`

## Consolidated Current-State Diagnosis
- Retrieval is partially centralized (`ResourceRepository`) but not canonicalized.
- Adapters still carry duplicated retrieval assumptions and custom transformations.
- Downstream components (validator and worker) re-query SQL to fill missing identity fields.
- Controller contracts depend on heterogeneous alias sets, increasing coupling.
- There is no single authoritative field semantics registry.

## Consolidated Target-State Architecture
- One consultor entrypoint responsible for:
  - SQL retrieval
  - normalization into canonical model
  - optional legacy alias compatibility output
- Adapters consume canonical records and apply only site business rules and site payload derivations.
- Payload consumers stop direct SQL hydration once completeness parity is proven.
- Controllers remain unchanged until late migration.

## Likely Implementation Slices

### Slice 1 (design-only, done in this task)
- Canonical field model + consultor architecture docs.

### Slice 2 (consultor compatibility mode)
- Create `core/consultor/*`.
- Integrate optional consultor path in `services/brain_claim/app.py`.
- Add canonical->legacy alias parity tests.

### Slice 3 (first adapter migration)
- Migrate `ayunta_palma` adapter to canonical consultor output.
- Add payload parity comparator for Palma.

### Slice 4 (incremental adapters)
- Migrate `terrassa`, `redsara`, `xaloc_girona`, `base_online`, `madrid`.
- Keep per-site feature flags.

### Slice 5 (consumer decoupling)
- Remove direct SQL fallback from validator and worker after parity/telemetry gates.
- Deprecate duplicate query logic.

## Exact Files Likely to Change
- New:
  - `core/consultor/contracts.py`
  - `core/consultor/sql_builder.py`
  - `core/consultor/normalizer.py`
  - `core/consultor/compat_aliases.py`
  - `core/consultor/service.py`
  - `tests/parity/*`
- Updated:
  - `services/brain_claim/app.py`
  - `sites/adapters/*.py`
  - `services/payload_validator/app.py`
  - `core/worker_execution/task_orchestrator.py`

## Tests Needed Before and During Migration
- Unit:
  - source-to-canonical mapping
  - doc/plate/address normalization rules
- Parity:
  - adapter payload parity snapshots per site
  - discard-reason parity checks
- Integration:
  - stream pipeline with consultor-enabled site toggles
- Regression:
  - no increase in worker retries, no drop in claim throughput.

## Unresolved Unknowns
- Whether legacy `core/brain/orchestrator.py` is still active in any environment.
- Exact set of truly required controller aliases after cleanup.
- Runtime performance impact of potential superset query profile.

## Cross-Check and Disagreements
- Workstream 2 vs Workstream 3:
  - adapter-level consumed fields and SQL-selected fields match on core entities, but some SQL columns are not clearly justified by current payload path (`exp_idpublic` in madrid).
  - action: treat as verification task, not immediate removal.
- Workstream 4 vs Workstream 6:
  - architecture goal is strict consultor boundary, but validator/worker currently re-query SQL.
  - action: defer removal of fallback SQL to Slice 5 only after measured payload completeness parity.
- Workstream 5 vs existing controller contracts:
  - canonical nested model is cleaner, while controllers still expect flat alias-heavy payloads.
  - action: compatibility alias layer required during migration windows.

Verification tasks derived from ambiguities:
1. Confirm production process ownership (`brain-claim-service` only vs any live `core/brain/orchestrator.py` usage).
2. Validate low-frequency fields with runtime telemetry before deprecation.
3. Benchmark consultor profile query plans on production-like datasets before enabling superset mode.

## Safest First Coding Slice
- Implement consultor facade that wraps existing `ResourceRepository` templates and returns canonical + legacy alias output without changing adapter logic.
- This keeps behavior stable while enabling parallel parity instrumentation.

## Assumptions
- Current production claim path uses `services/brain_claim/app.py`.
- Feature flags are available for phased rollout.

## Risks
- Silent semantic drift if canonical conversion reorders precedence logic.
- Hidden dependencies in low-frequency site flows.

## Recommendations
- Treat migration as contract evolution, not refactor-only.
- Promote parity metrics to release criteria.

## Open Questions
- Final canonical schema versioning policy (`v1`, `v2` compatibility windows)?

## Exact Next Steps
1. Approve canonical schema and consultor boundaries.
2. Implement Slice 2 under feature flag with shadow parity logs.
3. Execute Slice 3 on `ayunta_palma` and validate with deterministic payload diffs.
