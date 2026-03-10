# payload-construction-dataflow-analysis.md

## Purpose
Trace how query output fields become payload fields and how payloads are consumed downstream.

## Scope
- Adapter payload builders
- Candidate publication and validation services
- Worker-side mapping and controller target creation

## Relevant Files
- `services/brain_claim/app.py`
- `sites/adapters/*.py`
- `services/payload_validator/app.py`
- `core/worker_execution/task_orchestrator.py`
- `core/worker_execution/browser_executor.py`
- `sites/*/controller.py`

## Observed Current Behavior
- Payload creation starts in `adapter.build_payloads()` per site.
- Payloads are serialized as `raw_payload` and pushed to `candidates` stream.
- Validator may mutate/enrich payload using SQL (`_hydrate_payload_from_sql`) before drafting jobs.
- Worker may again mutate/enrich payload using SQL (`_backfill_identity_from_sqlserver`).
- Final payload interpretation happens in controller `map_data` and `create_target`.

## Payload Builder Inventory
- `sites/adapters/madrid.py::build_payloads`
- `sites/adapters/base.py::build_payloads`
- `sites/adapters/xaloc_girona.py::build_payloads`
- `sites/adapters/ayunta_palma.py::build_payloads`
- `sites/adapters/redsara.py::build_payloads`
- `sites/adapters/terrassa.py::build_payloads`

## Input Field Dependencies by Payload (high level)
- madrid payload depends on:
  - expediente decomposition + naturaleza + rep/notif structures + attachments.
- base payload depends on:
  - phase protocol classification + conductor/client/address + motivos + protocol-specific blocks.
- xaloc_girona payload depends on:
  - mandatario struct + motivos + expediente aliases.
- ayunta_palma payload depends on:
  - person type split and minimal contact/alegaciones fields.
- redsara payload depends on:
  - organism rule destination code + interested identity/address + subject/exposes/solicit.
- terrassa payload depends on:
  - document type value + plate inference + alegaciones/observaciones + document list.

## Current Transformation Stages
1. SQL alias layer (`ResourceRepository` query columns).
2. Adapter site rules (`fetch_candidates`).
3. Adapter payload derivations (`build_payloads`).
4. Validator rehydration fallback (optional SQL fetch by id).
5. Worker rehydration fallback (optional SQL fetch by id).
6. Controller alias mapping (`map_data`).
7. Controller strict target validation (`create_target`).

## Coupling and Risk Analysis
- Hidden coupling #1:
  - Validator/worker SQL fallback assumes DB schema and alias semantics directly, bypassing adapter normalization.
- Hidden coupling #2:
  - Controllers accept multiple aliases (`notif_name` vs `notif_nombre`, etc.), making field ownership ambiguous.
- Hidden coupling #3:
  - Some adapter payload fields are controller contract fields, not business-canonical fields.

## Recommended Separation of Concerns
Consultor layer:
- retrieval + normalization only
- no site form/payload semantics

Adapter layer:
- site candidate filtering
- site-specific business derivations from canonical fields

Payload builder layer:
- deterministic transformation from adapter domain object to controller contract
- no SQL access

Consumer/controller layer:
- strict site form validation and serialization
- no DB fallback or business rule inference

## Assumptions
- Rehydration fallbacks currently exist to tolerate incomplete payloads from stream boundaries.
- Removing fallbacks without parity-safe upstream completeness is unsafe.

## Findings
- At least two downstream consumers independently re-query SQL for missing identity fields.
- This indicates current adapter payload completeness is not treated as authoritative.
- Migration must include a payload completeness contract and verification gates.

## Risks
- If consultor migration ignores validator/worker fallback paths, regressions may appear only in production queue execution.
- Controller alias flexibility can hide drift until strict branches are hit.

## Recommendations
- Add payload schema validation right after adapter payload generation.
- Introduce `payload_version` and `canonical_source=true` markers for migration observability.
- Reduce SQL fallback to read-only diagnostics, then remove once parity is proven.

## Open Questions
- Which fields are intentionally optional at stream boundaries?
- Should validator be allowed to enrich payloads or only reject/route?

## Exact Next Steps
1. Define canonical payload completeness checklist per site.
2. Add parity comparator old-vs-new payload before publish to `candidates`.
3. Instrument validator/worker fallback usage counters to track migration readiness.
