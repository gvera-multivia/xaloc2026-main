# Plan de Acción: Migración a Redis y Arquitectura Multi-Usuario

Este documento detalla los pasos técnicos necesarios para transformar la aplicación actual en un sistema distribuido, multi-usuario y en tiempo real, utilizando **Redis** como eje central de coordinación.

---

## Fase 1: Infraestructura y Configuración Base

**Objetivo:** Establecer el entorno de Redis y la conectividad básica.

### 1.1. Despliegue de Redis
*   **Acción:** Crear/Actualizar `docker-compose.yml`.
*   **Detalle:** Añadir servicio `redis:alpine` exponiendo el puerto `6379`.
*   **Configuración:** Persistencia activada (`appendonly yes`) para no perder la cola en reinicios.

### 1.2. Módulo de Conexión (`core/redis_client.py`)
*   **Acción:** Crear un módulo singleton para gestionar la conexión asíncrona.
*   **Librería:** `redis-py` (versión async).
*   **Implementación:**
    ```python
    import redis.asyncio as redis
    from core.config import settings

    redis_pool = redis.ConnectionPool.from_url(settings.REDIS_URL)

    def get_redis_client():
        return redis.Redis(connection_pool=redis_pool)
    ```

---

## Fase 2: Backend (FastAPI) - Adaptación Real-Time

**Objetivo:** Permitir que la API gestione bloqueos y comunique eventos al frontend.

### 2.1. Endpoints de Bloqueo (Locks)
*   **Ruta:** `POST /api/incidents/{id}/claim`
*   **Lógica:**
    1.  Obtener usuario actual (JWT).
    2.  Intentar `SET lock:incident:{id} {user_id} NX EX 1800`.
    3.  Si éxito: Retornar 200 OK. Publicar evento `INCIDENT_LOCKED` en canal `ui_updates`.
    4.  Si fallo (ya existe): Retornar 409 Conflict con datos del usuario que tiene el lock (hacer `GET` de la clave).

*   **Ruta:** `POST /api/incidents/{id}/release`
*   **Lógica:**
    1.  Verificar que el `lock:incident:{id}` pertenece al usuario actual.
    2.  `DEL lock:incident:{id}`.
    3.  Publicar evento `INCIDENT_UNLOCKED` en canal `ui_updates`.

### 2.2. WebSockets & Pub/Sub
*   **Ruta:** `WS /ws/dashboard`
*   **Lógica:**
    1.  Aceptar conexión WebSocket.
    2.  Suscribirse (usando `aioredis.pubsub()`) al canal `channel:ui_updates`.
    3.  Bucle infinito: Esperar mensaje de Redis -> Enviar mensaje JSON por WebSocket al cliente.
    4.  Manejar desconexiones limpiamente.

---

## Fase 3: Workers - Adaptación a Colas Redis

**Objetivo:** Que los workers consuman de Redis en lugar de consultar SQLite repetidamente, y reporten su estado en vivo.

### 3.1. Consumo de Tareas (Queue Consumer)
*   **Cambio:** Reemplazar el bucle de "polling" a SQLite en `worker.py` / `brain.py`.
*   **Nueva Lógica:**
    ```python
    while True:
        # Bloquea hasta que haya tarea (timeout 5s para permitir checkeo de señales de stop)
        task = await redis.brpop("queue:tramites", timeout=5)
        if task:
            procesar_tarea(json.loads(task[1]))
    ```
*   **Fallback:** Si la DB sigue siendo SQLite para persistencia histórica, el worker actualiza el estado en DB *después* de procesar, pero la coordinación es Redis.

### 3.2. Heartbeat (Latido)
*   **Acción:** Implementar una tarea en segundo plano (`asyncio.create_task`) en el arranque del Worker.
*   **Lógica:**
    ```python
    async def heartbeat_loop(worker_id):
        while True:
            payload = json.dumps({"status": "busy", "task_id": current_task_id})
            await redis.set(f"worker:status:{worker_id}", payload, ex=60)
            await asyncio.sleep(30)
    ```

---

## Fase 4: Frontend (Dashboard Next.js)

**Objetivo:** Reflejar el estado en tiempo real.

### 4.1. Contexto de WebSocket
*   **Acción:** Crear `WebSocketContext.tsx`.
*   **Funcionalidad:**
    *   Mantener conexión única.
    *   Reconectar automáticamente si se cae.
    *   Exponer función `lastMessage` o `events` a los componentes.

### 4.2. Integración en UI
*   **Lista de Incidencias:**
    *   Escuchar eventos `INCIDENT_LOCKED`.
    *   Si llega uno, buscar la fila correspondiente y deshabilitar el botón "Atender", mostrando "🔒 Ana".
*   **Panel de Control (Workers):**
    *   Escuchar `WORKER_UPDATE`.
    *   Actualizar barras de progreso o estado (Online/Offline) dinámicamente.

---

## Fase 5: Migración de Base de Datos (PostgreSQL) - *Opcional pero Recomendada*

**Objetivo:** Robustez y concurrencia transaccional real.

*   **Paso 1:** Levantar contenedor Postgres.
*   **Paso 2:** Usar herramienta de migración (ej. `alembic` o script custom) para mover datos de `tramite_queue` (SQLite) a Postgres.
*   **Paso 3:** Actualizar `core/db.py` (o similar) para usar driver `asyncpg` en lugar de `aiosqlite`.
*   **Paso 4:** Actualizar modelos de datos (SQLAlchemy / Tortoise ORM) para reflejar las relaciones Users <-> Roles.

---

## Resumen de Tareas Inmediatas

1.  [ ] **Infra:** Añadir Redis a Docker Compose.
2.  [ ] **Backend:** Instalar `redis` (pip). Crear `core/redis_client.py`.
3.  [ ] **Backend:** Implementar endpoint WebSocket `/ws/dashboard`.
4.  [ ] **Backend:** Crear endpoints de Lock/Unlock usando Redis.
5.  [ ] **Worker:** Añadir loop de Heartbeat.
6.  [ ] **Frontend:** Crear Hook `useWebSocket` y conectar a `/ws/dashboard`.
