# Fase 1: Aislamiento de tmp por job

## Problema actual

`task_orchestrator.py` linea 27 define `TMP_ROOT = Path("tmp")`.

La funcion `_cleanup_tmp_workspace()` (lineas 370-393) borra **todo** lo que hay dentro de `tmp/` al finalizar cada job:

```python
for child in list(root.iterdir()):
    if child.is_dir():
        shutil.rmtree(child, ignore_errors=True)
    else:
        child.unlink(missing_ok=True)
```

Con 4 workers en paralelo, el worker-1 terminando su job borra los archivos que worker-2 todavia necesita.

`document_fetcher.py` linea 13 tambien usa ruta fija: `DOWNLOAD_DIR = Path("tmp/downloads")`.

## Solucion: workspace por job_id

### 1. Cambiar TMP_ROOT a funcion

En `task_orchestrator.py`:

```python
# Antes
TMP_ROOT = Path("tmp")

# Despues
TMP_ROOT = Path("tmp")

def _job_workspace(job_id: str | int | None) -> Path:
    """Devuelve tmp/<job_id> si aislamiento activo, o tmp/ si no."""
    if not _berserker_enabled():
        return TMP_ROOT
    safe_id = str(job_id or "unknown").strip()
    safe_id = "".join(ch for ch in safe_id if ch.isalnum() or ch in ("-", "_")) or "unknown"
    ws = TMP_ROOT / safe_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws

def _berserker_enabled() -> bool:
    return os.getenv("BERSERKER_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
```

### 2. Pasar workspace a download_document_and_attachments

En `document_fetcher.py`, cambiar:

```python
# Antes
DOWNLOAD_DIR = Path("tmp/downloads")

# Despues
def _download_dir(workspace: Path | None = None) -> Path:
    base = workspace or Path("tmp")
    d = base / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

Y en `process_task()`:

```python
workspace = _job_workspace(task_id or payload.get("idRecurso"))
archivos_para_subir = await download_document_and_attachments(
    payload=payload,
    auth_session=auth_session,
    download_dir=workspace / "downloads",  # nuevo parametro opcional
)
```

### 3. Cambiar _cleanup_tmp_workspace para limpiar solo el workspace del job

```python
def _cleanup_tmp_workspace(workspace: Path | None = None) -> None:
    target = workspace or TMP_ROOT
    try:
        root = target.resolve()
    except Exception:
        root = target

    if not root.exists():
        return

    # Safety: nunca borrar fuera de .../tmp/...
    try:
        if TMP_ROOT.resolve() not in root.resolve().parents and root.resolve() != TMP_ROOT.resolve():
            logger.warning("Se omite limpieza por ruta insegura: %s", root)
            return
    except Exception:
        return

    if workspace and workspace != TMP_ROOT:
        # Modo aislado: borrar la carpeta entera del job
        shutil.rmtree(root, ignore_errors=True)
    else:
        # Modo legacy: borrar contenido de tmp/ (comportamiento actual)
        for child in list(root.iterdir()):
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("No se pudo limpiar temporal %s: %s", child, exc)
```

### 4. Actualizar bloque finally en process_task

```python
finally:
    _cleanup_tmp_workspace(workspace)
    logger.info("Finalizando procesamiento de tarea %s", task_label)
```

## Ficheros a modificar

| Fichero | Cambio |
|---------|--------|
| `core/worker_execution/task_orchestrator.py` | Workspace por job, cleanup aislado |
| `core/worker_execution/document_fetcher.py` | Parametro download_dir opcional |

## Test de validacion

1. Sin `BERSERKER_MODE`: el comportamiento es identico al actual (test de regresion).
2. Con `BERSERKER_MODE=1`: dos `process_task` concurrentes con job_id distintos NO se pisan archivos en tmp.
3. Verificar que `tmp/<job_id>/` se borra completamente tras cada job.
4. Verificar que `tmp/<job_id>/downloads/` contiene los archivos descargados.

## Riesgo residual

- Si algun site escribe directamente a `tmp/` sin usar el workspace, se rompe el aislamiento. Buscar con `grep -r "tmp/" sites/` para auditar.
