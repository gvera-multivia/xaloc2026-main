# Worker tasks (modo prueba)

Payloads JSON de ejemplo para encolar tareas con `enqueue_task.py`.

## Guía de parámetros

- Referencia completa de parámetros por web: `worker-tasks/PARAMETROS.md`.

## Previsualizar tareas desde SQL Server (a CSV)

1) Edita `sync_sqlserver_config.json` con tus credenciales (no se sube al repo; está en `.gitignore`).
2) Ejecuta el preview interactivo:
   - `python sync_sqlserver_preview_to_csv.py`
3) Revisa el CSV generado (por defecto `out/sync_preview.csv`).

Notas:

- En tu BD, `rs.FaseProcedimiento` suele ser un tipo (`denuncia`, `apremio`, `embargo`, `sancion`, `identificacion`), no “PENDIENTE”. Si quieres filtrar, pon `"fase": "denuncia"` en el config; si lo dejas vacío, no filtra.

## Comandos

- BASE On-line (P1):
  - `python enqueue_task.py --site base_online --protocol P1 --payload worker-tasks/base_online_p1.json`
- BASE On-line (P2):
  - `python enqueue_task.py --site base_online --protocol P2 --payload worker-tasks/base_online_p2.json`
- BASE On-line (P3):
  - `python enqueue_task.py --site base_online --protocol P3 --payload worker-tasks/base_online_p3.json`
- Madrid:
  - `python enqueue_task.py --site madrid --payload worker-tasks/madrid.json`
- Xaloc Girona:
  - `python enqueue_task.py --site xaloc_girona --payload worker-tasks/xaloc_girona.json`
- Selva:
  - `python enqueue_task.py --site selva --payload worker-tasks/selva.json`


## Nota

- Los campos están pensados para funcionar con los `map_data()` de cada `controller.py` y los defaults de `create_demo_data()`.
- `archivos` son rutas relativas dentro del repo (se usan PDFs de `pdfs-prueba/`).

