# Site Failure Heuristics

## Madrid

- Si falla un job, primero sospechar:
  - direccion del cliente mal escrita
  - pagina de Madrid caida

## Palma

- Si falla un job, probablemente la pagina esta caida

## Redsara

- Si falla un job, casi seguro que es por direccion
- casos tipicos:
  - direccion mal escrita
  - municipio no valido
  - excepcion de escritura por como Redsara nombra lugares

## Xaloc

- Si falla un job, suele ser por la pagina y no por la automatizacion
- por defecto es candidato a reintento

## Base

- Si falla un job, probablemente es la pagina
- segunda sospecha: mala identificacion

## Diputacion

- Puede fallar por:
  - identificacion
  - expediente pasado
  - pagina caida

## ATC

- Puede fallar por:
  - pagina
  - popups

## Terrassa

- Puede fallar por:
  - pagina
  - DNI caducado
  - DNI mal escrito

## Regla de uso

- Estas heuristicas sirven para triaje inicial.
- Si el caso contradice la heuristica, pasar a debug con evidencia real.
