# Seguridad y Control de Acceso (RBAC)

Este documento define la estructura de seguridad, roles y restricciones de acceso para la nueva arquitectura multi-usuario.

---

## 1. Estructura del Token (JWT)

El sistema utilizará **JSON Web Tokens (JWT)** para autenticación y autorización. El token se emite al iniciar sesión y debe enviarse en el header `Authorization: Bearer <token>` de cada petición.

### Payload del Token
```json
{
  "sub": "user_123",           // ID único del usuario
  "username": "ana.operador",  // Nombre visible
  "role": "operator",          // Rol: 'admin' | 'operator'
  "exp": 1698420000            // Expiración (ej. 8 horas)
}
```

*   **Firma:** HMAC SHA256 (HS256) con una clave secreta (`SECRET_KEY`) en el backend.
*   **Renovación:** El frontend debe manejar la expiración (redirección a login o refresh token silencioso).

---

## 2. Matriz de Acceso (Backend API)

Definición estricta de qué puede hacer cada rol en la API.

| Endpoint | Método | Admin | Operator | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `/api/auth/login` | POST | ✅ | ✅ | Inicio de sesión. |
| `/api/users/*` | CRUD | ✅ | ❌ | Gestión de usuarios (Crear, borrar, cambiar contraseñas). |
| `/api/config/*` | CRUD | ✅ | ❌ | Configuración global del sistema y de los Sites. |
| `/api/logs/*` | GET | ✅ | ❌ | Ver logs técnicos del servidor. |
| `/api/control/*` | POST | ✅ | ❌ | Reiniciar servicios, parar workers. |
| `/api/queue/stats` | GET | ✅ | ✅ | Ver estado general de la cola. |
| `/api/incidents` | GET | ✅ | ✅ | Ver lista de incidencias pendientes. |
| `/api/incidents/{id}/claim` | POST | ✅ | ✅ | Bloquear/Reclamar una incidencia para trabajarla. |
| `/api/incidents/{id}/resolve`| POST | ✅ | ✅* | Resolver una incidencia. **(*) Solo si es el dueño del lock.** |
| `/api/incidents/{id}/release`| POST | ✅ | ✅* | Liberar incidencia sin resolver. **(*) Solo si es el dueño del lock.** |
| `/api/history/*` | GET | ✅ | ✅ | Consultar historial de trámites pasados. |

**Nota sobre Admin:** El administrador tiene permisos implícitos para desbloquear (`force release`) incidencias asignadas a otros usuarios si es necesario (ej. usuario enfermo).

---

## 3. Restricciones en Frontend (Next.js)

El frontend debe adaptar la interfaz según el claim `role` del token decodificado.

### 3.1. Protección de Rutas (Middleware)
Usaremos un Middleware en Next.js para interceptar la navegación:

*   **Rutas Públicas:** `/login`
*   **Rutas Protegidas (Cualquier Rol):** `/dashboard`, `/incidents`, `/history`
*   **Rutas Admin:** `/settings`, `/users`, `/logs`

**Lógica del Middleware:**
1.  Si no hay token -> Redirigir a `/login`.
2.  Si intenta entrar a `/settings` y `role !== 'admin'` -> Redirigir a `/dashboard` (o mostrar 403).

### 3.2. Adaptación de la UI (Componentes)

#### Menú de Navegación (Sidebar)
*   **Admin:** Ve todo: "Incidencias", "Historial", "Configuración", "Usuarios", "Logs".
*   **Operator:** Solo ve: "Incidencias", "Historial".

#### Lista de Incidencias
*   **Estado:** Cada fila debe indicar si está "Libre", "Asignada a Mí" o "Asignada a Otro".
*   **Botones de Acción:**
    *   **Libre:** Botón "Atender" habilitado para todos.
    *   **Asignada a Otro (Ana):**
        *   **Operator (Juan):** Botón deshabilitado (gris), tooltip "En uso por Ana".
        *   **Admin:** Botón "Forzar Liberación" (rojo) visible.
    *   **Asignada a Mí:** Botón "Continuar" (verde) y "Soltar" (amarillo).

#### Pantalla de Resolución de Incidencia
*   Al cargar la página `/incidents/{id}`, el frontend verifica:
    1.  ¿El lock en Redis (`lock:incident:{id}`) existe?
    2.  ¿El `user_id` del lock coincide con mi `sub` del token?
*   **Si coincide:** Muestra el formulario de edición.
*   **Si NO coincide:** Muestra mensaje de error "No tienes permiso para editar esta incidencia" y redirige a la lista.

---

## 4. Flujo de Auto-Asignación y Resolución

Para garantizar que nadie resuelva una incidencia que no le pertenece:

1.  **Paso 1 (Claim):** El usuario llama a `POST /claim`. El backend verifica token y crea el lock en Redis con su ID.
2.  **Paso 2 (Work):** El usuario trabaja en la UI.
3.  **Paso 3 (Resolve):** El usuario envía `POST /resolve`.
    *   El Backend **LEE** el lock de Redis: `GET lock:incident:{id}`.
    *   **Validación Crítica:** Compara el valor del lock con el `user_id` del token JWT de la petición.
    *   **Éxito:** Si coinciden, procesa la resolución y borra el lock.
    *   **Fallo:** Si no coinciden (ej. el lock expiró y otro lo tomó), rechaza la petición (403 Forbidden) y avisa al usuario: "Tu sesión de trabajo expiró o la incidencia fue reasignada".
