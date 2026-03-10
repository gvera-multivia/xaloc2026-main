# sql-query-comparison-and-field-matrix.md

## Purpose
Compare all SQL retrieval shapes and aliases to identify common core fields, site-specific extensions, inconsistencies, and unified retrieval feasibility.

## Scope
- `core/repositories/resource_repository.py` (`SQL_BY_SITE` templates)
- Adapter-local fallback SQL constants in:
  - `sites/adapters/madrid.py`
  - `sites/adapters/base.py`
  - `sites/adapters/ayunta_palma.py`
  - `sites/adapters/xaloc_girona.py`

## Relevant Files
- `core/repositories/resource_repository.py`
- `sites/adapters/*.py`

## Observed Current Behavior
- Current primary runtime path already uses `ResourceRepository.SQL_BY_SITE`.
- Each `site_id` has a dedicated SELECT with overlapping columns but divergent aliases and joins.
- Some adapters keep fallback local SQL with equivalent but not guaranteed identical semantics.

## Field-by-Field Comparison Matrix
Legend: Y = selected by site query.

| Semantic Field | madrid | base_online | xaloc_girona | ayunta_palma | redsara | terrassa |
|---|---:|---:|---:|---:|---:|---:|
| idRecurso | Y | Y | Y | Y | Y | Y |
| idExp | Y | Y | Y | Y | Y | Y |
| Expedient | Y | Y | Y | Y | Y | Y |
| Organisme | Y | Y | Y | Y | Y | Y |
| TExp | Y | Y | Y | Y | Y | Y |
| Estado | Y | Y | Y | Y | Y | Y |
| numclient | Y | Y | Y | Y | Y | Y |
| SujetoRecurso | Y | Y | Y | Y | Y | Y |
| FaseProcedimiento | Y | Y | Y | Y | Y | Y |
| UsuarioAsignado | Y | Y | Y | Y | Y | Y |
| FUsuarioCompletado | - | - | Y | - | - | - |
| FAlta | - | Y | - | - | - | Y |
| dia_denuncia | - | Y | - | - | - | - |
| rs_matricula alias | Y | - | - | - | - | Y |
| expedientes.matricula | Y | Y | Y | Y | - | Y (as exp_matricula) |
| pubExp.matricula | - | - | - | - | - | Y |
| pub_publicacion | Y | - | - | - | - | Y |
| notas | Y | - | - | - | - | - |
| cif | Y | Y | Y | Y | Y | - |
| cliente_tipo | Y | - | - | Y | Y | Y |
| cliente_nif | Y | Y | Y | Y | Y | Y |
| cliente_nif_empresa | Y | - | - (`nifempresa`) | Y | Y | Y |
| cliente_nombre | Y | Y | Y | Y | Y | Y |
| cliente_apellido1 | Y | Y | Y | Y | Y | Y |
| cliente_apellido2 | Y | Y | Y | Y | Y | Y |
| cliente_razon_social | Y | Y | - (`Nombrefiscal`) | Y | Y | Y |
| cliente_provincia | Y | Y | - | - | Y | - |
| cliente_municipio | Y | Y | - | - | Y | - |
| cliente_domicilio | Y | Y | - | - | Y | - |
| cliente_numero | Y | Y | - | - | Y | - |
| cliente_escalera | Y | Y | - | - | - | - |
| cliente_planta | Y | Y | - | - | Y | - |
| cliente_puerta | Y | Y | - | - | Y | - |
| cliente_cp | Y | Y | - | - | Y | - |
| cliente_email | Y | Y | - | Y | Y | - |
| cliente_tel1 | Y | Y | - | Y | Y | - |
| cliente_tel2 | Y | Y | - | - | Y | - |
| cliente_movil | Y | Y | - | Y | Y | - |
| conduc_nom | - | Y | - | - | - | - |
| conduc_dni | - | Y | - | - | - | - |
| conduc_adr | - | Y | - | - | - | - |
| conduc_codpost | - | Y | - | - | - | - |
| conduc_pobl | - | Y | - | - | - | - |
| conduc_prov | - | Y | - | - | - | - |
| Empresa | - | - | Y | - | - | - |
| Nombrefiscal raw | - | - | Y | - | - | - |
| adjunto_id / adjunto_filename | Y | Y | Y | Y | Y | Y |

## Source-Column to Semantic Mapping Notes
- `rs.Matricula`, `e.matricula`, `pe.matricula`, `pe.publicacion` all map to semantic `vehicle.plate` candidates with priority decisions outside SQL.
- `cif`, `cliente_nif_empresa`, `cliente_nif` map to semantic `client.document` but precedence differs by adapter.
- `Empresa`, `Nombrefiscal`, `cliente_razon_social` map to semantic business name with inconsistent aliasing.

## Alias Inconsistency Analysis
- Same concept, different names:
  - business name: `cliente_razon_social` vs `Nombrefiscal` vs `Empresa`
  - plate source aliases vary widely (`rs_matricula`, `exp_matricula`, `pub_matricula`, direct `matricula`)
  - company doc: `cif` vs `cliente_nif_empresa`
- Query operator semantics differ by parser logic:
  - legacy AND split by spaces
  - OR split by `|`

## Common Core Field Set (recommended minimum)
- `idRecurso`, `idExp`, `Expedient`, `Organisme`, `TExp`, `Estado`, `numclient`, `SujetoRecurso`, `FaseProcedimiento`, `UsuarioAsignado`
- `cliente_nif`, `cliente_nombre`, `cliente_apellido1`, `cliente_apellido2`
- `adjunto_id`, `adjunto_filename`

## Organism-Specific Extension Set
- madrid: `notas`, `pub_publicacion`, full address/contact set
- base_online: `conduc_*`, `dia_denuncia`, `FAlta`
- xaloc_girona: `FUsuarioCompletado`, `Empresa`, `nifempresa`, `Nombrefiscal`
- ayunta_palma: compact juridical/person split fields
- redsara: full interested address/contact bundle
- terrassa: multi-source plate fields and publication text

## Unused/Suspicious Query Fields
- `exp_idpublic` in madrid appears unconsumed in adapter payload path.
- Some contact/address fields are selected but replaced by constants in payload generation for specific sites.

## Superset Query Feasibility
Feasible with caveats:
- Technically possible to build one superset SELECT with optional joins and normalized output.
- Risk of over-fetching acceptable compared to behavioral risk of under-fetching, if bounded by `TOP/limit` and indexed joins.
- Must keep per-site filters external to SQL projection logic to avoid semantic drift.

## Risks
- Over-fetching may increase row width and transport costs.
- Under-fetching can silently break site payloads and downstream forms.
- Joins to optional tables (`pubExp`, `DadesIdentif`, attachments) can alter cardinality if not grouped consistently.

## Recommendations
- Keep one consultor retrieval contract with:
  - universal core projection
  - extension sections loaded conditionally by site profile
- Normalize all aliases to canonical names immediately after retrieval.
- Preserve original raw fields under `raw.*` for parity and debugging during migration.

## Open Questions
- Should attachments remain joined in the same query or become a secondary retrieval step for performance?
- Which publication joins are truly required in production vs legacy fallback?

## Exact Next Steps
1. Implement machine-readable mapping file (source column -> canonical field -> site coverage).
2. Define consultor query profiles (`core`, `address`, `vehicle`, `conductor`, `publication`, `attachments`).
3. Validate cardinality/parity on sampled `idRecurso` per site.
