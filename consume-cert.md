# Plan de acción: modo Worker (certificado sin popups)

Objetivo: ejecutar **Xaloc 2026** en modo desatendido (24/7) evitando que el popup nativo del certificado bloquee el proceso, y procesando trámites desde una cola persistente.

## Alcance

- Windows + Edge (Playwright) con **autoselección de certificado** vía políticas.
- Cola de trámites en **SQLite** (local) como primer paso (sin servidor externo).
- Nuevo entrypoint `worker.py` que sustituye la interacción de `main.py`.
- Mantener el modo “seguro/demo” actual: llegar a pantallas finales pero **sin firmar/presentar** donde aplique.

## Entregables

- `setup_worker_env.ps1`: configura Edge para autoseleccionar certificado (sin prompt).
- `db/schema.sql` + `db/xaloc_database.db`: cola `tramite_queue`.
- `worker.py`: bucle que toma tareas `pending`, ejecuta el site y actualiza estado.
- Ajustes menores de configuración para perfíl persistente y rutas (si hiciera falta).
- Documentación mínima de operación (cómo preparar el perfil, arrancar/parar, y cómo encolar tareas).

---

## 1) “Eliminador de popups”: política de Edge (registro)

**Meta:** que Edge no muestre el selector de certificado y elija automáticamente el disponible **solo** para las URLs del proyecto (Madrid + Girona + Tarragona), en vez de `https://*`.

1. Crear `setup_worker_env.ps1` (ejecutar como Administrador):
   ```powershell
   # setup_worker_env.ps1
   # Ejecutar como Administrador

   $registryPath = "HKLM:\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls"
   if (!(Test-Path $registryPath)) { New-Item -Path $registryPath -Force }

   # Lista explícita de URLs donde Edge debe autoseleccionar certificado (sin popup)
   # Nota: cada entrada crea un valor "1", "2", "3"... en el registro.
   #
   # Madrid
   # - sites/madrid/config.py: https://sede.madrid.es/...
   # - sites/madrid/flows/navegacion.py: https://servcla.madrid.es/... y enlaces a https://servpub.madrid.es/...
   #
   # Girona
   # - sites/xaloc_girona/config.py: https://www.xalocgirona.cat/... y post-login en https://seu.xalocgirona.cat/...
   #
   # Tarragona (BASE On-line)
   # - sites/base_online/config.py: https://www.base.cat/...
   # - sites/base_online/flows/navegacion.py: https://www.baseonline.cat/...
   $certUrlPatterns = @(
     "https://sede.madrid.es/*",
     "https://servcla.madrid.es/*",
     "https://servpub.madrid.es/*",
     "https://www.xalocgirona.cat/*",
     "https://seu.xalocgirona.cat/*",
     "https://www.base.cat/*",
     "https://www.baseonline.cat/*"
   )

   $i = 1
   foreach ($pattern in $certUrlPatterns) {
     $policyValue = "{`"pattern`":`"$pattern`",`"filter`":{}}"
     New-ItemProperty -Path $registryPath -Name "$i" -Value $policyValue -PropertyType String -Force | Out-Null
     $i++
   }

   Write-Host "Configuración de Edge completada. El popup ya no aparecerá." -ForegroundColor Green
   ```
2. Verificación:
   - Reiniciar Edge (y cualquier proceso `msedge.exe` residual).
   - Validar la clave con `reg query` o `Get-ItemProperty`.
3. Rollback (por si se necesita volver al modo interactivo):
   - Eliminar el valor `1` o la clave completa `AutoSelectCertificateForUrls`.

**Notas:**
- Esta política aplica a Edge (y puede requerir ejecución con permisos elevados).
- En entornos sin escritorio, esta vía evita depender de `pyautogui` (`utils/windows_popup.py`).
- Si el login abre un dominio adicional (p.ej. VALID/IdP), añadirlo a `$certUrlPatterns`. Pista: el log actual imprime `Pestaña detectada: <url>` en `sites/xaloc_girona/flows/login.py`.

---

## 2) Perfil persistente (reutilizar “decisión”/estado)

**Meta:** que el Worker use un perfil persistente dedicado (p.ej. `profiles/worker/`) para:
- reutilizar cookies/sesión si aplica,
- evitar prompts repetidos,
- mantener estado estable entre ejecuciones.

