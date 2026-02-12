# Diseño de la Interfaz de Usuario para Control Centralizado

Este documento describe la nueva estructura del Dashboard para incluir capacidades de gestión de procesos y listas negras, priorizando una UX sencilla y accesible.

## 1. Navegación Principal

El dashboard existente (`dashboard-frontend/index.html`) se reorganizará mediante un sistema de pestañas o navegación lateral.

### Secciones Propuestas
1. **Estado General (Inicio)**: Resumen de colas, actividad reciente y métricas clave. (Ya existe).
2. **Panel de Control**: Gestión de `worker.py` y `brain.py`. (Nueva).
3. **Listas Negras / Bloqueos**: Gestión de recursos bloqueados. (Nueva).
4. **Colas**: Vista detallada de las colas. (Ya existe).
5. **Histórico**: Registro histórico de actividad. (Ya existe).

---

## 2. Panel de Control (Nueva Sección)

Esta vista permitirá controlar los componentes principales del sistema sin tocar la terminal.

### Layout
- **Dos Tarjetas Principales**:
  - **Worker**: Control del proceso de ejecución de tareas.
  - **Brain**: Control del orquestador.

### Componentes por Tarjeta
1. **Encabezado**: Nombre del Proceso (`WORKER`, `BRAIN`).
2. **Indicador de Estado**:
   - 🟢 **Activo (Running)**: Color verde brillante.
   - 🔴 **Inactivo (Stopped)**: Color gris o rojo suave.
   - ⚠️ **Error**: Color naranja/ámbar si el proceso terminó inesperadamente.
3. **Botones de Acción**:
   - `[▶ INICIAR]`: Habilitado solo si está Inactivo. Color Verde/Azul.
   - `[⏹ DETENER]`: Habilitado solo si está Activo. Color Rojo.
   - `[↻ REINICIAR]`: Habilitado si está Activo. Color Naranja.
4. **Visor de Logs (Terminal View)**:
   - Caja de texto (`<pre>` o `textarea readonly`) con fondo oscuro y letra monospace.
   - Muestra las últimas 50-100 líneas del log.
   - **Auto-scroll**: Checkbox para activar/desactivar el desplazamiento automático al final.
   - Botón `[Refrescar Logs]` o actualización automática cada 2-5 segundos.

---

## 3. Listas Negras / Recursos Bloqueados (Nueva Sección)

Esta vista permitirá gestionar los recursos que han sido bloqueados por errores repetidos o manualmente.

### Tabla de Recursos Bloqueados
- **Columnas**:
  - **ID Recurso**: Identificador numérico.
  - **Site ID**: Organismo (`madrid`, `xaloc_girona`, etc.).
  - **Motivo**: Razón del bloqueo (ej. "Error 500 recurrente", "Credenciales inválidas").
  - **Origen**: Quién/qué lo bloqueó (`worker`, `manual`).
  - **Fecha**: Cuándo ocurrió el bloqueo.
  - **Acciones**: Botón `[🔓 Desbloquear]`.

### Formulario de Bloqueo Manual (Opcional/Avanzado)
- Campos para introducir `Site ID`, `ID Recurso` y `Motivo` manualmente.
- Botón `[Bloquear Recurso]`.

---

## 4. Configuración (Mejora Opcional)

Si se decide exponer la configuración (`organismo_config`), se puede añadir una vista de tabla editable.

- **Tabla de Configuración**:
  - **Site ID** (No editable).
  - **Activo** (Switch On/Off).
  - **URL Login** (Editable).
  - **Regex Expediente** (Editable).
  - **Filtro TExp** (Editable).
  - Botón `[Guardar Cambios]`.

---

## 5. Experiencia de Usuario (UX)

- **Feedback Inmediato**: Al pulsar "Iniciar" o "Detener", mostrar un spinner o deshabilitar el botón hasta confirmar el cambio de estado.
- **Notificaciones (Toasts)**:
  - "Worker iniciado correctamente" (Verde).
  - "Error al detener Brain" (Rojo).
  - "Recurso 12345 desbloqueado" (Azul).
- **Actualización en Tiempo Real**: El estado de los procesos debe refrescarse periódicamente (polling cada 5s) para reflejar si un proceso se cae inesperadamente.
