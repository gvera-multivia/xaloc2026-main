# Investigación: Simultaneidad de Trámites y Arquitectura por Organismo (noVNC)

## 1. Estado Actual y Tecnología de Visualización
**Nota importante:** El sistema de "Screencast" (frames JPEG) ha sido deprecado en favor de **noVNC**, que proporciona una transmisión de video en tiempo real del navegador mucho más fluida y eficiente.

Para lograr la simultaneidad, el sistema debe permitir múltiples sesiones de noVNC activas, una por cada navegador en ejecución.

---

## 2. Estrategia: Un Organismo por Docker
La arquitectura recomendada para escalar el sistema es dedicar un par de contenedores (Worker + Playwright Runner) a cada organismo o sitio específico.

### Beneficios de esta aproximación:
*   **Aislamiento de Recursos:** Un trámite pesado en "Madrid" no ralentiza a "Palma".
*   **Configuración Específica:** Cada contenedor puede tener sus propias variables de entorno, certificados y políticas de autoselección.
*   **Simplicidad en el Filtrado:** El Worker solo solicita tareas de su organismo asignado, simplificando la lógica de la cola.

---

## 3. Implementación de la Visualización Multi-puesto (noVNC)
Al tener varios contenedores `playwright-runner`, cada uno tendrá su propia instancia de noVNC. Para que el Dashboard muestre la "cámara" correcta, se propone:

1.  **Registro Dinámico de URLs:**
    *   Cada contenedor `playwright-runner` expone noVNC en un puerto distinto o bajo una ruta única.
    *   Al arrancar, el Worker obtiene su URL de noVNC (ej: `http://runner-madrid:6080/vnc.html`) y la registra en la tabla `worker_runtime` de PostgreSQL.
2.  **Consumo en el Dashboard:**
    *   El Dashboard ya no usará una variable de entorno estática para la URL de noVNC.
    *   Consultará la API `/api/control/status` o una nueva ruta `/api/workers/active` para obtener la lista de workers y sus respectivas URLs de noVNC.
    *   El usuario podrá seleccionar qué worker visualizar, y el frontend cargará el `iframe` con la URL registrada para ese worker.

---

## 4. Cambios Técnicos Necesarios

### A. Worker (Consumer)
*   **Filtrado por Site:** Añadir soporte para una variable `WORKER_SITE_ID` que, si está presente, haga que el worker ignore tareas de otros sitios en el método `reserve`.
*   **Heartbeat con URL:** Incluir la `NOVNC_URL` en el latido (heartbeat) que el worker envía a la base de datos.

### B. Playwright Runner
*   Asegurar que cada instancia use un puerto de noVNC único si están en la misma red, o usar nombres de servicio de Docker (ej: `playwright-runner-madrid`) para que el proxy los identifique.

### C. Dashboard API
*   Modificar `/api/queue/live-viewer` para que acepte un `worker_id` y devuelva la URL específica almacenada en la base de datos.

### D. Docker Compose
Ejemplo de configuración para dos organismos:
```yaml
services:
  worker-madrid:
    image: xaloc-worker
    environment:
      - WORKER_SITE_ID=madrid
      - PLAYWRIGHT_RUNNER_URL=http://runner-madrid:8111
      - NOVNC_INTERNAL_URL=http://runner-madrid:6080

  runner-madrid:
    image: xaloc-playwright-runner
    ports: ["6081:6080"]

  worker-palma:
    image: xaloc-worker
    environment:
      - WORKER_SITE_ID=ayunta_palma
      - PLAYWRIGHT_RUNNER_URL=http://runner-palma:8111
      - NOVNC_INTERNAL_URL=http://runner-palma:6080

  runner-palma:
    image: xaloc-playwright-runner
    ports: ["6082:6080"]
```

---

## 5. Conclusión
La transición a un modelo de **"Un Organismo por Docker"** con **noVNC** es el camino más natural para el proyecto. Aprovecha la infraestructura de microservicios actual y resuelve los conflictos de concurrencia (perfiles, certificados, bloqueos) al proporcionar aislamiento total por proceso.
