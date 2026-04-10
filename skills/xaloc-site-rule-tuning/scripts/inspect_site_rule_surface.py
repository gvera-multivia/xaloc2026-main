from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ORGANISMO_CONFIG_PATH = ROOT / "organismo_config.json"
ADAPTERS_DIR = ROOT / "sites" / "adapters"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_json_configs(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("configs")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _find_json_config(site_id: str) -> dict[str, Any] | None:
    for item in _load_json_configs(ORGANISMO_CONFIG_PATH):
        if str(item.get("site_id") or "").strip() == site_id:
            return item
    return None


def _read_pg_config(site_id: str) -> dict[str, Any] | None:
    try:
        from core.pg_admin_store import PgAdminStore
    except Exception as exc:
        logging.warning("No se pudo importar PgAdminStore: %s", exc)
        return None

    try:
        return PgAdminStore.from_env(logger=logging.getLogger("inspect_site_rule_surface")).get_organismo_config(site_id)
    except Exception as exc:
        logging.warning("No se pudo leer organismo_config desde PG: %s", exc)
        return None


def _adapter_path(site_id: str) -> Path:
    return ADAPTERS_DIR / f"{site_id}.py"


def _extract_signal_lines(path: Path) -> list[str]:
    if not path.exists():
        return []

    needles = (
        "REGEX_DISCARDED",
        "SITE_RULE_DISCARDED",
        "NOT_PROCESSABLE",
        "on_discard",
        "regex_expediente",
        "validate_expediente",
        "query_organisme",
        "filtro_texp",
    )
    out: list[str] = []
    for idx, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if any(needle in line for needle in needles):
            out.append(f"{idx}: {line}")
    return out[:40]


def _print_section(title: str, value: Any) -> None:
    print(f"\n## {title}")
    if value is None:
        print("(none)")
        return
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    print(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspeccion read-only de reglas/config de un site Xaloc.")
    parser.add_argument("--site-id", required=True, help="site_id a inspeccionar")
    parser.add_argument("--show-pg", action="store_true", help="Tambien lee la config activa desde PostgreSQL")
    args = parser.parse_args()

    site_id = str(args.site_id).strip()
    if not site_id:
        raise SystemExit("site_id vacio")

    json_cfg = _find_json_config(site_id)
    adapter = _adapter_path(site_id)

    print(f"# Site rule surface for {site_id}")
    _print_section("JSON config", json_cfg)
    _print_section("Adapter path", adapter if adapter.exists() else f"missing: {adapter}")
    _print_section("Adapter signal lines", _extract_signal_lines(adapter))

    if args.show_pg:
        _print_section("PostgreSQL config", _read_pg_config(site_id))

    print("\n## Suggested checks")
    print("- Revisar si el problema vive en config base o en regla final del adapter.")
    print("- Confirmar que JSON y PG no divergen si el entorno esta corriendo con PostgreSQL activa.")
    print("- Validar incidencias y tests del site tras cualquier cambio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
