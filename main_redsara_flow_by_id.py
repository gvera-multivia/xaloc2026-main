from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from core.process_launcher import setup_asyncio_policy
from sites.redsara.automation import RedsaraAutomation
from sites.redsara.controller import RedsaraController

from main_redsara_payload_by_id import _build_brain_like_payload, _fetch_resource_by_id

# Conexión SQL fija para ejecución local directa desde CMD (sin preparar variables antes).
SQLSERVER_DRIVER = "SQL Server"
SQLSERVER_SERVER = "BD-SERVER"
SQLSERVER_DATABASE = "MULTIVIA"
SQLSERVER_USERNAME = "Xvia-Grupo"
SQLSERVER_PASSWORD = "Xvia_Grupo_Multivia_20180806"
REDSARA_CERT_RULES_JSON = (
    '[{"pattern":"https://reg.redsara.es/*","filter":{"SUBJECT":{"CN":"__CERT_CN__"}}}]'
)


def _load_organism_code_from_json() -> str:
    json_path = Path(
        os.getenv(
            "REDSARA_ORGANISM_JSON_PATH",
            r"C:\Users\Guillem Vera\Desktop\redsara2026\ORGANISMOS_REDSARA.json",
        )
    )
    organism_key = (
        os.getenv("REDSARA_ORGANISM_KEY", "tribunal_economico_mostoles_madrid").strip().lower()
    )

    if not json_path.exists():
        raise FileNotFoundError(f"No existe el JSON de organismos: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    organismos = data.get("organismos") or []
    if not isinstance(organismos, list):
        raise ValueError(f"Formato invalido en {json_path}: 'organismos' debe ser una lista")

    for item in organismos:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        code = str(item.get("codigo") or "").strip()
        if key == organism_key:
            if not code:
                raise ValueError(f"El organismo '{organism_key}' no tiene 'codigo' en {json_path}")
            return code

    raise KeyError(f"No existe key='{organism_key}' en {json_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta flujo REDSARA completo leyendo payload desde SQL por idRecurso.")
    parser.add_argument("--id", type=int, default=91216, help="idRecurso en SQL Server")
    args = parser.parse_args()

    os.environ["SQLSERVER_DRIVER"] = SQLSERVER_DRIVER
    os.environ["SQLSERVER_SERVER"] = SQLSERVER_SERVER
    os.environ["SQLSERVER_DATABASE"] = SQLSERVER_DATABASE
    os.environ["SQLSERVER_USERNAME"] = SQLSERVER_USERNAME
    os.environ["SQLSERVER_PASSWORD"] = SQLSERVER_PASSWORD

    # Acotar auto-selección de certificado solo a REDSARA para evitar command-line excesiva.
    os.environ["XALOC_CERT_AUTOSELECT_RULES_JSON"] = REDSARA_CERT_RULES_JSON
    os.environ["XALOC_CERT_AUTOSELECT_PATTERN"] = "https://reg.redsara.es/*"

    os.environ.setdefault("XALOC_KEEP_BROWSER_OPEN", "1")
    os.environ.setdefault("XALOC_KEEP_TAB_OPEN", "1")
    os.environ.setdefault("XALOC_HEADLESS", "0")

    row = _fetch_resource_by_id(args.id)
    payload = _build_brain_like_payload(row)
    payload["destination_organism_code"] = _load_organism_code_from_json()

    controller = RedsaraController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    config = controller.create_config(headless=False)
    config.navegador.perfil_path = Path("profiles/worker_redsara").absolute()

    try:
        async with RedsaraAutomation(config) as bot:
            screenshot = await bot.ejecutar_flujo_completo(target)
            print(f"[OK] Flujo REDSARA completado para idRecurso={args.id}. Screenshot: {screenshot}")
    except Exception as exc:
        print(f"[ERROR] Flujo REDSARA falló para idRecurso={args.id}: {exc}")
    finally:
        print("[INFO] Navegador mantenido abierto. Pulsa Ctrl+C para salir.")
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    setup_asyncio_policy()
    asyncio.run(main())
