# Investigación: Sistema Multi-usuario y Gestión de Incidencias Concurrentes

## 1. Contexto y Definición del Problema

Actualmente, el sistema de automatización (`xaloc_automation`) opera bajo un modelo centralizado donde los "workers" procesan tareas de una cola (`tramite_queue` en SQLite) de manera automática. La intervención humana es necesaria cuando ocurren incidencias o se requieren autorizaciones manuales.

El objetivo es evolucionar la aplicación actual (Dashboard en Next.js + FastAPI) para soportar múltiples usuarios humanos trabajando simultáneamente en la resolución de incidencias, evitando conflictos (ej. dos personas intentando arreglar el mismo expediente a la vez) y restringiendo el acceso según roles.

### Requerimientos Clave:
1.  **Control de Acceso (RBAC):**
    *   **Administrador:** Acceso total (Configuración, Logs, Gestión de Usuarios, todas las colas).
    *   **Operador (Usuario Estándar):** Acceso restringido a:
        *   Estado (Ver colas).
        *   Gestión (Resolver incidencias).
        *   Historial (Consultar expedientes pasados).
2.  **Concurrencia:** Evitar que dos usuarios editen/resuelvan la misma incidencia simultáneamente.
3.  **Asignación:** Mecanismo para repartir el trabajo (Manual vs Automático).

---

## 2. Control de Acceso Basado en Roles (RBAC)

Para soportar múltiples usuarios, el sistema necesita dejar de ser "single-tenant" (o sin autenticación real) e implementar una tabla de usuarios y sesiones.

