# Revision flujo P1 (Identificaciones BASE) para integrar con `brain.py` + `sites/adapters/base.py`

## Resumen ejecutivo
- Hoy **P1 no entra en cola** desde `brain` porque el adapter de BASE lo descarta explicitamente.
- Aunque quitemos ese `skip`, el P1 real de `base_online` tiene requisitos que el payload actual no cubre.
- Para llegar al mismo punto que el dummy (pantalla **"Signar i Presentar"**, sin firmar), faltan datos/reglas concretas.

## Donde se bloquea ahora
- `sites/adapters/base.py:242`-`sites/adapters/base.py:245`:
  - `if protocolo == "P1": ... continue` (se salta P1).

## Que exige el P1 real (no dummy)
- `sites/base_online/controller.py:88`-`sites/base_online/controller.py:128` obliga en P1:
  - `p1_data_denuncia`
  - `p1_llicencia_conduccio`
  - `p1_identificacio` (documento conductor)
  - `p1_nom_complet`
  - expediente (`id_ens`, `any`, `num`, `num_butlleti`)
  - contacto (`telefono_mobil`, `correu`)
  - direccion estructurada completa o `p1_adreca`
  - al menos un archivo (`p1_archivos`)
- `sites/base_online/flows/p1.py:101`-`sites/base_online/flows/p1.py:132` ademas valida:
  - `sigla` de via en catalogo permitido (`CL`, `AV`, etc.)
  - CP, municipio/provincia/pais con reglas de Espana/extranjero.

## Que ya tienes cubierto en BASE adapter
- contacto base (`user_phone`, `user_email`)
- expediente parseado (`expediente_id_ens`, `expediente_any`, `expediente_num`, `num_butlleti`)
- direccion (`address_*`)
- identidad basica (`nif`, `name`, datos cliente)
- archivos del cliente (`archivos`) con fallback no estricto

## Lo que necesito y hoy no esta (imprescindible)
1. **Origen para `llicencia_conduccio` (campo obligatorio)**
- No se esta extrayendo de SQL ni de otra fuente.
- En el script legado ya aparece como pendiente: `claim_one_resource_base_online.py:485`-`claim_one_resource_base_online.py:487`.

2. **Regla para `data_denuncia` cuando falte/sea invalida**
- El adapter actual no la carga para P1.
- Se puede derivar de `FAlta`, pero hay que definir fallback si viene vacio.

3. **Mapeo de `address_sigla` al catalogo permitido de P1**
- Hoy se rellena con `clasif["tipo_via"]` o `"CALLE"` (`sites/adapters/base.py:263`-`sites/adapters/base.py:266`).
- P1 no acepta valores libres; debe mapearse a codigos (`CL`, `AV`, ...).

4. **Regla de completado para direccion incompleta**
- `p1_address_number`, `zip`, `city`, `province`, `pais` son obligatorios en `create_target`.
- Necesitamos criterio cuando DB/IA no traiga numero o CP (ej. usar `S/N`, descartar recurso, o fallback fijo).

5. **Regla para identificacion del conductor en P1**
- Ahora `p1_identificacio` saldria de `nif` del cliente.
- Confirmar si en BASE P1 debe ir **siempre documento del conductor** (no CIF/NIF empresa).

6. **Criterio de expediente valido para P1**
- El adapter permite formato "tipo B", pero `parse_expediente_base` no extrae `id_ens/any/num` en ese caso.
- Si esos campos quedan vacios, el controller P1 falla.
- Necesitamos decidir: excluir esos expedientes para P1 o definir parser especifico.

7. **Politica GESDOC para pruebas de integracion**
- `brain` pausa en `pending_authorization_queue` si no encuentra AUT (`brain.py:649`-`brain.py:677`, `core/client_documentation.py:544`+).
- Para "llegar al mismo punto que dummy" en real, o existe AUT local, o se habilita flujo GESDOC, o se desactiva este gate en entorno de prueba.

## Diferencia clave con la version dummy
- El dummy (`worker-tasks/base_online_p1.json`) aporta valores sinteticos de campos criticos (`data_denuncia`, `llicencia_conduccio`, `address_sigla=CL`, etc.).
- En integracion real esos valores deben salir de SQL/reglas de negocio, no de hardcode de prueba.

## Propuesta minima para habilitar P1 hasta punto dummy
1. Quitar el `skip` de P1 en `sites/adapters/base.py`.
2. Anadir en payload P1:
- `data_denuncia` (desde `FAlta` formateada)
- `llicencia_conduccio` (segun regla que definas)
- normalizacion de `address_sigla` a catalogo valido.
3. Anadir prevalidacion P1 (similar a Madrid) para descartar antes de encolar payloads inviables.
4. Asegurar disponibilidad AUT (o bypass controlado) para no quedar en `pending_authorization_queue`.

## Resultado esperado tras cubrir lo anterior
- `brain` podra reclamar + encolar P1.
- `worker` podra construir `BaseOnlineTarget` P1 sin `ValueError`.
- El flujo llegara al mismo hito del dummy: pantalla de firma/presentacion (sin necesidad de firmar automaticamente).
