# Documentación del Worker Xaloc 2026

Este documento describe cómo configurar y operar el modo Worker desatendido.

## 1. Configuración del Entorno (Solo una vez)

### 1.1. Prerrequisitos
- Python 3.10+
- Playwright instalado (`playwright install chromium msedge`)
- Dependencias instaladas (`pip install -r requirements.txt`)

### 1.2. Configurar Certificados (Eliminar Popups)
Para evitar que Edge pregunte qué certificado usar en cada conexión, se debe aplicar una política de registro.

1. Abrir PowerShell como **Administrador**.
2. (Opcional pero recomendado) Si hay mas de un certificado instalado, fija el CN para que Edge autoseleccione el correcto:
   ```powershell
   $env:CERTIFICADO_CN = "TU_CN_AQUI"
   ```
   El CN sale del campo `Subject` del certificado (p.ej. `CN=...`).
   Alternativa: pasar el CN como parбmetro:
   ```powershell
   .\setup_worker_env.ps1 -CertSubjectCN "TU_CN_AQUI"
   ```
3. Ejecutar el script `setup_worker_env.ps1`:
   ```powershell
   .\setup_worker_env.ps1
   ```
   Esto añadirá las URLs del proyecto a la lista de autoselección de certificados de Edge (y aplicará el filtro por CN si se ha configurado).

**Nota:** tras aplicar la política, cerrar Edge por completo (todos los procesos `msedge.exe`) para que la nueva configuración tenga efecto.

**Servidor sin PowerShell:** si no puedes ejecutar scripts de PowerShell en el servidor, puedes aplicar la misma polнtica desde `cmd` siguiendo `certificados-cmd.md`.

**Nota (VÀLid/AOC):** si sigue saliendo el selector, revisa que la policy incluya tambiйn `https://cert.valid.aoc.cat/*` (es el host que suele disparar el popup).

**PyAutoGUI:** ya no se usa (el worker asume autoselección de certificado vía policy). Si aparece un popup nativo, es señal de que falta algún dominio en la policy o el certificado no está instalado en el usuario correcto.

**Madrid/Cl@ve:** el popup puede venir de hosts intermedios (p.ej. `cas.madrid.es`, `pasarela.clave.gob.es`). Inclúyelos en la policy (ver `setup_worker_env.ps1` / `certificados-cmd.md`) y verifica en `edge://policy` que Edge los ha cargado.

### 1.3. Base de Datos
La base de datos SQLite se inicializa automáticamente al arrancar `worker.py` o usar `enqueue_task.py`. Se creará en `db/xaloc_database.db`.

## 2. Operación del Worker

### 2.1. Arrancar el Worker
El worker es un proceso que busca tareas pendientes en la base de datos y las ejecuta secuencialmente.

```bash
python worker.py
```
- El worker corre en bucle infinito.
- Usa un perfil de navegador persistente por site en `profiles/worker/<site_id>/`.
- Genera logs en consola y en `logs/worker.log`.
- Guarda screenshots de éxito/error en `screenshots/`.

Para detenerlo, usar `Ctrl+C`.

### 2.2. Encolar Tareas
Para añadir trabajo a la cola, usar el script `enqueue_task.py`.

**Sintaxis:**
```bash
python enqueue_task.py --site <SITE_ID> [--protocol <PROTOCOLO>] --payload <JSON_DATA>
```

**Ejemplos:**

1. **Insertar tarea pasando JSON como string:**
   ```bash
   python enqueue_task.py --site madrid --payload '{"plate_number": "1234BBB", "user_phone": "600111222"}'
   ```

2. **Insertar tarea desde archivo JSON:**
   ```bash
   python enqueue_task.py --site base_online --protocol P1 --payload datos_tramite.json
   ```

**Ejemplos listos para usar (modo prueba):** ver `worker-tasks/README.md` y los JSONs en `worker-tasks/`.

## 3. Monitorización y Logs

- **Logs del sistema:** `logs/worker.log`
- **Logs por sitio:** `logs/<site_id>.log`
- **Evidencia visual:** `screenshots/`
- **Estado de la cola:** Consultar la tabla `tramite_queue` en `db/xaloc_database.db` (usando cualquier cliente SQLite).

## 4. Notas Importantes

- **Modo Demo/Seguro:** El worker ejecuta todo el flujo pero **NO** realiza la firma final (botón "Firmar/Registrar" no se pulsa) para evitar registros reales durante pruebas/desarrollo, a menos que se modifique el código del flujo.
- **Perfil Persistente:** El perfil `profiles/worker` guarda cookies y sesiones. Si hay problemas de sesión corrupta, se puede borrar esa carpeta para forzar un inicio limpio.
