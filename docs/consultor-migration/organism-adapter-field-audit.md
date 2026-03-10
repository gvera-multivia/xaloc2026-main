# organism-adapter-field-audit.md

## Purpose
Audit each organism adapter to identify exactly which fields are fetched, consumed, transformed, and emitted downstream.

## Scope
Adapters under `sites/adapters/` used by `services/brain_claim/app.py`:
- `madrid`
- `base_online`
- `xaloc_girona`
- `ayunta_palma`
- `redsara`
- `terrassa`

## Relevant Files
- `sites/adapters/madrid.py`
- `sites/adapters/base.py`
- `sites/adapters/xaloc_girona.py`
- `sites/adapters/ayunta_palma.py`
- `sites/adapters/redsara.py`
- `sites/adapters/terrassa.py`
- `core/repositories/resource_repository.py`

## Assumptions
- "Fetched" means fields present in SQL templates for that site.
- "Consumed" includes fetch filtering and payload building.
- "Dead/suspicious" means fetched but not materially used in adapter logic (static evidence).

## Findings by Adapter

### madrid
- Query source: `ResourceRepository.SQL_BY_SITE['madrid']` (fallback local SQL exists in adapter).
- Fetched fields include core + extended address/contact + notes/publicacion (`rs.notas`, `pub_publicacion`, `rs_matricula`, `exp_idpublic`, `adjunto_*`).
- Consumed in fetch/filter:
  - `Expedient`, `Estado`, `UsuarioAsignado`, `FaseProcedimiento`.
- Consumed in payload build:
  - identity: `cliente_tipo`, `cliente_nif`, `cliente_nif_empresa`, `cif`, `cliente_nombre`, `cliente_apellido1`, `cliente_apellido2`, `cliente_razon_social`
  - address/contact: `cliente_domicilio`, `cliente_numero`, `cliente_planta`, `cliente_puerta`, `cliente_escalera`, `cliente_municipio`, `cliente_provincia`, `cliente_cp`, `cliente_email`
  - expediente/vehicle: `Expedient`, `rs_matricula`, `matricula`, `pub_publicacion`, `notas`
  - documents: `adjuntos`
- Transformations:
  - phase blacklist filter (reclamacion/embargo/apremio)
  - document normalization/type detection
  - expediente decomposition (`exp_*`)
  - address heuristic fallback
  - plate extraction from multiple sources
- Required vs optional (observed):
  - required for final payload validation: `exp_tipo`, `naturaleza`, `expone`, `solicita`, key notif/rep fields
  - optional: `notif_surname2`, several contact extras
- Dead/suspicious:
  - `exp_idpublic` fetched but not consumed in adapter payload logic.

### base_online
- Query source: `ResourceRepository.SQL_BY_SITE['base_online']` (fallback local SQL exists).
- Fetched fields include conductor fields (`conduc_*`), client details, `dia_denuncia`, `FAlta`.
- Consumed in fetch/filter:
  - `Expedient`, `Estado`, `UsuarioAsignado`.
- Consumed in payload build:
  - protocol inference from `FaseProcedimiento`
  - P1/P2/P3 payload derivation from `conduc_*`, client, expediente, vehicle/date fields.
- Transformations:
  - protocol classification (P1/P2/P3)
  - address inference, cp/province inference
  - site rule hard checks for P1 mandatory fields
  - motivos text generation by phase
- Required vs optional:
  - protocol-specific required sets; strict P1 validation present.
- Dead/suspicious:
  - `cliente_tel2` fetched but frequently replaced with fixed contact values in payload.

### xaloc_girona
- Query source: `ResourceRepository.SQL_BY_SITE['xaloc_girona']` (fallback local SQL + DB update correction branch remains in adapter).
- Fetched fields: core + juridica/fisica discriminators (`cif`, `nifempresa`, `Empresa`, `Nombrefiscal`, `cliente_tipo`) + attachments.
- Consumed in fetch/filter:
  - `FUsuarioCompletado`, `Estado`, `UsuarioAsignado`, expediente format + corrective branch.
- Consumed in payload build:
  - mandatario object derived from company/person fields
  - motivos text by phase
  - expediente/plate aliases.
- Transformations:
  - format corrections (`NT/` and other fixes)
  - possible DB updates in fallback code path.
- Required vs optional:
  - mostly required: expediente, plate (with fallback to `.`), motivos, mandatario identity keys.
