# canonical-field-model-design.md

## Purpose
Define a canonical normalized field model for unified SQL consultation output, with stable semantics and compatibility rules.

## Scope
- Canonical retrieval object from consultor
- Universal required fields
- Optional/site extensions
- Nullability and derived-field rules

## Relevant Files
- `core/repositories/resource_repository.py`
- `core/domain/resource_domain.py`
- `sites/adapters/*.py`
- `sites/*/controller.py`
- `services/payload_validator/app.py`
- `core/worker_execution/task_orchestrator.py`

## Target Behavior
- Consultor returns one normalized structure per resource with stable names.
- Raw SQL aliases are retained under a separate namespace for compatibility/debug.
- Adapters consume only canonical fields plus declared extension sections.

## Canonical Field Catalog

### resource (required)
- `resource.id` (int)
- `resource.exp_id` (int|null)
- `resource.expedient` (string)
- `resource.organism` (string)
- `resource.texp` (int|null)
- `resource.state` (int)
- `resource.assigned_user` (string)
- `resource.completed_at` (datetime|null)
- `resource.phase` (string)
- `resource.numclient` (int|null)
- `resource.subject_name` (string)

### client.identity (required if known)
- `client.type` (`FISICA`|`JURIDICA`|`UNKNOWN`)
- `client.document.primary.value` (string)
- `client.document.primary.kind` (`NIF`|`NIE`|`CIF`|`PASAPORTE`|`UNKNOWN`)
- `client.document.alt_nif` (string|null)
- `client.document.alt_cif` (string|null)
- `client.name.first` (string|null)
- `client.name.last1` (string|null)
- `client.name.last2` (string|null)
- `client.business_name` (string|null)

### client.contact (optional)
- `client.contact.email`
- `client.contact.phone1`
- `client.contact.phone2`
- `client.contact.mobile`

### client.address (optional)
- `client.address.street_type` (normalized or null)
- `client.address.street_name`
- `client.address.number`
- `client.address.stair`
- `client.address.floor`
- `client.address.door`
- `client.address.zip`
- `client.address.city`
- `client.address.province`
- `client.address.country` (default `ESPANA` when needed downstream)

### vehicle (optional)
- `vehicle.plate.value`
- `vehicle.plate.source` (`rs_matricula`|`exp_matricula`|`pub_matricula`|`pub_publicacion_regex`|`none`)
- `vehicle.incident_date`

### conductor (site extension: base_online)
- `conductor.name`
- `conductor.document`
- `conductor.address`
- `conductor.zip`
- `conductor.city`
- `conductor.province`

### publication (optional)
- `publication.text`
- `publication.exp_idpublic`

### attachments
- `attachments.items[]` with `{id:int, filename:string}`

### metadata
- `meta.site_id`
- `meta.query_profile`
- `meta.retrieved_at`
- `meta.raw` (full raw row snapshot)

## Required vs Optional Rules
- Required globally: `resource.id`, `resource.expedient`, `resource.state`, `resource.phase`.
- Required for claiming/ownership checks: `resource.assigned_user`.
- Identity required for payload generation depends on site protocol; not all sites require full address.

## Nullability/Absence Semantics
- Missing source values become `null` (not empty string) in canonical model.
- Adapters may coerce `null -> ""` only for site form compatibility.
- Any fallback inference must set `meta.derived_fields[]` to preserve traceability.

## Derived Field Rules
- Derived values must include source provenance:
  - e.g. `vehicle.plate.value` with `vehicle.plate.source`.
- Document type inference result stored alongside raw value.
- Address normalization should not overwrite raw address.

## Naming Conventions
- Dot-path namespaces by domain (`resource.*`, `client.*`, `vehicle.*`).
- Use semantic names, not table aliases (`cliente_*`, `rs_*`).
- Booleans prefixed with `is_`.

## Compatibility Guidance
- During migration, emit both canonical and legacy aliases via a compatibility mapper.
- Legacy aliases must be generated from canonical values, not vice versa.
- Keep versioning:
  - `meta.schema_version = "v1"`
  - `meta.compat_aliases = true|false`

## Assumptions
- Canonical model is internal contract; controllers can remain unchanged initially.

## Findings
- Existing `ResourceDomain` only covers a subset and keeps raw `metadata`; it can evolve into canonical carrier.

## Risks
- Prematurely removing legacy aliases will break controller maps.
- Inference rules can change business behavior if not locked with parity tests.

## Recommendations
- Implement canonical model as typed dataclasses/TypedDicts in a new consultor package.
- Keep explicit mapping registry from source aliases to canonical fields.

## Open Questions
- Should canonical model include site-specific sub-objects (`extensions.<site>`) or generic extension bag?

## Exact Next Steps
1. Create `CanonicalResourceV1` type definitions.
2. Create alias-compat mapper per site.
3. Validate nullability and derived provenance with snapshot tests.
