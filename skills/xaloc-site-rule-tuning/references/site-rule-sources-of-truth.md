# Site Rule Sources Of Truth

## Objetivo

Recordar donde vive realmente cada parte de la decision de procesabilidad para no tocar la capa equivocada.

## Capas principales

1. `organismo_config.json`
- seed del catalogo base por `site_id`
- contiene `query_organisme`, `filtro_texp`, `regex_expediente`, `login_url`, `recursos_url`, `claim_limit_per_tick`, `active`

2. PostgreSQL `organismo_config`
- runtime source of truth cuando el stack corre con PG activo
- acceso via `core/pg_admin_store.py`
- lectura/actualizacion indirecta ya expuesta en `dashboard/services.py`

3. `sites/adapters/<site_id>.py`
- reglas finales de negocio
- patrones oficiales por organismo
- fases permitidas o bloqueadas
- campos obligatorios
- descartes con `on_discard`

4. `services/brain_claim/processable_validator.py`
- validacion transversal antes de publicar candidate/job

## Regla de decision practica

- Si el descarte ya ocurre por `query_organisme`, `filtro_texp` o una URL/config global, mirar config.
- Si el candidate pasa la config base pero cae por formato real o negocio, mirar adapter.
- Si el candidate parece correcto pero cae antes de publicar, mirar `processable_validator`.

## Archivos de referencia del repo

- `docs/12-expedientes-validos.md`
- `organismo_config.json`
- `core/pg_admin_store.py`
- `dashboard/services.py`
- `sites/adapters/`
