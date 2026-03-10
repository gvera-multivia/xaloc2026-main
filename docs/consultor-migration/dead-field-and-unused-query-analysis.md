# dead-field-and-unused-query-analysis.md

## Purpose
Identify queried fields that appear unused or weakly justified in current adapter/payload paths.

## Scope
Static analysis of query columns vs adapter and controller usage.

## Relevant Files
- `core/repositories/resource_repository.py`
- `sites/adapters/*.py`
- `sites/*/controller.py`

## Observed Current Behavior
- Queries often return richer row shapes than each adapter/controller consumes.
- Some fields are likely retained for historical fallback logic.

## Candidate Dead or Weak-Use Fields
- `madrid.exp_idpublic`:
  - fetched in query, no clear usage in adapter payload output path.
- `madrid/others` extra contact fields:
  - present but sometimes replaced with fixed constants.
- `base_online` some optional contact aliases:
  - selected but not always used in strict protocol branches.

## Suspicious Redundant Transformations
- repeated normalization of document identifiers in multiple adapters.
- repeated plate fallback inference in adapters instead of one normalized source stage.
- repeated motivos text resolution patterns.

## Assumptions
- "Dead" means static non-usage in audited path, not guaranteed runtime dead across all scripts.

## Findings
- True deadness cannot be proven for all fields due external scripts and historical workflows.
- Some fields are not dead but low-confidence dependencies and should be tagged for verification.

## Risks
- Removing suspicious fields too early can break low-frequency edge paths.

## Recommendations
- Introduce field usage telemetry during migration:
  - mark each canonical field as read by adapter/controller.
- Decommission only after observing sustained zero usage.

## Open Questions
- Which standalone scripts (`main_*_payload_by_id.py`) must be considered production-relevant?

## Exact Next Steps
1. Add runtime counters for field access in consultor compatibility mode.
2. Review 2-4 weeks of telemetry before removing any low-use fields.
