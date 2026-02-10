# Plan de Implementación: Better Queues, Logging y Reportes

Este plan detalla las mejoras en la gestión de colas, el sistema de reintentos con liberación de recursos, el log verboso por ejecución y la generación de informes finales de éxito e incidencias.

## 1. Gestión de Reintentos e Incidencias (Global)

### [MODIFY] [sqlite_db.py](file:///c:/Users/Guillem%20Vera/Desktop/Proyectos/xaloc2026-main/core/sqlite_db.py)
Añadiremos una tabla global de incidencias para consolidar errores del worker y descartes/gesdoc del orquestador.

- **Nueva tabla `incidencias`**:
  - `id` (AUTOINCREMENT)
  - `idRecurso` (INT, opcional)
  - `nExp` (TEXT)
  - `tipo_incidencia` (TEXT: `RETRY_EXHAUSTED`, `REQUIRES_GESDOC`, `REGEX_DISCARDED`)
  - `motivo` (TEXT)
  - `site_id` (TEXT)
  - `timestamp` (DATETIME DEFAULT CURRENT_TIMESTAMP)
- **Método `add_incident(id_recurso, n_exp, tipo, motivo, site_id)`**.

---

### [NEW] [xvia_deselect.py](file:///c:/Users/Guillem%20Vera/Desktop/Proyectos/xaloc2026-main/core/xvia_deselect.py)
Función para liberar recursos en Xvia cuando fallan todos los reintentos.

- **Función `deselect_resource(session, id_recurso)`**:
  - GET a `http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos` para CSRF.
  - POST a `.../servicio/recursos/telematicos/Asignado` con `{ recurso_id, id, _token, recursosSel: "0" }`.

---

## 2. Sistema de Logging Dual

### [NEW] [worker_logging.py](file:///c:/Users/Guillem%20Vera/Desktop/Proyectos/xaloc2026-main/core/worker_logging.py)
Configura una salida limpia para terminal y una verbosa para archivo por cada ejecución.

- **Función `setup_worker_logging(run_id: str)`**:
  - **Terminal**: Nivel `INFO`. Formato: `[WORKER] Procesando X de Y...`
  - **Archivo**: Nivel `DEBUG`. Ubicación: `logs/worker_run_{run_id}.log`. Incluye trazas completas y respuestas de red.

---

## 3. Reporte Final de Ejecución

### [NEW] [execution_report.py](file:///c:/Users/Guillem%20Vera/Desktop/Proyectos/xaloc2026-main/core/execution_report.py)
Módulo encargado de acumular estadísticas y generar los reportes finales.

- **Clase `ExecutionTracker`**:
  - Registra éxitos locales (idRecurso, expediente, ruta_justificante, tiempo, organismo).
  - Consulta la tabla `incidencias` para el informe de fallos.
  - **Informe A**: Incidencias (Listado de recursos deseleccionados y fallidos con motivo).
  - **Informe B**: Éxitos y Estadísticas (Detalle por trámite + Conteo total + Desglose por Organismo).

---

## 4. Cambios en Lógica Principal

### [MODIFY] [worker.py](file:///c:/Users/Guillem%20Vera/Desktop/Proyectos/xaloc2026-main/worker.py)
- **Reintentos**: Configurar `max_attempts = 3` (1 original + 2 reintentos).
- **Control**: Usar `nack(retryable=True)` para errores temporales. Si `attempt >= 3`, llamar a `deselect_resource` y `db.add_incident`.
- **Flujo**: Integrar `ExecutionTracker` para guardar el reporte al finalizar.

### [MODIFY] [brain.py](file:///c:/Users/Guillem%20Vera/Desktop/Proyectos/xaloc2026-main/brain.py)
- **Registro**: Al descartar un expediente por regex o marcar como "REQUIRES_GESDOC", llamar a `db.add_incident` para que aparezca en el reporte final.

---

## 5. Verificación
- **Pruebas Unitarias**: Crear `tests/test_execution_report.py` y `tests/test_xvia_deselect.py` con mocks de sesión/DB.
- **Prueba de Ejecución**: Validar que el terminal no se sature y que los informes en `logs/` sean correctos.
