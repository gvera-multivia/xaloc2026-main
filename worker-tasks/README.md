# Worker tasks (modo prueba)

Payloads JSON de ejemplo para encolar tareas con `enqueue_task.py`.

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

## Nota

- Los campos están pensados para funcionar con los `map_data()` de cada `controller.py` y los defaults de `create_demo_data()`.
- `archivos` son rutas relativas dentro del repo (se usan PDFs de `pdfs-prueba/`).

