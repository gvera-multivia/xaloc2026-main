# source-column-to-canonical-field-map.md

## Purpose
Provide a direct mapping from current SQL columns/aliases to canonical fields.

## Scope
Mappings from `ResourceRepository.SQL_BY_SITE` and known adapter fallback aliases.

## Relevant Files
- `core/repositories/resource_repository.py`
- `sites/adapters/*.py`

## Mapping Table
| Source Column/Alias | Canonical Field | Notes |
|---|---|---|
| `idRecurso` | `resource.id` | required |
| `idExp` | `resource.exp_id` | nullable in some edge rows |
| `Expedient` | `resource.expedient` | key reference |
| `Organisme` | `resource.organism` | used for site rules |
| `TExp` | `resource.texp` | protocol hint |
| `Estado` | `resource.state` | claim state |
| `UsuarioAsignado` | `resource.assigned_user` | ownership check |
| `FUsuarioCompletado` | `resource.completed_at` | availability filter |
| `FaseProcedimiento` | `resource.phase` | protocol/business derivations |
| `numclient` | `resource.numclient` | identity/doc retrieval key |
| `SujetoRecurso` | `resource.subject_name` | fallback identity |
| `cliente_tipo` | `client.type` | map 1/2 to physical/juridical |
| `cliente_nif` | `client.document.alt_nif` | |
| `cliente_nif_empresa` | `client.document.alt_cif` | |
| `cif` | `client.document.alt_cif` | often primary for juridical |
| `cliente_nombre` | `client.name.first` | |
| `cliente_apellido1` | `client.name.last1` | |
| `cliente_apellido2` | `client.name.last2` | optional |
| `cliente_razon_social`/`Nombrefiscal`/`Empresa` | `client.business_name` | unify alias set |
| `cliente_domicilio` | `client.address.street_name` | raw street text |
| `cliente_numero` | `client.address.number` | |
| `cliente_escalera` | `client.address.stair` | optional |
| `cliente_planta` | `client.address.floor` | optional |
| `cliente_puerta` | `client.address.door` | optional |
| `cliente_cp` | `client.address.zip` | |
| `cliente_municipio` | `client.address.city` | |
| `cliente_provincia` | `client.address.province` | |
| `cliente_email` | `client.contact.email` | |
| `cliente_tel1` | `client.contact.phone1` | |
| `cliente_tel2` | `client.contact.phone2` | |
| `cliente_movil` | `client.contact.mobile` | |
| `matricula`/`rs_matricula`/`exp_matricula`/`pub_matricula` | `vehicle.plate.candidates[*]` | resolve priority later |
| `pub_publicacion` | `publication.text` | regex fallback source |
| `adjunto_id` + `adjunto_filename` | `attachments.items[]` | grouped by idRecurso |
| `conduc_*` | `extensions.base_online.conductor.*` | site extension |
| `dia_denuncia` | `extensions.base_online.incident_date` | site extension |

## Assumptions
- Canonical model keeps raw source snapshot under `meta.raw`.

## Findings
- Most inconsistencies are alias-level, not source-table-level.

## Risks
- Priority rules (doc/plate) are not encoded by raw aliases alone; must be explicit in normalizer.

## Recommendations
- Store precedence policy in code, not implied by field order.

## Open Questions
- Should canonical include both resolved value and candidate list for each inferred concept?

## Exact Next Steps
1. Implement mapping constants in `core/consultor/normalizer.py`.
2. Unit-test every mapping and precedence rule.
