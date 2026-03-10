#!/usr/bin/env python3
"""
Generate a standalone Playwright site scaffold and a local smoke runner:
- sites/<site_id>/*
- main_<site_id>_payload_by_id.py

This script intentionally avoids worker/brain integration.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


def normalize_site_id(raw: str) -> str:
    value = (raw or "").strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_") if part)


@dataclass
class FileSpec:
    path: Path
    content: str


def build_specs(repo_root: Path, site_id: str, display_name: str) -> list[FileSpec]:
    base = pascal_case(site_id)
    config_class = f"{base}Config"
    target_class = f"{base}Target"
    controller_class = f"{base}Controller"
    automation_class = f"{base}Automation"

    site_dir = repo_root / "sites" / site_id
    flows_dir = site_dir / "flows"
    main_runner = repo_root / f"main_{site_id}_payload_by_id.py"

    init_site = '"""Site package."""\n'
    init_flows = (
        '"""Flow modules for this site."""\n\n'
        "from .login import run_login\n"
        "from .formulario import run_formulario\n"
        "from .documentos import run_documentos\n"
        "from .confirmacion import run_confirmacion\n"
        "\n"
        '__all__ = ["run_login", "run_formulario", "run_documentos", "run_confirmacion"]\n'
    )

    config_py = f'''from __future__ import annotations

from dataclasses import dataclass

from core.base_config import BaseConfig


@dataclass
class {config_class}(BaseConfig):
    site_id: str = "{site_id}"
    url_base: str = "https://example.local/{site_id}"
    default_timeout: int = 30000
    navigation_timeout: int = 60000
'''

    data_models_py = f'''from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class {target_class}:
    idRecurso: int | None = None
    expediente: str = ""
    archivos_adjuntos: list[Path] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    headless: bool = True
'''

    controller_py = f'''from __future__ import annotations

from pathlib import Path

from .config import {config_class}
from .data_models import {target_class}


class {controller_class}:
    site_id = "{site_id}"
    display_name = "{display_name}"

    def create_config(self, *, headless: bool):
        cfg = {config_class}()
        cfg.navegador.headless = bool(headless)
        return cfg

    def map_data(self, data: dict) -> dict:
        return dict(data or {{}})

    def create_target(self, **kwargs) -> {target_class}:
        archivos = kwargs.get("archivos") or []
        return {target_class}(
            idRecurso=kwargs.get("idRecurso"),
            expediente=str(kwargs.get("expediente") or ""),
            archivos_adjuntos=[Path(str(p)) for p in archivos],
            payload=dict(kwargs),
            headless=bool(kwargs.get("headless", True)),
        )


def get_controller() -> {controller_class}:
    return {controller_class}()
'''

    automation_py = f'''from __future__ import annotations

from pathlib import Path

from core.base_automation import BaseAutomation
from .config import {config_class}
from .data_models import {target_class}
from .flows import run_login, run_formulario, run_documentos, run_confirmacion


class {automation_class}(BaseAutomation):
    def __init__(self, config: {config_class}):
        super().__init__(config)
        self.config = config

    async def ejecutar_flujo_completo(self, datos: {target_class}) -> str:
        if not self.page:
            raise RuntimeError("Automation no inicializada (usar 'async with').")

        await run_login(self.page, self.config, datos)
        await run_formulario(self.page, self.config, datos)
        await run_documentos(self.page, self.config, datos)
        await run_confirmacion(self.page, self.config, datos)

        shot = self.config.dir_screenshots / f"{site_id}_standalone.png"
        await self.page.screenshot(path=shot, full_page=True)
        return str(Path(shot))
'''

    flow_template = '''from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..config import {config_class}
    from ..data_models import {target_class}


async def {fn_name}(page: "Page", config: "{config_class}", datos: "{target_class}") -> "Page":
    _ = (config, datos)
    # TODO: implementar paso real del organismo.
    await page.wait_for_timeout(50)
    return page
'''

    main_py = f'''from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyodbc

from core.sqlserver_utils import build_sqlserver_connection_string
from core.worker_execution.browser_executor import execute_browser_flow
from sites.{site_id}.controller import {controller_class}


SQL_BY_ID = """
SELECT TOP 1
    rs.idRecurso,
    rs.idExp,
    rs.Expedient
