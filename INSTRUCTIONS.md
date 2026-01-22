# 📘 Guía de Ejecución del Proyecto

Este documento detalla los diferentes modos de ejecución disponibles en el proyecto de automatización.

## 1. Modo Interactivo (CLI)

Utiliza `main.py` para ejecutar automatizaciones de forma interactiva, ideal para pruebas rápidas o ejecuciones puntuales controladas manualmente.

**Comando:**
```bash
python main.py
```

**Flujo:**
1. Seleccionas el sitio (ej. Madrid, Base Online, Xaloc).
2. Seleccionas el protocolo o configuración específica.
3. El script lanza el navegador (visible o headless según configuración) y ejecuta el flujo.

---

## 2. Modo Worker (Desatendido)

Utiliza `worker.py` para procesar una cola de tareas almacenada en la base de datos SQLite local (`db/xaloc_database.db`). Este es el modo principal para producción.

**Comando:**
```bash
python worker.py
```

**Características:**
- Lee tareas pendientes (`status='pending'`) de la tabla `tramite_queue`.
- Procesa una tarea a la vez.
- Descarga documentos adjuntos automáticamente si están definidos en la tarea.
- Actualiza el estado (`completed`, `failed`) y guarda screenshots/logs.
- Funciona en bucle infinito hasta que se interrumpe (Ctrl+C).

**Variables de Entorno Útiles:**
- `WORKER_HEADLESS=1`: Ejecuta el navegador sin interfaz gráfica.

---

## 3. Sincronización y Worker (Flujo Completo)

Este flujo conecta la base de datos origen (SQL Server) con el Worker.

### Paso 1: Sincronizar tareas
Ejecuta `sync_sqlserver_to_worker_queue.py` para leer expedientes de SQL Server e insertarlos en la cola SQLite.

**Comando:**
```bash
python sync_sqlserver_to_worker_queue.py --connection-string "DRIVER={ODBC Driver 17 for SQL Server};SERVER=...;..." --site auto
```

**Argumentos Importantes:**
- `--site`: Filtra por portal (`madrid`, `base_online`, `xaloc_girona`, o `auto`).
- `--fase`: (Opcional) Filtra por fase del procedimiento.
- `--limit`: Limita el número de registros a importar.
- `--dry-run`: Simula la importación sin escribir en la DB.

### Paso 2: Ejecutar el Worker
Una vez poblada la cola, ejecuta el worker para procesarlas:

```bash
python worker.py
```

---

## 4. Encolado Manual de Tareas

Si necesitas probar un caso específico sin pasar por SQL Server, puedes insertar una tarea manualmente en la cola.

**Comando:**
```bash
python enqueue_task.py --site <SITE_ID> --payload <JSON_DATA>
```

**Ejemplo:**
```bash
python enqueue_task.py --site madrid --payload '{"idRecurso": "123", "expediente": "EXP-001", ...}'
```
O usando un archivo JSON:
```bash
python enqueue_task.py --site madrid --payload datos_prueba.json
```

---

## 5. Ejecución de Tests

### Tests Unitarios y de Integración
Ejecuta los tests definidos en el directorio `test_files` o módulos de prueba específicos.

**Test de Adjuntos:**
Verifica la lógica de descarga de adjuntos.
```bash
python -m unittest test_files/test_attachments.py
```

**Test de Validación:**
Verifica las reglas de validación de datos.
```bash
python test_validation_module.py
```

---

## 6. Configuración del Entorno

Antes de ejecutar cualquier modo, asegúrate de tener el entorno configurado.

1. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   playwright install msedge
   ```

2. **Configuración de Certificados (Windows):**
   Ejecuta el script de PowerShell como Administrador para configurar las políticas de selección automática de certificados en Edge.
   ```powershell
   ./setup_worker_env.ps1
   ```
   *El worker también intenta aplicar una configuración local al iniciar si detecta `url-cert-config.txt`.*

3. **Variables de Entorno:**
   Crea un archivo `.env` si es necesario para definir credenciales o flags globales.
