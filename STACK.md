# Stack Tecnológico

Este archivo describe las tecnologías y librerías clave que se utilizarán para la implementación del dashboard centralizado y la gestión de procesos.

## 1. Backend (Control y Orquestación)

### 1.1 `asyncio.subprocess` (Python)
- **Propósito**: Ejecución y gestión de procesos externos (`worker.py` y `brain.py`) sin bloquear el hilo principal de la API.
- **Justificación**: Proporciona control nativo sobre los procesos, incluyendo señales (Start, Stop, Kill) y redirección de logs (stdout/stderr).

### 1.2 `FastAPI` (Python)
- **Propósito**: Framework principal para la API del Dashboard.
- **Justificación**:
  - Asíncrono (compatible con `asyncio` y `playwright`).
  - Documentación automática (OpenAPI/Swagger) para probar los endpoints.
  - Alto rendimiento con Uvicorn.

### 1.3 `SQLite3` (Python Standard Library)
- **Propósito**: Gestión de listas negras (`blocked_resources`), configuración (`organismo_config`) y colas.
- **Justificación**: Ligero, sin dependencias externas, integrado nativamente en Python.

### 1.4 `logging` (Python Standard Library)
- **Propósito**: Redirección de la salida estándar de los procesos a archivos en `logs/` para consumo asíncrono.

## 2. Frontend (Dashboard)

### 2.1 Vanilla JS / HTML / CSS
- **Propósito**: Interfaz de usuario ligera y sin pasos de compilación complejos.
- **Justificación**: El dashboard actual es simple; mantenerlo "vanilla" facilita el despliegue y la modificación rápida sin necesidad de `npm build`.
- **Librerías Opcionales (CDN)**:
  - *TailwindCSS* (para estilos rápidos y modernos sin escribir CSS desde cero).
  - *Toastify.js* (para notificaciones de éxito/error al iniciar procesos).

## 3. Despliegue

### 3.1 `uvicorn`
- **Propósito**: Servidor ASGI para correr FastAPI.
- **Comando**: `uvicorn dashboard_api:app --reload` (desarrollo) o con workers (producción).

### 3.2 Estructura de Archivos de Log
- `logs/worker_out.log`: Salida estándar del worker.
- `logs/brain_out.log`: Salida estándar del brain.
- `logs/worker_err.log`: Errores del worker.
- `logs/brain_err.log`: Errores del brain.
