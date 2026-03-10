# phased-migration-and-parity-plan.md

## Purpose
Define a low-risk phased migration strategy to centralized consultor retrieval with strict behavior parity controls.

## Scope
- Adapter-by-adapter migration
- Parity validation approach
- Test, rollout, and rollback per phase

## Relevant Files
- `services/brain_claim/app.py`
- `core/repositories/resource_repository.py`
- `sites/adapters/*.py`
- `services/payload_validator/app.py`
- `core/worker_execution/task_orchestrator.py`
- `tests/*adapter*`, `tests/*worker*`, new parity test suite

## Migration Principles
- Additive compatibility first.
- One adapter at a time.
- No removal of legacy query paths until parity proven in production.
- Feature flags for controlled rollout.

## Phase Slices

### Slice 1: Documentation + Contracts (no functional change)
- Deliver canonical model docs and consultor interface spec.
- Files likely to change:
  - new docs only.
- Tests to add:
  - none required yet.
- Rollout strategy:
  - design review gate.
- Rollback:
  - not applicable.
- Production checklist:
  - architecture approval + field ownership agreement.

### Slice 2: Consultor Compatibility Mode
- Implement consultor service reusing current SQL templates.
- Emit canonical + legacy alias maps.
- Keep adapters unchanged, switch call path via flag to consultor facade.
- Files likely to change:
  - `core/consultor/*` (new)
  - `services/brain_claim/app.py` (optional consultor call)
- New files likely:
  - `tests/parity/test_consultor_alias_parity.py`
  - `tests/parity/fixtures/*.json`
- Tests to add:
  - canonical mapping unit tests
  - row-to-alias parity snapshot tests
- Rollout strategy:
  - disabled by default, canary on one non-critical site in shadow mode.
- Rollback:
  - disable feature flag.
- Production checklist:
  - no increase in incident rates, no claim throughput drop.

### Slice 3: Safest First Adapter Migration
- Migrate first adapter to consume canonical consultor output.
- Recommended first adapter: `ayunta_palma` (smaller field surface and simpler payload contract).
- Files likely to change:
  - `sites/adapters/ayunta_palma.py`
  - `services/brain_claim/app.py` (site flag wiring)
- New tests:
  - `tests/parity/test_ayunta_palma_payload_parity.py`
- Rollout strategy:
  - single-site canary window, compare old/new payload dumps per `idRecurso`.
- Rollback:
  - per-site flag off and revert to legacy adapter path.
- Production checklist:
  - deterministic payload equivalence for sampled resources
  - no new `SITE_RULE_DISCARDED` anomalies.

### Slice 4: Incremental Migration of Remaining Adapters
- Migrate in this order:
  1. `terrassa`
  2. `redsara`
  3. `xaloc_girona`
  4. `base_online`
  5. `madrid` (highest complexity)
- Files likely to change:
  - `sites/adapters/*.py` one-by-one
  - parity fixtures/tests
- Tests to add:
  - one parity suite per adapter
  - integration smoke over candidate->validated pipeline.
- Rollout strategy:
  - staggered feature flags by site.
- Rollback:
  - site-level fallback to legacy input shape.
- Production checklist:
  - incident baseline stable
  - queue metrics stable
  - no increased worker retries.

### Slice 5: Downstream Decoupling + Cleanup
- Migrate payload consumers to rely on canonical completeness and remove direct SQL rehydration.
- Decommission duplicate SQL retrieval logic only after sustained parity.
- Files likely to change:
  - `services/payload_validator/app.py`
  - `core/worker_execution/task_orchestrator.py`
  - `core/repositories/resource_repository.py` (deprecation)
- Tests to add:
  - regression tests asserting no SQL fallback invocation in green path
  - end-to-end stream-to-worker contract tests.
- Rollout strategy:
  - dual-write telemetry period before removal.
- Rollback:
  - re-enable fallback code path behind feature flag.
- Production checklist:
  - fallback counter near zero for multiple cycles
  - no data-loss incidents.

## Parity Validation Approach
- Deterministic comparison keys:
  - `site_id`, `idRecurso`, `idExp`, `expediente`
- Compare artifacts:
  - candidate filters (included/discarded reason)
  - built payload (normalized ordering)
  - controller map output
- Tolerate known non-deterministic fields:
  - timestamps (`claimed_at`, `validated_at`)
  - generated trace IDs.

## Test Strategy by Phase
- Unit tests:
  - canonical mapping, normalization rules, alias compatibility.
- Parity tests:
  - old vs new payload snapshot per adapter.
- Integration tests:
  - candidate stream -> validated stream -> worker map_data/create_target smoke.
- Manual verification:
  - runbook with sample ids per site and output diff review.

## Risks
- Site-specific regex/business rules may interact with normalized values unexpectedly.
- Controller alias assumptions may hide missing canonical fields until runtime.

## Recommendations
- Add observability counters:
  - consultor hits per site
  - fallback SQL hydration calls
  - payload parity mismatch count
- Enforce entry/exit criteria per slice before progressing.

## Open Questions
- Final tolerance policy for payload diffs (strict vs semantically equivalent transforms)?

## Exact Next Steps
1. Create parity fixture generator from current production-like candidate samples.
2. Implement consultor facade and shadow comparison logging.
3. Start Slice 3 with `ayunta_palma` after 1-2 days of shadow data.
