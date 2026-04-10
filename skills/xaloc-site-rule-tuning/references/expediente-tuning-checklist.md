# Expediente Tuning Checklist

## Antes del cambio

- Reunir al menos varios ejemplos reales validos y no validos.
- Confirmar si el problema es:
  - regex demasiado estricta
  - regex demasiado amplia
  - organismo incorrecto
  - `filtro_texp` incorrecto
  - regla adicional del adapter

## Durante el cambio

- Mantener `regex_expediente` como barrera inicial, no como unica fuente de verdad.
- Para sedes multi-organismo, preferir reglas explicitas en adapter.
- Mantener motivos de descarte claros y operativos.

## Despues del cambio

- Revisar tests del adapter/site.
- Comprobar si hay que alinear PostgreSQL activa con `organismo_config.json`.
- Confirmar que la incidencia corregida no reaparece en historico.

## Comandos utiles

```powershell
python skills/xaloc-site-rule-tuning/scripts/inspect_site_rule_surface.py --site-id <site_id> --show-pg
rg -n "REGEX_DISCARDED|SITE_RULE_DISCARDED|NOT_PROCESSABLE|on_discard|regex_expediente" sites/adapters
Get-Content organismo_config.json
```
