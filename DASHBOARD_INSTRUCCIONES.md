# Dashboard Realtime: Instrucciones de uso

Este documento explica como arrancar y usar el dashboard del sistema en local y en red WiFi.

## 1. Requisitos

- Python con dependencias instaladas (`requirements.txt`).
- Base SQLite accesible (por defecto: `db/xaloc_database.db`).
- PostgreSQL accesible para historico (si quieres ver incidencias/exitos), usando `REPORT_PG_DSN`.

Instalacion:

```powershell
pip install -r requirements.txt
```

## 2. Que muestra cada pantalla

- `http://<host>:<port>/historico`
  - Lee de PostgreSQL:
    - `realtime_incidents` (incidencias)
    - `realtime_task_results` con `status='success'` (exitos)
- `http://<host>:<port>/colas`
  - Lee de SQLite:
    - `tramite_queue` (si `QUEUE_BACKEND=sqlite`)
    - `job_runs` (si `QUEUE_BACKEND=redis`)

## 3. Variables de entorno recomendadas

- `SQLITE_DB_PATH` (opcional): ruta al sqlite local.
- `REPORT_PG_DSN` (recomendada para historico):
  - Ejemplo:
  - `postgresql://usuario:password@host:5432/base`
- `QUEUE_BACKEND` (`sqlite` o `redis`).
- `DASHBOARD_PORT_START` y `DASHBOARD_PORT_END` (opcional, rango de puertos libres).

Ejemplo PowerShell:

```powershell
$env:SQLITE_DB_PATH="db/xaloc_database.db"
$env:REPORT_PG_DSN="postgresql://usuario:password@localhost:5432/xaloc"
$env:QUEUE_BACKEND="sqlite"
```

## 4. Arrancar en localhost (solo tu PC)

```powershell
python run_dashboard.py
```

El script busca un puerto libre automaticamente (por defecto entre `8787` y `8999`) y muestra la URL.

## 5. Arrancar para toda la WiFi (otros dispositivos)

Por defecto `run_dashboard.py` usa `127.0.0.1` (solo local). Para exponerlo en tu LAN, arrancalo en `0.0.0.0`:

```powershell
python -c "import os,uvicorn; os.environ.setdefault('DASHBOARD_PORT_START','8787'); os.environ.setdefault('DASHBOARD_PORT_END','8999'); import run_dashboard; p=run_dashboard.find_free_port(int(os.environ['DASHBOARD_PORT_START']),int(os.environ['DASHBOARD_PORT_END'])); print(f'Dashboard listening on http://0.0.0.0:{p}'); uvicorn.run('dashboard_api:app', host='0.0.0.0', port=p, reload=False)"
```

Despues entra desde otro equipo de la red en:

- `http://<IP_WIFI_DE_TU_PC>:<puerto>/historico`
- `http://<IP_WIFI_DE_TU_PC>:<puerto>/colas`

Para ver tu IP WiFi en Windows:

```powershell
ipconfig
```

Busca `Dirección IPv4` del adaptador WiFi.

## 6. Firewall de Windows (si no abre desde otro equipo)

Permite el puerto TCP usado por el dashboard:

```powershell
netsh advfirewall firewall add rule name="Xaloc Dashboard" dir=in action=allow protocol=TCP localport=<puerto>
```

Sustituye `<puerto>` por el que imprime el arranque.

## 7. API disponible

- `GET /api/history/days`
- `GET /api/history/incidents`
- `GET /api/history/successes`
- `GET /api/queue/days`
- `GET /api/queue/current`

Parametros comunes:

- `day=YYYY-MM-DD`
- `page=<n>`
- `page_size=<n>`

## 8. Problemas comunes

- Historico vacio:
  - `REPORT_PG_DSN` no definido o sin conectividad.
  - Tablas realtime no creadas en PostgreSQL.
- Colas vacias:
  - No hay jobs en `pending/processing` para ese dia.
  - `QUEUE_BACKEND` no coincide con tu backend real.
- Error al arrancar:
  - Dependencias faltantes (`fastapi`, `uvicorn`, `psycopg[binary]`).

## 9. Comprobacion rapida

1. Arranca `python run_dashboard.py`.
2. Abre `/historico` y `/colas`.
3. Cambia de dia con las pills y pulsa `Refresh`.
4. Verifica que los totales cambian segun datos reales.