### 2.1. Cambios en Base de Datos (SQLite)
Se requiere una nueva tabla `users` en `core/sqlite_db.py`:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT CHECK(role IN ('admin', 'operator')) DEFAULT 'operator',
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);
```

### 2.2. Implementación en FastAPI (`dashboard_api.py`)
Utilizaríamos **OAuth2 con Password Flow** y **JWT Tokens**.
*   **Dependencia:** `fastapi.security.OAuth2PasswordBearer`.
*   **Flujo:**
    1.  Usuario hace POST a `/token` con usuario/contraseña.
    2.  Servidor valida hash (usando `bcrypt` o `passlib`) y retorna un JWT firmado.
    3.  El JWT contiene el `role` del usuario.
    4.  Endpoints protegidos leen el JWT e inyectan el usuario actual (`current_user`).
    5.  Middleware o dependencias para verificar permisos: `RequireRole('admin')`.

---

## 3. Modelos de Concurrencia y Asignación

El problema principal es la **Condition de Carrera (Race Condition)**: El Usuario A abre una incidencia para arreglarla. El Usuario B abre la misma 10 segundos después. Ambos intentan guardar cambios. El último en guardar sobrescribe al primero, o el sistema genera un estado inconsistente.

Analicemos tres estrategias para resolver esto:

### Modelo A: "Shark Tank" (Pull / Reclamación) - **RECOMENDADO**
Los usuarios ven una lista global de incidencias pendientes ("pool"). Para trabajar en una, deben "reclamarla" explícitamente.

*   **Flujo:**
    1.  El usuario ve la lista de incidencias con estado `pending_fix`.
    2.  Hace clic en "Atender".
    3.  El sistema marca la tarea: `assigned_to = UserA`, `status = 'fixing'`, `locked_at = NOW`.
    4.  La tarea desaparece de la lista general o aparece marcada como "En uso por UserA".
    5.  Nadie más puede entrar a esa tarea.
*   **Pros:** Sencillo, flexible, evita cuellos de botella si un usuario se va a comer (el admin puede liberar la tarea).
*   **Contras:** Requiere acción explícita del usuario.

### Modelo B: "The Dealer" (Push / Reparto Automático)
El sistema asigna incidencias automáticamente a los usuarios conectados (Round Robin o por carga).

*   **Flujo:**
    1.  El usuario se loguea.
    2.  El sistema busca incidencias sin asignar y se las asigna al usuario automáticamente.
    3.  El usuario ve "Mis Tareas" y no tiene que elegir.
*   **Pros:** Eficiencia máxima teórica. Nadie "escoge las fáciles".
*   **Contras:** Complejo de implementar (detectar presencia real, qué pasa si el usuario ignora la tarea, re-asignación por timeouts). Puede ser estresante para el usuario.

### Modelo C: Asignación por Manager
Un usuario "Jefe de Sala" asigna manualmente las incidencias a cada operador.

*   **Pros:** Control total humano.
*   **Contras:** Cuello de botella en el manager. Micro-management innecesario.

---

## 4. Solución Técnica Propuesta: "Bloqueo Optimista con Reclamación"

Para este proyecto, dado el stack (Python/SQLite/FastAPI) y el caso de uso (automatización administrativa), la mejor solución es el **Modelo A (Pull) con Bloqueo Exclusivo**.

### 4.1. Cambios en Esquema de Datos (`tramite_queue`)
Añadiremos columnas para controlar el bloqueo humano:

```sql
ALTER TABLE tramite_queue ADD COLUMN assigned_to_user_id INTEGER REFERENCES users(id);
ALTER TABLE tramite_queue ADD COLUMN locked_at TIMESTAMP;
-- El status ya existe, pero definiremos nuevos estados lógicos para UI
-- status actuales: 'pending', 'processing', 'completed', 'failed'
-- status propuesto para intervención humana: 'manual_intervention'
```

### 4.2. API Endpoints Necesarios

1.  **`POST /api/incidents/{id}/claim`**
    *   Verifica si `assigned_to_user_id` es NULL o si el bloqueo expiró (ej. > 30 min).
    *   Si está libre: `UPDATE tramite_queue SET assigned_to_user_id = me, locked_at = NOW WHERE id = {id}`.
    *   Si está ocupado: Retorna 409 Conflict ("Tarea bloqueada por Usuario B").

2.  **`POST /api/incidents/{id}/release`**
    *   Permite al usuario (o admin) soltar la tarea sin resolverla.
    *   `UPDATE tramite_queue SET assigned_to_user_id = NULL, locked_at = NULL`.

3.  **`POST /api/incidents/{id}/resolve`**
    *   El usuario marca la incidencia como resuelta.
    *   `UPDATE tramite_queue SET status = 'pending' (para reintento), attempts = 0, assigned_to_user_id = NULL`.

### 4.3. Gestión de "Bloqueos Zombis"
Si un usuario reclama una incidencia y cierra el navegador o se va a casa, la incidencia queda bloqueada.
**Solución:** Un "Heartbeat" o TTL (Time To Live).
*   Si `locked_at` es más antiguo que 30 minutos, cualquiera puede "robar" (re-reclamar) la incidencia, asumiendo que el usuario original abandonó.

---

## 5. Comparativa con el Mundo Real

| Sistema | Modelo | Descripción | Similitud con Proyecto |
| :--- | :--- | :--- | :--- |
| **Jira** | Asignación Explícita | Un ticket tiene un campo `Assignee`. Cualquiera puede cambiarlo, pero generalmente uno se lo asigna a sí mismo. No bloquea edición simultánea estricta, pero avisa. | Alta (Gestión de tareas) |
| **Zendesk** | Pull ("Play") | Botón "Play" que te sirve el siguiente ticket disponible y lo bloquea temporalmente para ti. | Media (Atención al cliente rápida) |
| **Uber** | Algorítmico (Push) | El sistema decide quién recibe el viaje. El conductor tiene pocos segundos para aceptar. | Baja (Tiempo real crítico) |
| **Git** | Merge Conflict | Permite edición paralela y obliga a resolver conflictos al guardar. | Inviable (Muy complejo para usuarios no técnicos) |

---

## 6. Recomendación Final y Plan de Acción

### Recomendación
Implementar el **Modelo de Reclamación (Pull)**. Es intuitivo, fácil de implementar sobre SQLite y escala bien para equipos pequeños/medianos.

### Pasos de Implementación

1.  **Fase 1: Autenticación (Backend)**
    *   Crear tabla `users` y script de seed para crear el primer Admin.
    *   Implementar login (`/token`) y protección de rutas en FastAPI.
    *   Decorador `@requires_role("admin")` para rutas sensibles.

2.  **Fase 2: Asignación de Incidencias (Backend)**
    *   Modificar `tramite_queue` para incluir `assigned_to` y `locked_at`.
    *   Crear endpoints `claim` y `release`.
    *   Modificar endpoints de listado (`GET /api/history/incidents`) para mostrar quién tiene asignada cada tarea.

3.  **Fase 3: Frontend (Dashboard)**
    *   Pantalla de Login.
    *   Ocultar menús (Config, Logs) si el usuario no es Admin.
    *   En la lista de incidencias:
        *   Mostrar candado si está asignada a otro.
        *   Botón "Asignarme" si está libre.
    *   Filtro "Mis Incidencias".

4.  **Fase 4: Limpieza Automática**
    *   Una tarea en background (en `brain.py` o cron) que libere bloqueos antiguos (> 30 min) para evitar tareas huérfanas.

Esta arquitectura asegura que el sistema sea **robusto** (sin conflictos de escritura), **seguro** (cada uno ve lo que debe) y **organizado** (claridad sobre quién está haciendo qué).
