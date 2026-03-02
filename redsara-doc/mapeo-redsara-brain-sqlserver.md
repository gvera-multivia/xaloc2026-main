# REDSARA: Mapeo SQL Server -> Orquestador Brain -> Campos Web

Este documento describe el mapeo **real implementado hoy** para REDSARA en:

- `sites/redsara/controller.py` (`map_data` + `create_target`)
- `sites/redsara/flows/formulario.py` (relleno de campos web)
- `sites/adapters/base.py` (origen típico de payload desde SQL Server en el orquestador)

## Regla general de flujo

1. SQL Server se consulta en el adapter del brain (normalmente `BaseOnlineAdapter`).
2. El adapter construye un `payload` normalizado (ej. `address_*`, `user_*`, `nif`, `name`, etc.).
3. `RedsaraController.map_data` traduce claves del payload a `RedsaraTarget`.
4. `formulario.py` rellena el formulario web con esos campos.

## Tabla de mapeo (trazabilidad completa)

| Campo web REDSARA | Campo interno REDSARA (`RedsaraTarget`) | Claves aceptadas en `map_data` | Origen típico SQL Server (brain) |
|---|---|---|---|
| Tipo vía representante (`dnt-select#represented.streetType`) | `represented_street_type` | `represented_street_type` / `rep_tipo_via` | No viene directo en `base.py`; normalmente se deriva de dirección (`address_sigla`) o se inyecta específico por adapter |
| Dirección representante (`formgroup=represented`, `streetName`) | `represented_address` | `represented_address` / `rep_direccion` / `representative_street` | `clientes.calle` -> `address_street` (si se remapea) |
| Provincia representante (`dnt-select#represented.province`) | `represented_province` | `represented_province` / `rep_provincia` / `representative_province` | `clientes.provincia` -> `address_province` (si se remapea) |
| Población representante (`dnt-select#represented.city`) | `represented_city` | `represented_city` / `rep_poblacion` / `representative_city` | `clientes.poblacion` -> `address_city` (si se remapea) |
| CP representante (`formgroup=represented`, `zipCode`) | `represented_zip` | `represented_zip` / `rep_cp` / `representative_zip` | `clientes.Cpostal` -> `address_zip` (si se remapea) |
| Teléfono representante (`formgroup=represented`, `phone`) | `represented_phone` | `represented_phone` / `rep_phone` / `representative_phone` / `user_phone` | `clientes.movil/telefono*` -> `user_phone` |
| Email representante (`formgroup=represented`, `email`) | `represented_email` | `represented_email` / `rep_email` / `representative_email` / `user_email` | `clientes.email` -> `user_email` |
| Tipo doc interesado (`dnt-select#tipoDoc`) | `interested_doc_type` | `interested_doc_type` / `tipo_doc_interesado` | Normalmente no directo; suele fijarse en adapter o defaults (`NIF`) |
| Nº doc interesado (`formgroup=interested`, `docNumber`) | `interested_doc_number` | `interested_doc_number` / `nif` / `interested_nif` | `clientes.nif` o `rs.cif` normalizado -> `nif` |
| Nombre interesado (`formgroup=interested`, `name`) | `interested_name` | `interested_name` / `name` | `rs.SujetoRecurso` -> `name` (en `base.py`) |
| 1er apellido interesado (`formgroup=interested`, `surname`) | `interested_surname1` | `interested_surname1` / `surname1` | **No mapeado automáticamente desde `cliente_apellido1` en REDSARA actual** |
| 2º apellido interesado (`formgroup=interested`, `lastName`) | `interested_surname2` | `interested_surname2` / `surname2` | **No mapeado automáticamente desde `cliente_apellido2` en REDSARA actual** |
| Tipo vía interesado (`dnt-select#streetType`) | `interested_street_type` | `interested_street_type` / `address_sigla` | `classify_address_fallback(...).tipo_via` -> `address_sigla` |
| Dirección interesado (`formgroup=interested`, `streetName`) | `interested_address` | `interested_address` / `address_street` | `clientes.calle` (o conductor adr) -> `address_street` |
| Provincia interesado (`dnt-select#interested.province`) | `interested_province` | `interested_province` / `address_province` | `clientes.provincia` (o inferida por CP) -> `address_province` |
| Población interesado (`dnt-select#interested.city`) | `interested_city` | `interested_city` / `address_city` | `clientes.poblacion` -> `address_city` |
| CP interesado (`formgroup=interested`, `zipCode`) | `interested_zip` | `interested_zip` / `address_zip` | `clientes.Cpostal` -> `address_zip` |
| Teléfono interesado (`formgroup=interested`, `phone`) | `interested_phone` | `interested_phone` / `user_phone` | `clientes.movil/telefono*` -> `user_phone` |
| Email interesado (`formgroup=interested`, `email`) | `interested_email` | `interested_email` / `user_email` | `clientes.email` -> `user_email` |
| Checkbox avisos email (`formcontrolname=emailAlert`) | `email_alert` | `email_alert` | No SQL directo; bandera de payload |
| Organismo destino (`dnt-select#destinationOrganism`) | `destination_organism_code` | `destination_organism_code` / `organism_code` | En pruebas: JSON `ORGANISMOS_REDSARA.json`; en producción debe venir del orquestador |
| Asunto (Paso 2) | `subject` | `subject` / `asunto` | Texto de negocio (no SQL estructural fijo) |
| Expone (Paso 2) | `exposes` | `exposes` / `expone` | Texto de negocio (no SQL estructural fijo) |
| Solicita (Paso 2) | `solicit` | `solicit` / `solicita` | Texto de negocio (no SQL estructural fijo) |

## Observaciones importantes (estado actual)

- REDSARA **sí consume bien** `address_*`, `user_*`, `nif`, `name` si llegan ya normalizados por el brain.
- Para apellidos del interesado, REDSARA espera `surname1/surname2` o `interested_surname1/interested_surname2`.
  - El adapter base produce `cliente_apellido1/cliente_apellido2`, pero `map_data` de REDSARA no los usa todavía.
- Para bloque representante, si el orquestador no envía claves `rep_*` o `representative_*`, se usan defaults de `create_target`.

## Recomendación de alineación con SQL Server (si se quiere cerrar gaps)

- Añadir en `RedsaraController.map_data`:
  - `interested_surname1 <- cliente_apellido1`
  - `interested_surname2 <- cliente_apellido2`
- Opcional:
  - `represented_* <- address_*` como fallback explícito cuando no existan `rep_*`.

