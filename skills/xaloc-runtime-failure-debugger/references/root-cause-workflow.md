# Root Cause Workflow

## Secuencia obligatoria

1. Fijar un caso concreto.
- no depurar "el sistema" en abstracto

2. Recoger evidencia.
- detalle PG
- estado de job
- ultimos logs por servicio relevante

3. Elegir la primera rotura real.
- no la ultima excepcion visible

4. Bajar al codigo.
- localizar la rama exacta
- revisar guardas, flags y contratos de payload

5. Cerrar con conclusion accionable.
- causa raiz
- fix
- test o reproduccion de validacion

## Malas practicas

- reintentar sin evidencia
- culpar al site sin mirar payload
- culpar a runner cuando el problema nacio en adapter o validator
- ignorar divergencias entre `organismo_config.json` y PG activa
