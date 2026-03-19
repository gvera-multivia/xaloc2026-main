# Integracion Productiva Diputacio BCN

## Objetivo

Integrar `diputacio_bcn` end-to-end en el flujo productivo de `brain` + `worker` + Docker, usando el contrato comun del repositorio y manteniendo bloqueadas las fases no soportadas.

## Alcance funcional actual

- Fases soportadas:
  - `sancion`
  - `denuncia`
  - `propuesta de resolucion`
  - `subsanacion`
- Fases bloqueadas por ahora:
  - `apremio`
  - `embargo`
  - `identificacion`
- Organismos validos:
  - los devueltos por `org_identif_direct` para la URL de ORGT indicada por negocio
  - excluyendo `AJUNTAMENT DE MANRESA`
  - excluyendo `AJUNTAMENT DE RIPOLLET`

## SQL de negocio de referencia

```sql
SELECT *
FROM recursos.recursosExp
WHERE Organisme IN (
    SELECT organismo
    FROM org_identif_direct
    WHERE url = 'https://orgt.diba.cat/es/Home/selecciomunicipi?areaToReturn=TramitsPagaments&viewToReturn=idconductor&controllerToReturn=IdentificacioConductor&concepteTramit=NO&codiError=WEB00011&parametre=V&keyModel=modelIDCONDUCTOR'
)
AND Organisme NOT IN ('AJUNTAMENT DE MANRESA', 'AJUNTAMENT DE RIPOLLET')
AND (
    Estado = 0
    OR (Estado = 1 AND usuarioAsignado = 'Guillen Vera')
);
```

## Arquitectura objetivo

1. `brain_claim` selecciona candidatos de SQL Server para `diputacio_bcn`.
2. El adapter del site filtra organismos permitidos y descarta fases bloqueadas.
3. El adapter construye payload canonico con datos del representado, expediente, textos y adjuntos.
4. El `worker` descarga documento principal y adjuntos de XVIA.
5. El `worker` rescata documentacion del cliente desde el mount configurado.
6. El `worker` deriva `doc_acreditativa` y `doc_tramite` a partir del lote ya preparado.
7. Playwright ejecuta el flujo exacto actual del site.
8. Se descarga el justificante y se guarda en `RECURSOS TELEMATICOS/<fase>`.
9. Solo entonces se marca el recurso como completado en XVIA.

## Cambios por hacer

### 1. Brain / adapter

- Crear `sites/adapters/diputacio_bcn.py`.
- Registrar el adapter en `sites/adapters/__init__.py`.
- Registrar el site en `services/brain_claim/app.py`.
- Añadir entrada en `organismo_config.json`.
- Filtrar por organismos permitidos consultando `org_identif_direct`.
- Excluir fases `apremio`, `embargo`, `identificacion`.

### 2. Worker

- Mantener SQL Server por `.env` usando `build_sqlserver_connection_string()`.
- Reusar `download_document_and_attachments()` para XVIA.
- Reusar `get_required_client_documents()` para docs del cliente.
- Preparar `doc_acreditativa` y `doc_tramite` antes de `execute_browser_flow()` para `diputacio_bcn`.
- Mantener el justificante descargado en la carpeta del cliente.

### 3. Docker / runtime

- Validar mounts del perfil de navegador y carpeta de clientes.
- Validar uso de certificado en `valid.aoc.cat`.
- Confirmar que el contenedor dispone del mismo `.env` que worker/brain.

## Criterios de validacion

- Un recurso `sancion` valido entra en cola y llega al worker.
- Un recurso `apremio`, `embargo` o `identificacion` se descarta en brain.
- `doc_acreditativa` y `doc_tramite` quedan poblados antes del flujo Playwright.
- El flujo llega a `presentmulPas2`, firma, presenta y descarga recibo.
- El justificante queda guardado en la ruta del cliente.
- El recurso queda marcado como completado en XVIA.

## Estado actual

- Flujo Playwright del site avanzado hasta firma/presentacion/recibo.
- Pendiente cerrar integracion productiva real en adapter + worker + Docker.
