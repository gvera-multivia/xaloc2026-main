# Propuesta de Arquitectura "Lego": Modularización y Robustez para Xaloc

Este documento describe una propuesta de refactorización para transformar el código actual en una arquitectura de piezas independientes ("Legos"), donde cada componente tiene una responsabilidad única, una interfaz clara y puede ser reemplazado o probado sin afectar al resto del sistema.

## Filosofía: "Everything is a Component"

El objetivo es pasar de "scripts que hacen cosas" a "servicios que colaboran".
Principios clave:
1.  **Desacoplamiento fuerte:** Ningún módulo debe importar lógica interna de otro. Comunicación vía interfaces o eventos.
2.  **Agnosticismo de Infraestructura:** El código de negocio no debe saber si corre en Windows/Linux, o si la DB es SQLite/SQLServer.
3.  **Configuración como Contrato:** Los settings se validan al inicio (Pydantic). Si falta algo, falla rápido.

---

## 1. El Núcleo (`core/kernel`)

Crear un "Kernel" mínimo que provea los servicios base.

*   **`ConfigManager` (Singleton/Dependency Injection):**
    *   Centraliza `.env`, base de datos de configuración y argumentos CLI.
    *   Usa **Pydantic** para validar tipos (nada de `os.getenv` disperso por el código).
    *   *Ejemplo:* `config.database.connection_string`, `config.sites.madrid.timeout`.
*   **`ServiceBus` / `EventDispatcher`:**
    *   Permite que componentes se comuniquen sin referencias directas.
    *   *Ejemplo:* `worker` emite evento `JobCompleted`. `dashboard` escucha y actualiza UI. `brain` escucha y libera recurso.

## 2. Capa de Datos (`core/data`)

Actualmente hay mezcla de SQL crudo, `sqlite3` y `pyodbc`.

*   **Repository Pattern (Patrón Repositorio):**
    *   Crear interfaces abstractas: `JobRepository`, `ResourceRepository`, `LogRepository`.
    *   Implementaciones concretas: `SqliteJobRepository`, `SqlServerResourceRepository`, `RedisJobRepository`.
    *   *Ventaja:* Cambiar de SQLite a PostgreSQL para la cola sería cambiar 1 línea de configuración.
*   **Modelos de Dominio (Domain Models):**
    *   Clases puras de Python (Dataclasses o Pydantic) que representan `Job`, `Task`, `Resource`.
    *   Separar la "fila de base de datos" del "objeto de negocio".

## 3. Motor de Ejecución (`core/engine` - Ex `worker`)

El worker actual sabe demasiado sobre HTTP, descargas y lógica de negocio.

*   **`TaskExecutor`:**
    *   Recibe un `Job` genérico.
    *   Busca el `Plugin` adecuado (el sitio).
    *   Ejecuta en un sandbox (proceso aislado, thread, o contenedor).
*   **Plugins de Sitios (`sites/` refactorizado):**
    *   Interfaz estricta:
        ```python
        class SitePlugin(ABC):
            def validate_payload(self, payload: dict) -> SiteTaskModel: ...
            async def run(self, task: SiteTaskModel, context: BrowserContext) -> TaskResult: ...
        ```
    *   **Separación de Navegación:** La lógica de "hacer click" (`PageObjects`) separada de la lógica de "qué hacer si falla" (Flow).

## 4. El Cerebro (`core/brain` - Ex `brain`)

Transformarlo en un planificador de recursos puro.

*   **`ResourceDiscoveryService`:**
    *   Abstracción para "encontrar cosas que hacer". Hoy es SQL Server, mañana podría ser una API REST externa.
*   **`PolicyEngine`:**
    *   Lógica de prioridades, cuotas y backpressure extraída a clases configurables.
    *   *Ejemplo:* `RoundRobinPolicy`, `PriorityQueuePolicy`.
*   **`ClaimManager`:**
    *   Servicio transaccional para marcar recursos como "tomados" (evita race conditions).

## 5. Interfaz y Control (`dashboard/` y `api/`)

El dashboard actual mezcla lógica de presentación con gestión de procesos.

*   **API Layer (FastAPI puro):**
    *   Solo define rutas y esquemas de entrada/salida.
    *   Delega a `Controller` o `Service` la lógica real.
*   **Process Supervisor (SupervisorD-like en Python):**
    *   Una librería robusta (evolución de `process_launcher`) que gestione el ciclo de vida.
    *   Capacidades: Auto-restart, Health checks, Logging rotativo centralizado.
*   **Frontend Desacoplado:**
    *   El frontend (Next.js) debe ser un consumidor de la API, sin saber si el backend corre en local o en otro servidor.

## 6. Infraestructura y Despliegue

*   **Docker Containerization:**
    *   Cada servicio (`brain`, `worker`, `dashboard`) en su propio contenedor (o un compose orquestado).
    *   Elimina problemas de "en mi máquina funciona" y dependencias de OS (como `cmd` vs `bash`).
*   **Unified Logging:**
    *   Logs estructurados (JSON) enviados a stdout.
    *   Un recolector (como Fluentd o simplemente Docker logs) se encarga de guardarlos/rotarlos.

## Hoja de Ruta (Roadmap) para la Transformación

1.  **Fase 1: Interfaces (The Blueprints):** Definir `JobRepository`, `SitePlugin` y `ConfigModel`. No cambiar código, solo definir contratos.
2.  **Fase 2: Adaptadores de Datos:** Mover el SQL de `brain.py` y `sqlite_db.py` a repositorios.
3.  **Fase 3: Estandarización de Sitios:** Migrar un sitio (ej. `madrid`) al nuevo formato de Plugin.
4.  **Fase 4: Core Engine:** Reescribir el bucle del worker para usar Plugins.
5.  **Fase 5: Dockerización:** Crear `Dockerfile` y `docker-compose.yml`.

Esta arquitectura permite que si mañana cambia la web de "Madrid", solo tocas la pieza "Madrid". Si cambias de base de datos, solo tocas el "Repository". Si quieres correr en Mac, Linux o Windows, el "Process Launcher" se encarga.