Acciones:
- Definir una ruta de perfil “worker” (p.ej. `profiles/edge_worker/`).
- Confirmar que `core/base_automation.py` usa `chromium.launch_persistent_context(...)` con:
  - canal `msedge` (o `executable_path` si se fija una ruta específica),
  - `headless=True` en Worker (con opción de debugging en visible),
  - timeouts/logging ya existentes.

**Checklist de aceptación:**
- Al ejecutar cualquier site 2 veces seguidas, usa el mismo perfil (mismas cookies/estado).
- No aparece popup de selección de certificado (tras aplicar política).

---

## 3) Cola persistente en SQLite (db)

**Meta:** que haya una fuente de verdad de tareas para ejecutar sin intervención humana.

1. Crear carpeta `db/` y un `schema.sql` con:
   ```sql
   CREATE TABLE IF NOT EXISTS tramite_queue (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       site_id TEXT NOT NULL,          -- 'madrid', 'base_online', 'xaloc_girona'
       protocol TEXT,                  -- 'P1', 'P2', 'P3'
       payload JSON NOT NULL,          -- Datos del formulario en JSON
       status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
       attempts INTEGER DEFAULT 0,
       screenshot_path TEXT,
       error_log TEXT,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );
   ```
2. Crear el archivo `db/xaloc_database.db` e inicializarlo aplicando `schema.sql`.

**Recomendación de robustez (para más adelante):**
- Reclamar tareas de forma atómica (evitar dos workers procesando la misma fila) usando transacciones/`BEGIN IMMEDIATE` o un `UPDATE ... WHERE status='pending'` con verificación.
- Incrementar `attempts` y reintentar con backoff antes de marcar como `failed`.

---

## 4) `worker.py`: motor desatendido

**Meta:** reemplazar `main.py` (CLI interactivo) por un proceso que:
- consulta la DB,
- marca tarea como `processing`,
- ejecuta el flujo del site,
- actualiza `completed/failed` con evidencia y logs.

Diseño propuesto:
- Bucle infinito con `asyncio.sleep(10)` cuando no hay trabajo.
- Logger a consola + fichero (reutilizando patrón del repo en `logs/`).
- Integración con `core/site_registry.py`:
  - `get_site(site_id)` -> clase `Automation`
  - `get_site_controller(site_id)` -> construye config/base payload
- Ejecutar un método común (a decidir según lo existente): p.ej. `Automation.ejecutar_flujo_completo(payload)` o equivalente por site.

**Criterios de aceptación:**
- Si no hay tareas `pending`, el worker no falla y espera.
- Al insertar una tarea `pending`, pasa por `processing` -> `completed/failed`.
- En `failed`, se guarda `error_log` y ruta de screenshot si existe.
- No solicita input por consola en ningún caso.

---

## 5) Encolado de tareas (operación mínima)

**Meta:** forma simple y repetible de crear filas `pending`.

Opciones (de menor a mayor esfuerzo):
1. Script `enqueue_task.py` que inserte en SQLite (CLI).
2. “Backoffice” mínimo (web) que escriba en la cola (futuro).
3. Import desde Excel/CSV (futuro).

Ejemplo de inserción (conceptual):
- `site_id='base_online'`, `protocol='P1'`, `payload={...}` (JSON).

---

## 6) Operación 24/7 (Windows)

**Meta:** que el worker arranque solo y se recupere de fallos.

1. Preparación:
   - `python -m venv venv` + `pip install -r requirements.txt`
   - `python -m playwright install msedge`
   - Ejecutar `setup_worker_env.ps1` como Admin
   - Correr una vez en modo visible para confirmar login/certificado si hace falta (calentar perfil).
2. Servicio:
   - Programador de tareas de Windows (Task Scheduler) o NSSM para “python worker.py”.
3. Observabilidad:
   - Revisar `logs/` y `screenshots/` como evidencia.

---

## Riesgos y mitigaciones

- **Sin escritorio:** evitar `pyautogui` y depender de política + perfil persistente.
- **Concurrencia:** si se corren múltiples workers, asegurar “claim” atómico en DB.
- **Portales lentos/inestables:** parametrizar timeouts por site y capturar screenshots al fallar.
- **Cambios de UI:** centralizar selectores en `sites/<site>/config.py` y mantener regresión con pruebas manuales rápidas.
