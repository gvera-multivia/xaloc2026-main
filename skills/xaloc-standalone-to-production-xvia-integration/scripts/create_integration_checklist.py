#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path


def build_markdown(site_id: str, main_script: str) -> str:
    return f"""# Checklist integracion productiva: {site_id}

## Input

- Site ID: `{site_id}`
- Script standalone: `{main_script}`

## 1) Site runtime

- [ ] Confirmar `sites/{site_id}/` completo (`config.py`, `controller.py`, `automation.py`, `flows/`)
- [ ] Registrar `site_id` en `core/site_registry.py`
- [ ] Validar compile: `python -m py_compile sites/{site_id}/automation.py`

## 2) Adapter + brain claim

- [ ] Crear `sites/adapters/{site_id}.py` (`fetch_candidates`, `build_payloads`)
- [ ] Exportar adapter en `sites/adapters/__init__.py`
- [ ] Registrar adapter en `services/brain_claim/app.py` (`self.adapters`)
- [ ] Anadir bloque en `organismo_config.json`

## 3) XVIA: organismo sancionador y expedientes validos

- [ ] Definir reglas por organismo (`like_patterns`)
- [ ] Definir lista de expedientes validos (`regex_list`)
- [ ] Registrar descartes trazables con `on_discard`

## 4) Worker confirmacion

- [ ] Verificar `idRecurso` en payload final
- [ ] Verificar confirmacion via `mark_resource_complete` en `core/worker_execution/task_orchestrator.py`

## 5) Dashboard

- [ ] Verificar aparicion en `/api/config`
- [ ] Actualizar `dashboard-frontend/app/gestion/page.tsx` (`KNOWN_SITES`) si aplica

## 6) Certificado login

- [ ] Actualizar `core/base_automation.py` (patterns + origins)
- [ ] Actualizar `infra/docker/playwright-runner-entrypoint.sh` (`default_patterns`)
- [ ] Actualizar `url-cert-config.bat` (reglas Windows)

## 7) Validacion final

- [ ] Compilar todos los archivos tocados
- [ ] Ejecutar smoke por `idRecurso` real
- [ ] Confirmar ciclo completo: claim -> publish -> worker -> completado XVIA
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera checklist markdown para integrar un site standalone en produccion."
    )
    parser.add_argument("--site-id", required=True, help="Identificador del site (snake_case).")
    parser.add_argument(
        "--main-script",
        default="",
        help="Ruta o nombre del script standalone (ej: main_terrassa_payload_by_id.py).",
    )
    parser.add_argument(
        "--out",
        default="tmp",
        help="Directorio de salida para el .md (default: tmp).",
    )
    args = parser.parse_args()

    site_id = str(args.site_id).strip()
    if not site_id:
        raise SystemExit("site_id vacio")

    main_script = str(args.main_script).strip() or f"main_{site_id}_payload_by_id.py"
    out_dir = Path(str(args.out).strip() or "tmp")
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"integration_checklist_{site_id}.md"
    out_path.write_text(build_markdown(site_id=site_id, main_script=main_script), encoding="utf-8")
    print(f"[OK] Checklist generada: {out_path}")


if __name__ == "__main__":
    main()
