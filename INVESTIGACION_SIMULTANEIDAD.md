# Investigación: Simultaneidad de Trámites en Xaloc 2026

## 1. Estado Actual: ¿Es factible hoy?
**No de forma inmediata**, pero sí con cambios técnicos menores y una reconfiguración de la arquitectura.

El sistema actual tiene varios "cuellos de botella" que fuerzan la ejecución secuencial (un trámite después de otro):
1.  **Bloqueo Global en Runner:** El microservicio `playwright-runner-service` tiene un `asyncio.Lock()` global que impide que dos trámites se ejecuten a la vez en el mismo contenedor.
2.  **Cámara (Screencast) Única:** El archivo que genera la vista en vivo es fijo (`live_frame.jpg`). Si dos navegadores escribieran ahí a la vez, la imagen se corrompería o parpadearía.
3.  **Perfiles de Navegador:** Se usa una ruta fija (`profiles/worker`). Chromium bloquea el perfil si otra instancia intenta usarlo.
4.  **Certificados:** La importación de certificados en la base de datos NSS de Linux durante el arranque puede causar conflictos de acceso si varios procesos lo hacen simultáneamente sobre el mismo volumen.

---

## 2. ¿Varios Dockers o un Docker con varios Navegadores?

### Opción Recomendada: Varios Dockers (Escalabilidad Horizontal)
Es la opción más robusta y fácil de implementar. Cada "unidad de trabajo" (Worker + Playwright Runner) vive en su propio contenedor.

*   **Ventajas:**
    *   **Aislamiento Total:** Si un navegador falla o se cuelga, no afecta a los demás.
    *   **Gestión de Certificados:** Cada contenedor tiene su propio almacén NSS.
    *   **Recursos:** Puedes limitar CPU/RAM por contenedor.
    *   **Cámara:** Cada contenedor sirve su propio flujo de vídeo/imagen.
*   **Implementación:** Simplemente hay que instanciar más servicios en el `docker-compose.yml` o usar un orquestador (Docker Swarm/Kubernetes) para hacer `replica: 3`.

### Opción Descartada: Un Docker con varios Navegadores
Sería mucho más complejo de gestionar internamente.
*   **Desventajas:** Habría que gestionar múltiples puertos de VNC/noVNC (5900, 5901...), múltiples carpetas de perfiles dinámicamente y eliminar los bloqueos (`Locks`) del código Python.

---

## 3. Solución para la "Cámara" (Screencast)
Para poder ver uno u otro trámite en el Dashboard, se requiere:

### A. Identificación de Stream
Actualmente, el Dashboard pide `/api/queue/live-screenshot` y el backend lee siempre el mismo archivo.
**Cambio propuesto:**
1.  Cada Worker debe generar su frame con un ID: `live_frame_{worker_id}.jpg`.
2.  El Dashboard API debe aceptar el ID: `/api/queue/live-screenshot?worker_id=worker-1`.

### B. Selector en el Dashboard
La interfaz de usuario necesita un componente de "Selector de Cámara":
1.  Consultar la tabla `worker_runtime` para ver qué workers están "online".
2.  Mostrar un desplegable o miniaturas de los trámites activos.
3.  Al seleccionar uno, el componente `LiveScreencast` cambiará la URL del stream para apuntar al archivo del worker seleccionado.

---

## 4. Plan de Acción para habilitar la Simultaneidad

1.  **Eliminar el `_EXECUTE_LOCK`** en `services/playwright_runner/app.py` para permitir peticiones concurrentes (si se opta por un solo runner potente) o, mejor aún, desplegar múltiples runners.
2.  **Parametrizar el nombre del frame:** Modificar `BaseAutomation` para que acepte un sufijo o ID de worker al guardar el JPEG.
3.  **Configurar Rutas Dinámicas de Perfil:** Asegurar que cada instancia de Playwright use un subdirectorio único en `profiles/` (ej: `profiles/worker_1`, `profiles/worker_2`).
4.  **Actualizar el Dashboard:**
    *   Backend: Servir imágenes basadas en el ID del worker.
    *   Frontend: Añadir el selector de "Cámaras Activas".
5.  **Ajustar `docker-compose`:** Escalar el servicio `worker-orchestrator` y `playwright-runner-service`.

## 5. Conclusión
**Es perfectamente factible.** La arquitectura ya está orientada a microservicios, lo que facilita enormemente el escalado mediante **múltiples contenedores Docker**. El reto principal no es la ejecución en sí, sino la **coordinación de las evidencias visuales (cámara)** y los **bloqueos de perfil de navegador**, problemas que se resuelven asignando identidades únicas a cada instancia.
