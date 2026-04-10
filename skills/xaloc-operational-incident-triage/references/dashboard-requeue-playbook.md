# Dashboard Requeue Playbook

## Idea base

Cuando un job debe volver a correr:

1. ir a la lista de bloqueos
2. decidir entre `reintentar` o `bloquear`

## Criterio rapido

- `reintentar`
  - caida de pagina
  - popup puntual
  - fallo temporal de sede

- `bloquear`
  - dato persistentemente incorrecto
  - recurso cogido por otro usuario
  - caso que requiere correccion manual previa

## Enlaces de contexto del repo

- `docs/10-blacklist-e-incidencias.md`
- `dashboard/services.py`
- `core/pg_admin_store.py`

## Advertencia

- Resolver una incidencia no implica que el recurso ya este listo para reintento.
- Si no se corrigio la causa raiz, desbloquear o reintentar solo reintroduce el fallo.
