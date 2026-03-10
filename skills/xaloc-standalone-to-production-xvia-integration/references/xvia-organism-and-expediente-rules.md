# XVIA Organism And Expediente Rules

## Objetivo

Definir como se decide que un recurso es procesable para un organismo en XVIA y como se valida el expediente antes de publicarlo al worker.

## Fuentes de verdad

1. `organismo_config.json`
- `query_organisme`: patrones `LIKE` para `rs.Organisme`.
- `filtro_texp`: tipos de expediente permitidos.
- `regex_expediente`: validacion base configurable.

2. `core/repositories/resource_repository.py`
- construye query SQL por `site_id`.
- aplica `query_organisme` y `filtro_texp`.
- carga campos de `Recursos.RecursosExp` usados por adapters.

3. `sites/adapters/<site_id>.py`
- reglas finales de negocio (organismo sancionador y formato expediente).
- si descarta, debe usar `on_discard(...)` con motivo y tipo de incidencia.

## Regla recomendada por adapter

1. Normalizar `Organisme` (case/acentos/espacios) para matching estable.
2. Resolver regla del organismo sancionador con tabla explicita:
- `like_patterns`
- `destination_code` (si aplica)
- `regex_list` de expediente validos
3. Validar expediente contra la regla resuelta.
4. Si falla:
- no publicar payload
- registrar descarte trazable via `on_discard`

## Campos minimos en candidate/payload

1. `idRecurso`
2. `Expedient`
3. `Organisme`
4. `SujetoRecurso`
5. `FaseProcedimiento`
6. campos de identidad cliente necesarios para el formulario del site

## Checklist de calidad

1. No depender solo de `regex_expediente` global cuando hay multi-organismo.
2. Mantener lista versionada de patrones por organismo en el adapter.
3. Probar al menos:
- un expediente valido por organismo
- un expediente invalido por organismo
4. Registrar motivo de descarte legible para incidencias operativas.
