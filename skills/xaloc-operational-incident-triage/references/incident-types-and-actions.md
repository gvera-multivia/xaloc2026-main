# Incident Types And Actions

## Falta de documentacion

- Caso tipico: falta autorizacion
- Accion:
  - poner la autorizacion en la carpeta del cliente
  - reintentar despues

## Datos incorrectos

- Casos tipicos:
  - matricula faltante
  - DNI faltante
  - expediente considerado invalido
- Accion:
  - corregir el dato si falta o esta mal
  - si el expediente parece realmente valido pero el sistema lo rechaza, usar `$xaloc-site-rule-tuning`

## Recurso pillado por otro usuario

- Accion:
  - tratarlo como bloqueo operativo
  - no insistir con reintentos ciegos

## Pagina caida o inestable

- Accion:
  - reintentar
  - si persiste, dejar trazabilidad y escalar

## Identificacion incorrecta

- Accion:
  - revisar datos del cliente
  - revisar DNI, direccion o campos de identificacion que use la sede
