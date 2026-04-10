---
name: xaloc-site-rule-tuning
description: Ajustar expedientes validos y pequenos cambios operativos por sede en Xaloc. Usar cuando haya que tocar `organismo_config`, regex de expediente, filtros de organismo, URLs, activacion de site o reglas pequenas en `sites/adapters/*` para corregir descartes o desajustes sin hacer el alta completa de un site nuevo.
---

# Xaloc Site Rule Tuning

## Overview

Aplicar cambios pequenos y controlados sobre reglas de procesabilidad por site. Priorizar evidencia real de casos validos/no validos y mantener alineados `organismo_config.json`, la config activa en PostgreSQL y las reglas finales del adapter.

## Workflow

1. Identificar el `site_id` y el sintoma exacto.
- descartes por expediente
- organismo no reconocido
- `login_url` / `recursos_url` desactualizadas
- `active` o `claim_limit_per_tick` mal fijados
- ajustes pequenos de fase/campos minimos en adapter

2. Inspeccionar la superficie de reglas antes de editar.
- Ejecutar:
`python skills/xaloc-site-rule-tuning/scripts/inspect_site_rule_surface.py --site-id <site_id>`
- Si hay PostgreSQL disponible y quieres comparar contra runtime:
`python skills/xaloc-site-rule-tuning/scripts/inspect_site_rule_surface.py --site-id <site_id> --show-pg`

3. Determinar la capa correcta del cambio.
- `organismo_config.json` cuando falla el filtro base o la config operativa del site.
- `sites/adapters/<site_id>.py` cuando la regla real depende de organismo, fase, campos minimos o patrones multi-formato.
- No expandir `regex_expediente` global si la validacion correcta pertenece al adapter.

4. Aplicar el ajuste minimo.
- Mantener `regex_expediente` como primera barrera.
- Mantener descartes trazables con motivo claro.
- Si el cambio es de direcciones o activacion, revisar tambien la copia activa en PostgreSQL si el entorno esta usando PG como source of truth.

5. Validar el ajuste.
- Revisar tests existentes del site.
- Verificar incidencias esperadas (`REGEX_DISCARDED`, `SITE_RULE_DISCARDED`, `NOT_PROCESSABLE`).
- Confirmar que no se abren falsos positivos downstream por payload incompleto.

## Required References

- Fuentes reales de reglas y config:
  - `references/site-rule-sources-of-truth.md`
- Checklist de tuning de expedientes:
  - `references/expediente-tuning-checklist.md`
- Cambios pequenos frecuentes:
  - `references/common-small-config-fixes.md`

## Output Contract

Al cerrar una ejecucion con esta skill, devolver:

1. `site_id` y sintoma observado.
2. Capa correcta del cambio (`organismo_config`, PostgreSQL activa, adapter, o varias).
3. Regla/config final propuesta.
4. Evidencia usada para justificar el cambio.
5. Validaciones ejecutadas y riesgos pendientes.

## Non-goals

- No dar de alta un site nuevo de punta a punta.
- No tocar worker, dashboard o runner salvo que el problema real ya no sea de reglas/config.
- No convertir un caso multi-organismo en una regex global simplista.
