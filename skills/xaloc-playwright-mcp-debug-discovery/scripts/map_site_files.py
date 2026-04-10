from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _site_dir(site_id: str) -> Path:
    return ROOT / "sites" / site_id


def _adapter_file(site_id: str) -> Path:
    return ROOT / "sites" / "adapters" / f"{site_id}.py"


def _main_script(site_id: str) -> Path:
    return ROOT / f"main_{site_id}_payload_by_id.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Mapa rapido entre un site y sus archivos clave para debug con Playwright MCP.")
    parser.add_argument("--site-id", required=True, help="site_id a inspeccionar")
    args = parser.parse_args()

    site_id = str(args.site_id).strip()
    site_dir = _site_dir(site_id)
    flows_dir = site_dir / "flows"

    payload = {
        "site_id": site_id,
        "site_dir": str(site_dir),
        "exists": site_dir.exists(),
        "core_files": {
            "config": str(site_dir / "config.py"),
            "data_models": str(site_dir / "data_models.py"),
            "controller": str(site_dir / "controller.py"),
            "automation": str(site_dir / "automation.py"),
            "adapter": str(_adapter_file(site_id)),
            "standalone_main": str(_main_script(site_id)),
        },
        "flows": sorted(str(path) for path in flows_dir.glob("*.py")) if flows_dir.exists() else [],
        "notes": [
            "login roto suele vivir en flows/login.py o config.py",
            "campos/formato rotos suelen vivir en controller.py o flows/formulario.py",
            "adjuntos/firma en flows/documentos.py",
            "cierre/justificante en flows/confirmacion.py",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
