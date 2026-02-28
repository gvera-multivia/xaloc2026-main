# Plan de Acción: Migración a Arquitectura "Un Organismo por Docker"

Este documento detalla los pasos técnicos para implementar la ejecución simultánea de trámites segregados por sitio/organismo, utilizando contenedores dedicados y visualización vía noVNC.

## 1. Modificaciones en el Núcleo (Core)

### A. Filtrado de tareas por Sitio (`core/worker/consumer.py`)
Actualmente, los workers toman cualquier tarea disponible en la cola.
- **Acción:** Introducir una variable de entorno `WORKER_SITE_ID`.
- **Lógica:** Si `WORKER_SITE_ID` está definida, el worker pasará este valor al método `reserve()` del `QueueGateway`.
- **Impacto:** El gateway filtrará la consulta en Redis/PostgreSQL para devolver solo tareas donde `site_id == WORKER_SITE_ID`.

### B. Registro de URL de noVNC (`core/pg_runtime_store.py`)
Para que el Dashboard sepa dónde conectarse para ver la "cámara":
- **Acción:** Añadir la columna `novnc_url` (TEXT) a la tabla `worker_runtime`.
- **Acción:** Actualizar el método `upsert_worker_runtime` para aceptar y persistir este campo.

### C. Heartbeat con Metadatos (`core/worker/consumer.py`)
- **Acción:** El worker debe leer su URL de noVNC desde una variable de entorno (ej. `WORKER_NOVNC_EXTERNAL_URL`) y enviarla en cada latido de heartbeat.

---

## 2. Cambios en la API y Dashboard

### A. Endpoint de Visualización Dinámico (`dashboard_api.py`)
- **Acción:** Modificar `/api/queue/live-viewer` para que reciba un `worker_id`.
- **Lógica:** Buscar el worker en `worker_runtime` y devolver su `novnc_url` específica en lugar de la global del entorno.

### B. Frontend del Monitor (`dashboard-frontend/app/page.tsx`)
- **Acción:** Crear un componente `WorkerSelector` que liste los workers activos.
- **Acción:** Al seleccionar un worker, actualizar el `iframe` de noVNC con la URL correspondiente a ese worker.

---

## 3. Despliegue e Infraestructura (`docker-compose.yml`)

Para cada organismo que se desee procesar en paralelo, se debe definir un bloque de servicios:

```yaml
# Ejemplo para Organismo "Madrid"
worker-madrid:
  image: xaloc-worker
  environment:
    - WORKER_SITE_ID=madrid
    - WORKER_NOVNC_EXTERNAL_URL=http://tu-dominio.com:6081/vnc.html
  depends_on:
    - runner-madrid

runner-madrid:
  image: xaloc-playwright-runner
  ports:
    - "6081:6080" # Puerto externo para noVNC
```

---

## 4. Pasos para la Ejecución

1.  **Actualizar Base de Datos:** Ejecutar la migración SQL para añadir la columna `novnc_url` a `worker_runtime`.
2.  **Modificar `RedisStreamsQueueGateway`:** Actualizar el método `reserve` para aplicar el filtro de `site_id` en la lógica de lectura de streams.
3.  **Refactorizar `BaseAutomation`:** Eliminar cualquier referencia al antiguo sistema de screencast JPEG para limpiar el código.
4.  **Desplegar Piloto:** Probar con dos organismos distintos (ej: Madrid y Palma) en contenedores separados y verificar que ambos aparecen en el Dashboard.
