#!/usr/bin/env python3
"""
Create a minimal site scaffold + adapter scaffold for this repository.

This script only creates new files and does not patch existing integration files.
It prints the exact follow-up edits required to complete integration.
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


def pascal_case(site_id: str) -> str:
    return "".join(chunk.capitalize() for chunk in site_id.split("_") if chunk)


@dataclass
class FileSpec:
    path: Path
    content: str


def build_specs(repo_root: Path, site_id: str, display_name: str) -> list[FileSpec]:
    class_base = pascal_case(site_id)
    site_dir = repo_root / "sites" / site_id
    flows_dir = site_dir / "flows"
    adapter_path = repo_root / "sites" / "adapters" / f"{site_id}.py"

    config_class = f"{class_base}Config"
    target_class = f"{class_base}Target"
    controller_class = f"{class_base}Controller"
    automation_class = f"{class_base}Automation"
    adapter_class = f"{class_base}Adapter"

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

    def create_config(self, *, headless: bool) -> {config_class}:
        cfg = {config_class}()
        cfg.navegador.headless = bool(headless)
        return cfg

    def create_target(self, **kwargs) -> {target_class}:
        archivos = kwargs.get("archivos") or []
        return {target_class}(
            idRecurso=kwargs.get("idRecurso"),
            expediente=str(kwargs.get("expediente") or ""),
            archivos_adjuntos=[Path(str(p)) for p in archivos],
            payload=dict(kwargs),
            headless=bool(kwargs.get("headless", True)),
        )

    def map_data(self, data: dict) -> dict:
        return dict(data or {{}})


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

        shot = self.config.dir_screenshots / f"{site_id}_final.png"
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
    # TODO: implementar con pasos Playwright reales del organismo.
    _ = (config, datos)
    await page.wait_for_timeout(50)
    return page
'''
    adapter_py = f'''from __future__ import annotations

from typing import Any, Optional

from .site_adapter import SiteAdapter


class {adapter_class}(SiteAdapter):
    def __init__(self):
        super().__init__(site_id="{site_id}", priority=10)

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
        resource_repo: Any | None = None,
    ) -> list[dict]:
        # TODO: implementar query SQL Server / repo + filtros.
        _ = (config, conn_str, authenticated_user, limit, on_discard, resource_repo)
        return []

    async def build_payloads(
        self,
        candidates: list[dict],
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        # TODO: mapear campos SQL a payload del site.
        _ = on_discard
        return [dict(c) for c in candidates]
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
        FileSpec(adapter_path, adapter_py),
    ]


def write_files(specs: list[FileSpec], *, dry_run: bool, force: bool) -> tuple[list[Path], list[Path]]:
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
    class_base = pascal_case(site_id)
    automation_class = f"{class_base}Automation"
    adapter_class = f"{class_base}Adapter"
    print("\nManual integration edits required:")
    print("1) core/site_registry.py")
    print(f'   - add site_id="{site_id}" with automation_path "sites.{site_id}.automation:{automation_class}"')
    print(f'   - controller_path "sites.{site_id}.controller:get_controller"')
    print("2) sites/adapters/__init__.py")
    print(f"   - import {adapter_class} from .{site_id}")
    print(f'   - add "{adapter_class}" to __all__')
    print("3) services/brain_claim/app.py")
    print(f'   - import {adapter_class}')
    print(f'   - register "{site_id}": {adapter_class}() in self.adapters')
    print("4) organismo_config.json")
    print(f'   - add config block for site_id "{site_id}"')
    print("5) dashboard-frontend/app/gestion/page.tsx")
    print(f'   - add "{site_id}" to KNOWN_SITES if explicit UI listing is required')


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new Xaloc site + adapter.")
    parser.add_argument("--site-id", required=True, help="Snake_case site id (e.g. terrassa)")
    parser.add_argument("--display-name", default="", help="Human display name for controller")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument("--dry-run", action="store_true", help="Show files without writing")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    site_id = normalize_site_id(args.site_id)
    if not site_id:
        raise SystemExit("Invalid --site-id after normalization.")
    display_name = (args.display_name or "").strip() or pascal_case(site_id)
    repo_root = Path(args.repo_root).resolve()

    specs = build_specs(repo_root, site_id, display_name)
    created, skipped = write_files(specs, dry_run=bool(args.dry_run), force=bool(args.force))

    action = "Planned" if args.dry_run else "Created"
    print(f"{action} files ({len(created)}):")
    for path in created:
        print(f"  - {path}")
    if skipped:
        print(f"Skipped existing files ({len(skipped)}). Use --force to overwrite:")
        for path in skipped:
            print(f"  - {path}")

    print_followup(site_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
