# final-canonical-migration-execution-plan.md

## Purpose
Execution plan to finish the migration to a canonical, consultor-centered data contract across retrieval, adapters, validators, controllers, and worker flows.

## Scope
- Complete remaining migration work after current progress.
- Remove residual legacy/raw SQL-shape dependencies.
- Ship with parity, rollback, and production verification gates.

## Current State (as of 2026-03-10)
- `core/consultor/*` exists and emits `__canonical_v1`.
- Adapters no longer do direct SQL queries and require injected `resource_repo`.
- Brain-claim path is consultor-backed.
- Legacy consultor alias shim (`__legacy_aliases`) has been removed.
- Canonical-first controller mapping is implemented for:
  - `sites/ayunta_palma/controller.py`
  - `sites/terrassa/controller.py`
  - `sites/redsara/controller.py`
  - `sites/xaloc_girona/controller.py`
  - `sites/base_online/controller.py`
  - `sites/madrid/controller.py`
- Centralized defaults implemented for:
  - Contact data (`core/contact_defaults.py`)
  - Representative address/CP/country defaults (`core/address_defaults.py`)
- Canonical-first fallback in validator paths:
  - `services/brain_claim/processable_validator.py`
  - `services/payload_validator/app.py`
- Phase 3 completed in code:
  - `services/payload_validator/app.py` no longer performs SQL hydration.
  - Validator normalization is canonical-only (`_normalize_payload` + default email completion).
  - New tests cover canonical-only validator behavior.
- Phase 4 started (safe cleanup slice):
  - Removed stale consultor-compatibility/parity-shadow branch from `services/brain_claim/app.py`.
  - `core/brain/orchestrator.py` now has hard runtime guard: disabled by default; emergency opt-in via `ALLOW_LEGACY_BRAIN_ORCHESTRATOR=1`.
- Phase 5 prepared:
  - Operational canary/promotion/rollback runbook created in `docs/consultor-migration/phase5-canary-rollout-runbook.md`.
- Targeted migration/parity tests are passing (`24 passed`).
- Full `pytest -q` currently blocked by missing optional dependency: `python-multipart` (error in `scripts/test_count.py` collection).

## Completion Criteria
1. `ResourceRepository` retrieval is canonicalized and no consumer depends on adapter-specific SQL shape.
2. Controllers/flows consume canonical-first mappings (legacy fallback removed or explicitly deprecated).
3. Payload validator no longer hydrates from SQL in normal path.
4. Integration parity is proven in staging and canary production.
5. Obsolete migration scaffolding and dead paths are removed.

## Execution Principles
- One bounded slice at a time.
- No broad refactor without parity test for that slice.
- Any semantic ambiguity becomes a verification task, not a guess.
- Rollback path must exist before enabling each slice in production.

## Phase 1: Canonicalize Retrieval Contract

### Objective
Move retrieval responsibility to a single canonical contract in `ResourceRepository`/consultor boundary.

### Tasks
1. Refactor `core/repositories/resource_repository.py` to define one canonical retrieval profile plus minimal site-specific filters.
2. Ensure retrieval always includes all fields needed to build `__canonical_v1` without downstream SQL hydration.
3. Add contract tests for `ResourceRepository -> ConsultorService -> __canonical_v1`.

### Files Likely to Change
- `core/repositories/resource_repository.py`
- `core/consultor/normalizer.py`
- `core/consultor/service.py`
- `tests/test_consultor_service.py`
- new: `tests/test_consultor_repository_contract.py`

### Exit Criteria
- All consultor tests pass.
- No site adapter requires fields absent from canonical contract.

### Rollback
- Revert `ResourceRepository` contract changes only; keep adapter runtime contract unchanged.

## Phase 2: Controller Boundary Canonicalization (Site by Site)

### Objective
Make each site controller map canonical payload fields first, then remove legacy key dependence.

### Migration Order
1. `ayunta_palma`
2. `terrassa`
3. `redsara`
4. `xaloc_girona`
5. `base_online`
6. `madrid`

### Tasks per Site
1. Add a controller-side mapper that accepts canonical-first payload.
2. Keep temporary legacy fallback in that controller only.
3. Add site parity tests: `adapter payload -> controller map_data/create_target`.
4. Remove temporary fallback once parity is stable for that site.

