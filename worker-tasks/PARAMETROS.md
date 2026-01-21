# Guía de parámetros (payload JSON) por web

Estos JSON de `worker-tasks/` son el “alimento” del worker:

- `enqueue_task.py` guarda el `payload` tal cual en SQLite.
- `worker.py` llama a `controller.map_data(payload)` y con el resultado construye el `Target` vía `controller.create_target(...)`.

En consecuencia, los parámetros útiles son los que entiende cada `map_data()` (y, opcionalmente, algunos campos “avanzados” que se pasan 1:1 al `create_target()`).

## Reglas comunes

- `archivos`: lista de rutas (string) relativas al repo (ej: `pdfs-prueba/test1.pdf`).
- Valores: casi todo es `str`; algunos flags son `bool`.
- `protocol`: NO va dentro del JSON; se pasa como columna aparte al encolar (`--protocol P1|P2|P3`).

## BASE On-line (`site=base_online`)

El flujo depende de `protocol`:

- `P1`: Identificación del conductor (M250)
- `P2`: Alegaciones (M203)
- `P3`: Recurso de reposición (recursTelematic)

**Payload “genérico” (recomendado, estable)** (lo que usan los ejemplos y `map_data()`):

- `user_phone` (str)
- `user_email` (str)
- `plate_number` (str)
- `expediente_id_ens` (str)
- `expediente_any` (str)
- `expediente_num` (str)
- `num_butlleti` (str)
- `data_denuncia` (str, formato `dd/mm/YYYY`)
- `nif` (str)
- `llicencia_conduccio` (str)
- `name` (str)
- `address_street` (str)
- `address_number` (str)
- `address_zip` (str)
- `address_city` (str)
- `address_province` (str)
- `archivos` (list[str])

**Payload “avanzado” (opcional)**: permite sobreescribir directamente argumentos de `create_target()`:

- P1: `p1_telefon_mobil`, `p1_telefon_fix`, `p1_correu`, `p1_matricula`, `p1_expedient_id_ens`, `p1_expedient_any`, `p1_expedient_num`, `p1_num_butlleti`, `p1_data_denuncia`, `p1_identificacio`, `p1_llicencia_conduccio`, `p1_nom_complet`, `p1_adreca`, `p1_address_street`, `p1_address_number`, `p1_address_zip`, `p1_address_city`, `p1_address_province`, `p1_archivos`
- P2: `p2_nif`, `p2_rao_social`, `p2_archivos`
- P3: `p3_tipus_objecte`, `p3_dades_especifiques`, `p3_tipus_solicitud_value`, `p3_exposo`, `p3_solicito`, `p3_archivos`

Notas:

- Si informas un campo `p1_*`/`p2_*`/`p3_*`, tiene prioridad sobre el genérico equivalente.
- En `P3`, si no indicas los campos `p3_*`, el controlador usa defaults (y el ejemplo solo define `archivos`).

## Madrid Ayuntamiento (`site=madrid`)

**Payload “genérico” (recomendado, estable)**:

- `plate_number` (str)
- `user_phone` (str)
- `representative_email` (str)
- `representative_phone` (str)
- `representative_street` (str)
- `representative_number` (str)
- `representative_zip` (str)
- `representative_city` (str)
- `notif_name` (str)
- `notif_surname1` (str)
- `notif_surname2` (str)
- `expediente_tipo` (str: `opcion1` | `opcion2`)
- `expediente_nnn` (str)
- `expediente_eeeeeeeee` (str)
- `expediente_d` (str)
- `expediente_lll` (str, si `expediente_tipo=opcion2`)
- `expediente_aaaa` (str, si `expediente_tipo=opcion2`)
- `expediente_exp_num` (str, si `expediente_tipo=opcion2`)
- `naturaleza` (str: `A` | `R` | `I`)
- `expone` (str)
- `solicita` (str)
- `archivos` (list[str])

**Payload “avanzado” (opcional)** (argumentos directos de `create_target()`):

- `matricula`, `inter_telefono`, `inter_email_check`
- `rep_tipo_via`, `rep_nombre_via`, `rep_numero`, `rep_cp`, `rep_municipio`, `rep_email`, `rep_movil`
- `notif_nombre`, `notif_apellido1`, `notif_apellido2`, `notif_razon_social`
- `exp_tipo`, `exp_nnn`, `exp_eeeeeeeee`, `exp_d`, `exp_lll`, `exp_aaaa`, `exp_exp_num`
- `archivos` (o `archivos_adjuntos`)

## Xaloc Girona (`site=xaloc_girona`)

**Payload “genérico” (recomendado, estable)**:

- `user_email` (str)
- `denuncia_num` (str)
- `plate_number` (str)
- `expediente_num` (str)
- `motivos` (str)
- `archivos` (list[str])

**Payload “avanzado” (opcional)**:

- `email`, `num_denuncia`, `matricula`, `num_expediente`, `archivos_adjuntos`

