# unified-consultor-architecture-plan.md

## Purpose
Design the target centralized consultor abstraction for retrieval + normalization while preserving adapter and payload boundaries.

## Scope
- Consultor module boundaries
- Return model and call flow
- Extension strategy
- Compatibility and migration fit

## Relevant Files
- Current: `core/repositories/resource_repository.py`, `core/domain/resource_domain.py`
- Callers: `services/brain_claim/app.py`, adapters, validator, worker fallback utilities
- Consumers: site controllers

## Target Module Architecture

### Proposed New Modules
- `core/consultor/__init__.py`
- `core/consultor/contracts.py` (canonical types)
- `core/consultor/query_profiles.py` (site/core profiles)
- `core/consultor/sql_builder.py` (query assembly)
- `core/consultor/normalizer.py` (source -> canonical mapping)
- `core/consultor/compat_aliases.py` (canonical -> legacy aliases)
- `core/consultor/service.py` (public API)

### Existing Module Role After Migration
- `core/repositories/resource_repository.py` becomes adapter/deprecated facade or low-level SQL executor.
- Adapters consume `ConsultorService.get_pending_resources(...)` output.

## Proposed Responsibilities
- Consultor:
  - SQL retrieval
  - canonical normalization
  - optional compatibility alias generation
- Adapter:
  - site filtering and site business rules
  - payload shaping from canonical fields
- Payload validator/worker:
  - no direct SQL hydration (eventual state)
  - validate and route payloads only

## Proposed Call Flow
```text
BrainClaimService
  -> ConsultorService.get_pending_resources(site_id, config, limit, compat_mode=True)
     -> SQL profile resolution
     -> execute query
     -> normalize to canonical
     -> attach raw + compat aliases
  -> Adapter.fetch_candidates(canonical_items)
  -> Adapter.build_payloads(...)
  -> Stream publish
```

## Normalized Return Model
- Preferred shape: typed nested object (`CanonicalResourceV1`) + `raw` payload snapshot.
- Return list of canonical records with optional `legacy_aliases` dict.

## Extension Strategy
- Universal core fields always present.
- Site-specific fields under `extensions.<site_id>`.
- Adapter contracts declare required extensions explicitly.

## Boundaries: consultor vs adapter vs payload
- Consultor must not:
  - classify protocol P1/P2/P3 by legal/business rules
  - generate form texts (`expone/solicita`)
  - apply site claim exclusions based on domain policy
- Adapter must not:
  - execute SQL directly (target state)
  - infer missing raw DB entities outside consultor contract

## Likely File Changes Required
- Add: `core/consultor/*`
- Update:
  - `services/brain_claim/app.py`
  - `sites/adapters/*.py`
  - `services/payload_validator/app.py` (remove direct SQL hydrate path in later phase)
  - `core/worker_execution/task_orchestrator.py` (remove direct SQL backfill in later phase)
- Keep unchanged initially:
  - `sites/*/controller.py`

## Assumptions
- Compatibility mode will coexist with existing adapters during migration.

## Findings
- Current `ResourceRepository` is close to consultor retrieval role but lacks canonical contract and clear boundaries.

## Risks
- Building one giant SQL in one step may introduce hidden join/performance regressions.
- Overloading consultor with payload logic would repeat current coupling problem.

## Recommendations
- Start with consultor facade over existing `ResourceRepository` templates, then progressively converge query profiles.
- Keep adapter API stable during first migration slices.

## Open Questions
- Should consultor expose paging/cursor semantics for high-volume sites?
- Do we need per-site runtime feature flags for consultor adoption?

## Exact Next Steps
1. Implement consultor facade + canonical model without changing adapter logic.
2. Add feature flag per site (`USE_CONSULTOR_<SITE>`).
3. Enable compatibility mode and capture parity logs.
