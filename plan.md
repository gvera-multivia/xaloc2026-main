# Plan: separar orígenes (SQL sync vs JSON) y evitar defaults/validación

## Problema (resumen)
- Hoy el worker procesa tareas (vengan por JSON, por SQL “a pelo”, o por `sync_*`) por el mismo “canal” genérico:
  - `worker.py` ejecuta siempre `ValidationEngine.validate(payload)` y puede bloquear por reglas genéricas.
  - Los controladores (`sites/*/controller.py`) usan `create_demo_data` como `create_target` y **rellenan valores por defecto** cuando faltan (teléfonos, emails, motivos, textos, PDFs de `pdfs-prueba/*`).
  - `sync_sqlserver_to_worker_queue.py` además **inyecta defaults** (`archivos`, `expone/solicita`, `motivos`, representante…).
- Resultado: si un payload llega incompleto/vacío (p.ej. insertado vía SQL o por sync sin JSON completo), el sistema:
  - se valida con reglas genéricas (independiente de web/proceso),
  - y/o se “autocompleta” con datos dummy que no deberían existir.

## Objetivo mínimo pedido
Para **todo lo que venga de** `sync_sqlserver_to_worker_queue.py` y `sync_sqlserver_preview_to_csv.py`:
- No pasar por validación (no usar `ValidationEngine`).
- No inyectar datos “prehechos”/defaults en ningún punto (ni en sync, ni al construir targets).

## Diseño propuesto (control por “origen”)
Usar un metadato en el payload para que el worker sepa cómo tratar cada tarea, sin depender de cómo se insertó.

- Nuevo campo en payload: `"_meta": {"source": "...", "skip_validation": true, "no_defaults": true}`
  - `source`: `"sqlserver_sync"` (para ambos `sync_*`).
  - `skip_validation`: el worker omite `ValidationEngine`.
  - `no_defaults`: el worker y los controladores NO rellenan nada si falta.

Nota: esto permite también inserts “a través de SQL” (directos a `tramite_queue`) si incluyen el `"_meta"` en el JSON.

## Cambios concretos por archivo

### 1) `sync_sqlserver_to_worker_queue.py`
Cambios:
- Dejar de usar `PayloadDefaults` para el flujo “sync real”.
  - `map_to_worker_payload(...)` hoy mete:
    - `payload["archivos"] = defaults.archivos`
    - `madrid: naturaleza/expone/solicita (+ representative_email/phone)`
    - `xaloc_girona: motivos`
  - Eso debe eliminarse para el caso `source=sqlserver_sync`.
- Reutilizar `map_to_preview_payload(...)` (ya es “mínimo” y sin defaults) para encolar.
- Añadir `payload["_meta"] = {"source":"sqlserver_sync","skip_validation":True,"no_defaults":True}`
- (Opcional) mantener compatibilidad:
  - `--legacy-defaults` o `--with-defaults` para el comportamiento anterior (solo si lo necesitáis).

Resultado: lo que se encola en SQLite es “tal cual DB” (solo campos derivados), sin PDFs dummy, sin textos dummy.

### 2) `sync_sqlserver_preview_to_csv.py`
Cambios:
- Ya usa `map_to_preview_payload(...)` (bien).
- Añadir el mismo `"_meta"` al `payload` antes de `json.dumps(...)` para que el CSV sea consistente con lo que se encolará.

### 3) `worker.py`
Cambios:
- Leer `meta = payload.get("_meta", {})`.
- Si `meta.get("skip_validation") is True`: saltar el bloque “1. VALIDACIÓN EXHAUSTIVA”.
- Si `meta.get("no_defaults") is True`: construir el target en modo “estricto” (sin defaults).
- Arreglar el punto crítico de “datos prehechos” en adjuntos:
  - El worker descarga PDF/adjuntos (`archivos_para_subir`) pero hoy los pasa como `archivos_adjuntos` genérico, que **Madrid/BaseOnline no consumen** (por firma de `create_target`).
  - En modo estricto, el worker debe pasar los archivos descargados al parámetro correcto por site/protocol:
    - `madrid`: pasar `archivos=archivos_para_subir`
    - `xaloc_girona`: pasar `archivos_adjuntos=archivos_para_subir`
    - `base_online`: según `protocol` (`P1/P2/P3`) pasar `p1_archivos` / `p2_archivos` / `p3_archivos`
  - Así desaparece la necesidad de `pdfs-prueba/*` como fallback y el flujo usa los documentos reales del `idRecurso`.

### 4) Controladores: `sites/*/controller.py`
Cambios:
- Mantener `create_demo_data(...)` para tests/manual.
- Introducir un constructor estricto (ejemplos de naming):
  - `create_target_strict(...)` o `create_target(..., allow_defaults: bool = True)`
- En modo estricto:
  - No usar `or "valor_dummy"` para email/teléfono/matrícula/motivos/textos.
  - No asignar PDFs por defecto (`pdfs-prueba/test*.pdf`) si no se pasan.
  - Preferir strings vacíos/`None` tal cual y dejar que el flujo falle si el formulario lo exige (pero sin inventar datos).

Archivos afectados:
- `sites/madrid/controller.py` (hoy `create_target = create_demo_data` y tiene defaults masivos).
- `sites/xaloc_girona/controller.py` (defaults en `create_target` para email/denuncia/matricula/expediente/motivos/archivos).
- `sites/base_online/controller.py` (defaults para prácticamente todo y para archivos por protocolo).

### 5) SQLite / “vía SQL”
Sin cambios obligatorios de esquema si usamos `payload["_meta"]`.
- Si queréis filtrado/monitorización por origen, entonces sí:
  - añadir columna `source` en `db/schema.sql` y actualizar `core/sqlite_db.py`/`enqueue_task.py`/`sync_*` para poblarla.

### 6) `main.py` (retirar modo antiguo)
Cambios propuestos:
- Marcar `main.py` como **deprecado** (o eliminarlo) porque el modo worker ya cubre ejecución real.
- Sustituir por:
  - `worker.py` (ejecución),
  - `enqueue_task.py` (encolar manual),
  - `sync_sqlserver_to_worker_queue.py` (alimentar cola desde SQL Server).
- Actualizar `README.md`/`WORKER.md` si hace falta para que no se use el menú interactivo.

## Pasos de implementación (orden)
1) Cambiar `sync_sqlserver_to_worker_queue.py` para encolar “raw + _meta”.
2) Añadir `"_meta"` también en `sync_sqlserver_preview_to_csv.py`.
3) En `worker.py`, aplicar `skip_validation` y pasar archivos descargados con nombres correctos por site/protocol.
4) Implementar modo estricto en `sites/*/controller.py` y usarlo cuando `no_defaults=true`.
5) (Opcional) Deprecar/eliminar `main.py` y ajustar docs.

## Validación mínima (manual)
- Encolar 1 tarea vía `sync_sqlserver_to_worker_queue.py` y comprobar en SQLite que:
  - el `payload` contiene `"_meta"`,
  - no existe `archivos` con `pdfs-prueba/*`,
  - no se inyectan `expone/solicita/motivos` si vienen vacíos.
- Ejecutar `python worker.py` y verificar que:
  - no se abre reporte de validación para esas tareas,
  - los PDFs subidos corresponden a `tmp/downloads/*` (documento real + adjuntos).

