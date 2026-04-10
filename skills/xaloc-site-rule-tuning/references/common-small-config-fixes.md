# Common Small Config Fixes

## Casos tipicos

### 1. `login_url` o `recursos_url` desactualizada

- revisar `organismo_config.json`
- revisar si la URL tambien forma parte de flujos o docs operativos
- si el stack usa PG activa, alinear la entrada runtime

### 2. Site desactivado accidentalmente

- revisar `active`
- revisar si el adapter aparece como configurado en PG
- confirmar que el problema no era realmente de health o credenciales

### 3. `claim_limit_per_tick` demasiado bajo o demasiado alto

- tocar solo si el site lo necesita de verdad
- justificar el cambio con comportamiento observado en brain

### 4. Filtro de organismo mal escapado o incompleto

- revisar `query_organisme`
- en multi-organismo, evitar meter toda la logica en un solo regex de expediente

### 5. Regex valida pero fase/campos bloquean el candidate

- mover el cambio al adapter
- no relajar `regex_expediente` si no es el problema real