### Files Likely to Change
- `sites/<site>/controller.py`
- `sites/<site>/flows/*.py` (only where direct legacy keys are used)
- `core/worker_execution/browser_executor.py` (if shared mapping helpers needed)
- new tests per site under `tests/`

### Exit Criteria
- Site controller path works with canonical-only payload input in tests.
- No regression in existing site-specific flow tests.

### Rollback
- Re-enable temporary legacy fallback in affected site controller only.

## Phase 3: Remove SQL Hydration Fallback in Payload Validator

### Objective
Eliminate `payload_validator` SQL rehydration in normal operation.

### Tasks
1. Add explicit completeness checks for canonical payloads in validator.
2. Gate SQL hydration behind emergency feature flag (default OFF), then remove after stabilization.
3. Add metrics/logging for fallback hits during transition.

### Files Likely to Change
- `services/payload_validator/app.py`
- new: `tests/test_payload_validator_canonical_only.py`

### Exit Criteria
- Zero SQL hydration calls in staging/prod canary over agreed window.
- Validator outputs unchanged for sampled workloads.

### Rollback
- Temporary emergency flag to re-enable hydration for specific sites.

## Phase 4: Decommission Legacy Runtime Paths

### Objective
Remove old paths that are no longer part of canonical architecture.

### Tasks
1. Confirm whether `core/brain/orchestrator.py` is active in any environment.
2. If inactive, deprecate/remove it or mark explicitly as legacy with guard rails.
3. Remove any remaining legacy-field dual-read code not required by active controllers.

### Files Likely to Change
- `core/brain/orchestrator.py` (or deployment config/docs)
- `services/brain_claim/*`
- `sites/*/controller.py` and shared utils

### Exit Criteria
- Runtime path documentation matches deployed reality.
- No unused legacy branches in active path.

### Rollback
- Keep tagged release before cleanup and a short-lived rollback branch.

## Phase 5: Production Parity, Canary, and Full Rollout

### Objective
Ship canonical-only data contract safely.

### Tasks
1. Canary rollout per site (same order as Phase 2).
2. Compare key artifacts for each claimed resource:
   - claim/discard behavior
   - normalized payload fields
   - controller target construction
3. Promote site only after acceptance gate passes.

### Production Gate (Per Site)
- No increase in:
  - `SITE_RULE_DISCARDED`
  - `REGEX_DISCARDED` (unexpected deltas)
  - worker retries/failures
- Throughput and queue latency within normal band.
- Manual sample review approved.

### Rollback
- Site-level toggle to previous stable mapping release.
- Replay pending jobs from last known good point where applicable.

## Test Plan (Mandatory)

### Unit
- Canonical field mapping and normalization.
- Controller canonical mapping behavior.
- Validator canonical completeness behavior.

### Parity
- Legacy vs canonical payload parity snapshots by site.
- Deterministic comparison excluding volatile keys (`claimed_at`, trace IDs).

### Integration
- `candidate -> validated -> worker` smoke per site.
- One happy path + one discard path per site.

### Regression
- Existing adapter/controller/flow tests must stay green.

## Risks and Controls
- Risk: Hidden low-frequency legacy key dependence in site flows.
  - Control: site-by-site controller parity tests and canary.
- Risk: Canonical contract missing edge fields.
  - Control: contract tests from `ResourceRepository` through consultor and adapter.
- Risk: Production drift not visible in test data.
  - Control: sampled live parity checks during canary.

## Work Breakdown (Actionable Checklist)
- [x] Phase 1 retrieval canonicalization + contract tests
- [x] Phase 2 site controller canonicalization (`ayunta_palma`)
- [x] Phase 2 site controller canonicalization (`terrassa`)
- [x] Phase 2 site controller canonicalization (`redsara`)
- [x] Phase 2 site controller canonicalization (`xaloc_girona`)
- [x] Phase 2 site controller canonicalization (`base_online`)
- [x] Phase 2 site controller canonicalization (`madrid`)
- [x] Phase 3 remove validator SQL hydration
- [x] Phase 4 remove/deprecate legacy runtime paths
- [ ] Phase 5 canary + full rollout completion (runbook ready; execution pending)

## Immediate Next Step
Execute **Phase 5** canary operations using `phase5-canary-rollout-runbook.md` starting with `ayunta_palma`.