FROM Recursos.RecursosExp rs
WHERE rs.idRecurso = ?
"""


def fetch_resource_by_id(id_recurso: int) -> dict[str, Any]:
    conn_str = build_sqlserver_connection_string()
    conn = pyodbc.connect(conn_str)
    try:
        cur = conn.cursor()
        cur.execute(SQL_BY_ID, id_recurso)
        row = cur.fetchone()
        if not row:
            raise LookupError(f"No existe idRecurso={{id_recurso}}")
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def build_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    # TODO: mapear SQL -> payload real del site.
    return {{
        "idRecurso": row.get("idRecurso"),
        "idExp": row.get("idExp"),
        "expediente": str(row.get("Expedient") or "").strip(),
        "archivos": [],
    }}


async def run_flow(payload: dict[str, Any]) -> dict[str, Any]:
    outcome = await execute_browser_flow(
        site_id="{site_id}",
        protocol=None,
        payload=payload,
        archivos_para_subir=[],
    )
    return {{
        "success": bool(outcome.success),
        "error": outcome.error,
        "screenshot": outcome.screenshot,
        "payload_updates": outcome.payload_updates,
    }}


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone smoke test for {site_id}.")
    parser.add_argument("--id", type=int, required=True, help="idRecurso en SQL Server")
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local")
    args = parser.parse_args()

    row = fetch_resource_by_id(args.id)
    payload = build_payload_from_row(row)

    controller = {controller_class}()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / "{site_id}_raw_{{}}.json".format(args.id)
    payload_path = out / "{site_id}_payload_{{}}.json".format(args.id)
    mapped_path = out / "{site_id}_mapped_{{}}.json".format(args.id)
    raw_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mapped_path.write_text(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] SQL raw: {{raw_path}}")
    print(f"[OK] payload: {{payload_path}}")
    print(f"[OK] mapped target: {{mapped_path}}")

    if args.dump_only and not args.run_flow:
        return

    if args.run_flow:
        result = asyncio.run(run_flow(payload))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
'''

    return [
        FileSpec(site_dir / "__init__.py", init_site),
        FileSpec(flows_dir / "__init__.py", init_flows),
        FileSpec(site_dir / "config.py", config_py),
        FileSpec(site_dir / "data_models.py", data_models_py),
        FileSpec(site_dir / "controller.py", controller_py),
        FileSpec(site_dir / "automation.py", automation_py),
        FileSpec(
            flows_dir / "login.py",
            flow_template.format(
                fn_name="run_login",
                config_class=config_class,
                target_class=target_class,
            ),
        ),
        FileSpec(
            flows_dir / "formulario.py",
            flow_template.format(
                fn_name="run_formulario",
                config_class=config_class,
                target_class=target_class,
            ),
        ),
        FileSpec(
            flows_dir / "documentos.py",
            flow_template.format(
                fn_name="run_documentos",
                config_class=config_class,
                target_class=target_class,
            ),
        ),
        FileSpec(
            flows_dir / "confirmacion.py",
            flow_template.format(
                fn_name="run_confirmacion",
                config_class=config_class,
                target_class=target_class,
            ),
        ),
        FileSpec(main_runner, main_py),
    ]


def write_specs(specs: list[FileSpec], *, dry_run: bool, force: bool) -> tuple[list[Path], list[Path]]:
    created: list[Path] = []
    skipped: list[Path] = []
    for spec in specs:
        if spec.path.exists() and not force:
            skipped.append(spec.path)
            continue
        if dry_run:
            created.append(spec.path)
            continue
        spec.path.parent.mkdir(parents=True, exist_ok=True)
        spec.path.write_text(spec.content, encoding="utf-8")
        created.append(spec.path)
    return created, skipped


def print_followup(site_id: str) -> None:
    base = pascal_case(site_id)
    print("\nFollow-up edits required (standalone):")
    print("1) core/site_registry.py")
    print(f'   - add "{site_id}" entry:')
    print(f'     automation_path="sites.{site_id}.automation:{base}Automation"')
    print(f'     controller_path="sites.{site_id}.controller:get_controller"')
    print("2) main_<site> script")
    print("   - complete SQL_BY_ID and build_payload_from_row")
    print("3) flows")
    print("   - implement real Playwright logic in flows/*.py")
    print("4) run smoke test")
    print(f"   - python main_{site_id}_payload_by_id.py --id <idRecurso> --dump-only")
    print(f"   - python main_{site_id}_payload_by_id.py --id <idRecurso> --run-flow")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate standalone site + local smoke runner.")
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--display-name", default="")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    site_id = normalize_site_id(args.site_id)
    if not site_id:
        raise SystemExit("Invalid --site-id")
    display_name = (args.display_name or "").strip() or pascal_case(site_id)
    repo_root = Path(args.repo_root).resolve()

    specs = build_specs(repo_root, site_id, display_name)
    created, skipped = write_specs(specs, dry_run=bool(args.dry_run), force=bool(args.force))

    action = "Planned" if args.dry_run else "Created"
    print(f"{action} files ({len(created)}):")
    for p in created:
        print(f"  - {p}")
    if skipped:
        print(f"Skipped existing files ({len(skipped)}). Use --force to overwrite:")
        for p in skipped:
            print(f"  - {p}")
    print_followup(site_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
