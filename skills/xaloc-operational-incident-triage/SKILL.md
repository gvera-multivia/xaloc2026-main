---
name: xaloc-operational-incident-triage
description: Triage operativo de incidencias y jobs fallidos en Xaloc usando heuristicas por sede y por tipo de incidencia. Usar cuando haya que decidir rapidamente si un fallo apunta a pagina caida, direccion mal escrita, identificacion incorrecta, expediente pasado, popup, DNI caducado o dato faltante, y si conviene reintentar, bloquear o escalar a otra skill.
---

# Xaloc Operational Incident Triage

## Overview

Aplicar heuristicas operativas para clasificar rapidamente un job fallido o una incidencia y decidir la siguiente accion correcta. Esta skill no sustituye el debug profundo; sirve para decidir si un caso es reintentable, bloqueable, corregible en datos o derivable a otra skill.

## Workflow

1. Identificar `site_id` y tipo de fallo observado.
- job fallido en runtime
- incidencia de falta de documentacion
- incidencia de datos incorrectos
- recurso pillado por otro usuario

2. Consultar heuristica base.
- Ejecutar:
`python skills/xaloc-operational-incident-triage/scripts/site_failure_hints.py --site-id <site_id>`
- Si ya conoces el tipo de incidencia:
`python skills/xaloc-operational-incident-triage/scripts/site_failure_hints.py --site-id <site_id> --incident-type <tipo>`

3. Clasificar el caso.
- pagina caida o inestable
- direccion o municipio mal escritos
- identificacion incompleta o incorrecta
- expediente invalido pero potencialmente ajustable
- popup o comportamiento puntual de UI
- recurso cogido por otro usuario
- falta de documentacion

4. Elegir la accion operativa.
- reintentar si parece fallo de pagina o caida temporal
- bloquear si el dato es persistentemente incorrecto o el recurso esta tomado por otro usuario
- corregir documentacion en carpeta cliente si falta autorizacion
- derivar a `$xaloc-site-rule-tuning` si un expediente invalido debe considerarse valido
- derivar a `$xaloc-runtime-failure-debugger` si la heuristica no basta o hay contradiccion en evidencias

5. Ejecutar la accion.
- Para reencolar jobs que deben volver a correr:
  - ir a la lista de bloqueos
  - usar `reintentar` o `bloquear` segun el caso

## Required References

- Heuristicas por sede:
  - `references/site-failure-heuristics.md`
- Tipos de incidencia y accion recomendada:
  - `references/incident-types-and-actions.md`
- Uso operativo de bloqueos/incidencias:
  - `references/dashboard-requeue-playbook.md`

## Output Contract

Al cerrar una ejecucion con esta skill, devolver:

1. `site_id` y sintoma.
2. Tipo de incidencia o categoria probable.
3. Hipotesis operativa principal y secundarias.
4. Accion recomendada: reintentar, bloquear, corregir dato, corregir documentacion o escalar.
5. Si aplica, skill siguiente a usar.

## Non-goals

- No hacer debug de codigo profundo si la heuristica no alcanza.
- No relajar regex ni reglas de expediente desde aqui; para eso usar `$xaloc-site-rule-tuning`.
- No desbloquear o reintentar masivamente sin clasificar primero el motivo del fallo.
