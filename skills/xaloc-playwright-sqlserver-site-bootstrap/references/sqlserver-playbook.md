# SQL Server Playbook

## Objective

Define a repeatable pattern for extracting candidates from SQL Server and converting each candidate into worker payloads for a new site.

## 1) Adapter Contract

Implement in `sites/adapters/<site_id>.py`:

1. `fetch_candidates(...)`:
- Read pending resources from `resource_repo.get_pending_resources(...)` when available.
- Fallback to direct SQL query with `pyodbc` when needed.
- Apply regex and business-rule filtering.
- Call `on_discard({...})` for rejected resources with:
  - `site_id`
  - `idRecurso`
  - `tipo_incidencia`
  - `motivo`

2. `build_payloads(...)`:
- Convert SQL fields into worker payload keys expected by site controller.
- Fill required defaults (email/phone/static values) explicitly.
- Keep values normalized (`str.strip`, uppercase where needed).

## 2) Query Baseline

Use the adapters `base.py`, `madrid.py`, `ayunta_palma.py`, `redsara.py` as source patterns.

Common columns:
- `idRecurso`
- `idExp`
- `Expedient`
- `Estado`
- `UsuarioAsignado`
- `FaseProcedimiento`
- `cif`
- `SujetoRecurso`
- `numclient`
- client/contact/address fields
- attachment references

For cross-site compatibility, prioritize payload keys already used in existing controllers:
- `idRecurso`
- `expediente`
- `protocol` (if applicable)
- `archivos`
- domain-specific form fields (`expone`, `solicita`, etc.)

## 3) Resource Claim Safety

Claim flow is handled by `services/brain_claim/app.py`.

Adapter responsibilities:
- Ensure candidate remains valid before payload generation.
- Avoid returning malformed or incomplete payloads.
- Avoid side effects outside adapter scope.

## 4) organismo_config Requirements

Add entry in `organismo_config.json` with:
- `site_id`
- `query_organisme`
- `filtro_texp`
- `regex_expediente`
- `login_url`
- `recursos_url`
- `claim_limit_per_tick` (optional)
- `active`

Table schema lives in `infra/postgres/init/003_admin_schema.sql`.

## 5) SQL -> Payload Mapping Checklist

1. List SQL source columns.
2. List target payload keys.
3. Define normalization per field.
4. Define required/optional fields.
5. Define discard reason when required field missing.
6. Validate one sample payload per protocol/branch.

## 6) Common Failure Modes

1. Regex over-filters candidates.
2. Payload keys mismatch controller expectations.
3. Missing adapter registration in brain-claim.
4. Missing `organismo_config` entry (site never activated).
5. `archivos` paths unresolved at runtime.
