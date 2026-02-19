from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _resolve_base_path(cli_path: str | None) -> Path:
    if cli_path:
        return Path(cli_path).expanduser()
    env_path = (os.getenv("CLIENT_DOCS_BASE_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return Path("/mnt/clientes")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test de lectura/escritura en carpeta de clientes.")
    parser.add_argument(
        "--path",
        default=None,
        help="Ruta base a probar. Si no se informa, usa CLIENT_DOCS_BASE_PATH o /mnt/clientes.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="No borra el archivo de prueba al finalizar.",
    )
    args = parser.parse_args()

    base_path = _resolve_base_path(args.path)
    probe_dir = base_path / ".xaloc_smoke"
    probe_file = probe_dir / f"rw_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.txt"
    probe_payload = f"xaloc-smoke-ok:{datetime.now(timezone.utc).isoformat()}\n"

    print(f"[smoke] base_path={base_path}")
    print(f"[smoke] probe_file={probe_file}")

    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe_file.write_text(probe_payload, encoding="utf-8")
        read_back = probe_file.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[smoke] ERROR: fallo en escritura/lectura: {exc}")
        return 2

    if read_back != probe_payload:
        print("[smoke] ERROR: el contenido leido no coincide con el escrito.")
        return 3

    print("[smoke] OK: escritura y lectura correctas.")

    if args.keep:
        print("[smoke] keep=1, se conserva el archivo de prueba.")
        return 0

    try:
        probe_file.unlink(missing_ok=True)
    except Exception as exc:
        print(f"[smoke] WARNING: no se pudo borrar el archivo de prueba: {exc}")
        return 4

    print("[smoke] Limpieza completada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
