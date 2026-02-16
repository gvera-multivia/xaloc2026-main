# Investigación: Sistema Multi-usuario y Gestión de Incidencias Concurrentes (V2: Redis + Real-Time)

## 1. Contexto y Definición del Problema

El sistema de automatización (`xaloc_automation`) necesita evolucionar hacia una arquitectura **multi-usuario en tiempo real** que soporte:
1.  **Concurrencia:** Múltiples operadores resolviendo incidencias sin pisarse.
2.  **Interactividad:** Actualizaciones inmediatas en el Dashboard (WebSockets) sin necesidad de recargar la página.
3.  **Coordinación Eficiente:** Uso de Redis para bloqueos distribuidos (Locks), colas de trabajo y monitoreo de estado de los Workers.

### Requerimientos Clave (V2):
*   **Redis como Orquestador:** Manejo de Locks (`lock:incident:{id}`), Colas (`queue:tramites`) y Presencia (`worker:status:{id}`).
*   **Comunicación en Tiempo Real:** Pub/Sub de Redis puenteado a WebSockets en el Frontend.
*   **Persistencia Robusta:** Transición recomendada de SQLite a PostgreSQL para manejo relacional complejo (Usuarios/Roles/Historial).

---

## 2. Arquitectura de Datos en Redis

Para mantener el orden y la eficiencia, se define la siguiente estructura de claves y convenciones:

### 2.1. Naming Convention
| Tipo | Clave (Key) | Valor / Estructura | Propósito | Expiración (TTL) |
| :--- | :--- | :--- | :--- | :--- |
| **Lock** | `lock:incident:{id}` | `user_id` (String) | Bloqueo exclusivo para edición. Evita conflictos. | 30 min (1800s) |
| **Cola** | `queue:tramites` | List (JSON) | Tareas pendientes que los workers procesan (FIFO). | N/A |
| **Estado Worker** | `worker:status:{w_id}` | JSON (String) | Info del robot: `{"status": "busy", "task_id": 123}`. | 60s (Heartbeat) |
| **Pub/Sub** | `channel:ui_updates` | Mensaje JSON | Canal para difundir eventos al Dashboard. | N/A |

---

## 3. Contratos de Mensajes (JSON)

### A. Para los WebSockets (Backend → Frontend)
El backend escucha el canal `channel:ui_updates` de Redis y retransmite los mensajes a los clientes conectados vía WebSocket.

**Evento: Incidencia Bloqueada/Reclamada**
```json
{
  "event": "INCIDENT_LOCKED",
  "data": {
    "incident_id": 1025,
    "user_id": 7,
    "username": "Ana Operador",
    "expires_at": "2023-10-27T10:30:00Z"
  }
}
```

**Evento: Actualización de Worker**
```json
{
  "event": "WORKER_UPDATE",
  "data": {
    "worker_id": "robot_01",
    "status": "processing",
    "current_incident": 1025,
    "progress": 45
  }
}
```

### B. Para la Cola de Trabajo (Backend → Workers)
Estructura del payload que el worker recibe al hacer `BRPOP` de `queue:tramites`.

```json
{
  "task_id": "uuid-9876",
  "incident_id": 1025,
  "type": "RETRY_SUBMISSION",
  "payload": {
    "url": "https://sede.administracion.gob...",
    "data_to_fix": { "field": "cp", "value": "08001" }
  },
  "created_at": "2023-10-27T10:00:00Z"
}
```

---

## 4. Flujo de Trabajo "Real-Time"

### Paso 1: El Error (Worker → DB → Redis)
1.  El Worker encuentra un error en un trámite.
2.  Persiste el error en la Base de Datos Principal (PostgreSQL/SQLite).
3.  Publica el evento en Redis: `PUBLISH channel:ui_updates '{"event": "NEW_INCIDENT", "id": 1025}'`.
4.  **Resultado UI:** El Dashboard muestra una alerta roja o actualiza la lista al instante.

### Paso 2: La Reclamación (Usuario → Redis)
1.  El Usuario pulsa "Atender" en el Dashboard.
2.  FastAPI ejecuta: `SET lock:incident:1025 {user_id} NX EX 1800`.
3.  **Si tiene éxito (NX = Not Exists):**
    *   Publica `INCIDENT_LOCKED` en `channel:ui_updates`.
    *   **Resultado UI:** El botón se deshabilita para el resto de usuarios ("En uso por Ana").
    *   El usuario entra a la pantalla de edición.
4.  **Si falla:** Informa al usuario que la incidencia ya está siendo atendida.

### Paso 3: La Resolución (Usuario → Redis/Worker)
1.  El Usuario corrige los datos y pulsa "Re-lanzar".
2.  FastAPI:
    *   Elimina el bloqueo: `DEL lock:incident:1025`.
    *   Añade la tarea a la cola: `LPUSH queue:tramites {task_json}`.
    *   Publica `INCIDENT_RELEASED` (o `INCIDENT_QUEUED`).
3.  **Resultado UI:** La incidencia desaparece de la lista "Pendientes".
4.  **Worker:** Un Worker libre hace `BRPOP`, recibe la tarea y empieza a trabajar inmediatamente.

---

## 5. Gestión de "Presencia" de Workers (Heartbeat)

Para detectar robots caídos ("Zombis"):
1.  **Heartbeat:** Cada Worker ejecuta un hilo en segundo plano que hace `SET worker:status:{id} {info} EX 60` cada 30 segundos.
2.  **Monitoreo:** El Dashboard (o un servicio de backend) consulta `KEYS worker:status:*`.
3.  **Detección de Fallos:** Si un worker crashea, deja de enviar el heartbeat. A los 60 segundos, la clave expira automáticamente en Redis. El Dashboard deja de recibirlo y lo marca como "Offline".

---

## 6. Stack Tecnológico Recomendado (Final)

1.  **Persistencia:** **PostgreSQL**.
    *   Motivo: Integridad referencial fuerte para Usuarios, Roles e Historial. SQLite tiene limitaciones de concurrencia de escritura que podrían ser un cuello de botella con múltiples usuarios escribiendo logs simultáneamente.
2.  **Coordinación & Caché:** **Redis**.
    *   Motivo: Estándar de industria para Locks distribuidos, Colas rápidas y Pub/Sub.
3.  **Backend API:** **FastAPI**.
    *   Librerías: `redis-py` (modo async) para interactuar con Redis. `WebSockets` nativos de FastAPI.
4.  **Frontend:** **Next.js + TanStack Query**.
    *   Motivo: TanStack Query maneja el estado del servidor eficientemente. Next.js provee SSR/SSG.

---

## 7. Plan de Acción Detallado

Ver el documento adjunto `ACTION_PLAN_REDIS_MIGRATION.md` para la guía paso a paso de implementación.