- Dead/suspicious:
  - `adjuntos` forwarded but not deeply validated in adapter.

### ayunta_palma
- Query source: `ResourceRepository.SQL_BY_SITE['ayunta_palma']` (fallback local SQL exists).
- Fetched fields: compact set (identity + contact + plate + attachments).
- Consumed in fetch/filter:
  - regex, `Estado`, `UsuarioAsignado`.
- Consumed in payload build:
  - person type resolution via `cliente_tipo` and nif/cif fields
  - expone/solicita text by phase
  - minimal target payload for Palma controller.
- Transformations:
  - doc normalization
  - fallback matricula `.`
- Required vs optional:
  - hard discard when physical person lacks `documento` or juridical person lacks `nif_empresa`.
- Dead/suspicious:
  - `cliente_tel1`/`cliente_movil` fetched but outgoing payload uses fixed contact defaults in many flows.

### redsara
- Query source: `ResourceRepository.SQL_BY_SITE['redsara']` only (no adapter local SQL template).
- Fetched fields: core + detailed identity/address/contact + attachments.
- Consumed in fetch/filter:
  - `Organisme`, `Expedient`, `Estado`, `UsuarioAsignado` via rule tables and regex per organism.
- Consumed in payload build:
  - destination organism code, subject/exposes/solicit
  - interested party identity/address fields
  - document type bundle.
- Transformations:
  - merged organismo query patterns
  - rule-based organism resolution + expediente validation
  - company/person selection with strict CIF handling.
- Required vs optional:
  - destination code + subject/exposes/solicit mandatory for controller target creation.
- Dead/suspicious:
  - `address_sigla` access appears in payload build but query provides client street fields; semantics need explicit normalization spec.

### terrassa
- Query source: `ResourceRepository.SQL_BY_SITE['terrassa']` only.
- Fetched fields: core + plate variants (`rs_matricula`, `exp_matricula`, `pub_matricula`, `pub_publicacion`) + minimal identity.
- Consumed in fetch/filter:
  - organismo inclusion (`AYUNTAMIENTO DE TERRASSA`), expediente DSL patterns, ownership.
- Consumed in payload build:
  - is_company/document_type/doc number, alegaciones/observaciones, documents list.
- Transformations:
  - custom expediente DSL matcher
  - plate resolution priority chain + regex fallback in publication text
  - document type value mapping.
- Required vs optional:
  - strict discard if cannot infer plate or document identity.
- Dead/suspicious:
  - `adjuntos` mostly pass-through; Terrassa heavily relies on additional document enrichment later.

## Cross-Adapter Overlap
Common consumed concepts:
- resource identity: `idRecurso`, `idExp`, `numclient`
- expediente and phase: `Expedient`, `FaseProcedimiento`
- claim state: `Estado`, `UsuarioAsignado`
- subject identity: `SujetoRecurso`, `cliente_*`, `cif`/`cliente_nif_empresa`
- vehicle: one or more plate sources

## Unjustified Divergence Candidates
- Query pattern parsing differs (`split(" ")` AND semantics vs `split("|")` OR semantics).
- Document identity precedence differs by adapter in ways not always tied to site requirements.
- Similar contact fields are handled with fixed constants in some adapters and DB values in others.

## Candidate Canonical Field Names
- `resource.id`, `resource.expedient`, `resource.phase`, `resource.state`, `resource.assigned_user`
- `client.type`, `client.doc.primary`, `client.doc.type`, `client.name.first`, `client.name.last1`, `client.name.last2`, `client.business_name`
- `address.street_type`, `address.street_name`, `address.number`, `address.zip`, `address.city`, `address.province`
- `vehicle.plate.value`, `vehicle.plate.source`
- `attachments.items[]`

## Risks
- Some adapter filters depend on nuanced text normalization (accent folding, partial token matches).
- Replacing current precedence rules without parity tests may change claimant routing.

## Recommendations
- Freeze per-adapter contract snapshots before migration.
- Keep site-specific business filters in adapters; move generic extraction/normalization to consultor.
- Introduce compatibility alias outputs while controllers are unchanged.

## Open Questions
- Which fields in each adapter are historic compatibility only and can be deprecated after parity?
- Should plate fallback behavior be standardized or remain site-specific?

## Exact Next Steps
1. Build field-level matrix (fetched vs consumed vs output) per site in a machine-checkable format.
2. Create canonical-field mapping from each current alias.
3. Define adapter-specific extension sets that remain outside universal core.
