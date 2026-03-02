from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from core.site_registry import get_site, get_site_controller


def _load_payload(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"No existe payload: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("El payload debe ser un objeto JSON.")
    return data


def _to_bool(value: str | int | bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


async def run_task(payload_path: Path, headless: bool) -> str:
    site_id = "redsara"
    payload = _load_payload(payload_path)

    controller = get_site_controller(site_id)
    automation_cls = get_site(site_id)

    config = controller.create_config(headless=headless)
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    async with automation_cls(config) as bot:
        screenshot_path = await bot.ejecutar_flujo_completo(target)

    return str(screenshot_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prueba local del site RedSARA (Playwright/Python).",
    )
    parser.add_argument(
        "--payload-json",
        required=True,
        help="Ruta al JSON con los datos del trámite.",
    )
    parser.add_argument(
        "--headless",
        default="0",
        help="0/1 o false/true.",
    )
    args = parser.parse_args()

    payload_path = Path(args.payload_json).expanduser().resolve()
    headless = _to_bool(args.headless)

    result_path = asyncio.run(run_task(payload_path=payload_path, headless=headless))
    print(json.dumps({"ok": True, "site_id": "redsara", "screenshot": result_path}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
