# Plan de Implementación para Control Centralizado desde Frontend

Este documento detalla los cambios necesarios para desacoplar el sistema de la terminal, permitiendo gestionar el `worker.py` y el `brain.py` directamente desde el dashboard, además de administrar listas negras y configuraciones.

## 1. Backend: Gestión de Procesos (`dashboard/process_manager.py`)

Se creará un nuevo módulo `dashboard/process_manager.py` que encapsulará la lógica para iniciar, detener y monitorizar los subprocesos de Python.

### Clase `ProcessManager`
- **Responsabilidad**: Gestionar el ciclo de vida de `worker.py` y `brain.py`.
- **Métodos**:
  - `start_process(name: str)`: Inicia el proceso (si no está ya corriendo). Usa `asyncio.create_subprocess_exec`.
  - `stop_process(name: str)`: Envía señal `SIGTERM` (o `SIGKILL` tras timeout) al proceso.
  - `get_status(name: str)`: Retorna "running", "stopped", "error".
  - `get_logs(name: str, lines: int = 100)`: Lee las últimas N líneas del archivo de log asociado (redirigiendo stdout/stderr a archivos en `logs/`).
  - `stream_logs(name: str)`: Generador asíncrono para WebSocket (opcional) o endpoint de streaming.

### Integración en `dashboard_api.py`
- Se instanciará un objeto global `process_manager = ProcessManager()`.
- Al inicio de la aplicación FastAPI (`@app.on_event("startup")`), se puede configurar para no iniciar nada automáticamente, o recuperar estado si se implementa persistencia de PIDs.

## 2. Backend: API Endpoints (`dashboard_api.py`)

Se añadirán los siguientes endpoints para exponer la funcionalidad al frontend.

### Control de Procesos
- `GET /api/control/status`: Devuelve el estado de `worker` y `brain`.
  - Respuesta: `{"worker": "running", "brain": "stopped"}`
- `POST /api/control/{process_name}/start`: Inicia el proceso.
- `POST /api/control/{process_name}/stop`: Detiene el proceso.

### Logs
- `GET /api/logs/{process_name}`: Devuelve las últimas 100 líneas de log en texto plano o JSON.

### Listas Negras (Blocked Resources)
- `GET /api/blacklist`: Devuelve la lista de recursos bloqueados.
- `DELETE /api/blacklist/{site_id}/{resource_id}`: Desbloquea un recurso.
- `POST /api/blacklist`: Bloquea manualmente un recurso (opcional).

### Configuración (Opcional pero recomendado)
- `GET /api/config`: Lee `organismo_config` de la DB.
- `PUT /api/config/{site_id}`: Actualiza la configuración de un organismo (ej. activar/desactivar).

## 3. Base de Datos (`core/sqlite_db.py`)

Se extenderá la clase `SQLiteDatabase` para soportar la gestión de recursos bloqueados, ya que actualmente solo permite insertar y verificar, pero no listar ni borrar.

### Nuevos Métodos
- `list_blocked_resources(self, site_id: Optional[str] = None) -> List[Dict]`:
  - Consulta `SELECT * FROM blocked_resources`.
- `unblock_resource(self, site_id: str, resource_id: int) -> bool`:
  - Ejecuta `DELETE FROM blocked_resources WHERE ...`.

## 4. Frontend: Dashboard (`dashboard-frontend/`)

Se modificará la interfaz para incluir un panel de control.

### Nueva Pestaña "Control Panel"
- **Estado del Sistema**: Indicadores visuales (Verde/Rojo) para Worker y Brain.
- **Acciones**: Botones "Iniciar" y "Detener" para cada proceso.
- **Visor de Logs**: Un área de texto (textarea readonly) o `div` con scroll que muestra los logs en tiempo real (polling cada 2-5s o WebSocket).

### Nueva Pestaña "Blacklist / Bloqueos"
- **Tabla de Bloqueos**: Muestra `site_id`, `resource_id`, `reason`, `created_at`.
- **Acciones**: Botón "Desbloquear" en cada fila.

### Modificaciones en `app.js`
- Funciones para llamar a los nuevos endpoints de API.
- Lógica de polling para actualizar el estado de los procesos y los logs.
