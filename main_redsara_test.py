from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from core.process_launcher import setup_asyncio_policy
from sites.redsara.automation import RedsaraAutomation
from sites.redsara.controller import RedsaraController

# Payload de prueba para REDSARA (Paso 1).
PAYLOAD = {
    "represented_street_type": "CALLE",
    "represented_address": "CALLE MAYOR 1",
    "represented_province": "MADRID",
    "represented_city": "MADRID",
    "represented_zip": "28013",
    "represented_phone": "600123123",
    "represented_email": "test+redsara@xvia.app",
    "interested_doc_type": "NIF",
    "interested_doc_number": "12345678Z",
    "interested_name": "JUAN",
    "interested_surname1": "PEREZ",
    "interested_surname2": "GARCIA",
    "interested_street_type": "CALLE",
    "interested_address": "CALLE ALCALA 10",
    "interested_province": "MADRID",
    "interested_city": "MADRID",
    "interested_zip": "28014",
    "interested_phone": "600123123",
    "interested_email": "test+redsara@xvia.app",
    "email_alert": True,
    "subject": "Prueba Redsara asunto",
    "exposes": "Expone de prueba automatizada.",
    "solicit": "Solicita de prueba automatizada.",
}


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
    # Mantener ventana y pestaña abiertas al terminar (modo prueba).
    os.environ["XALOC_KEEP_BROWSER_OPEN"] = "1"
    os.environ["XALOC_KEEP_TAB_OPEN"] = "1"
    os.environ["XALOC_HEADLESS"] = "0"

    controller = RedsaraController()
    config = controller.create_config(headless=False)
    config.navegador.perfil_path = Path("profiles/worker").absolute()

    payload = dict(PAYLOAD)
    payload["destination_organism_code"] = _load_organism_code_from_json()

    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    try:
        async with RedsaraAutomation(config) as bot:
            screenshot = await bot.ejecutar_flujo_completo(target)
            print(f"[OK] Flujo REDSARA completado. Screenshot: {screenshot}")
    except Exception as exc:
        print(f"[ERROR] Flujo REDSARA falló: {exc}")
    finally:
        print("[INFO] Navegador mantenido abierto. Pulsa Ctrl+C para salir.")
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    setup_asyncio_policy()
    asyncio.run(main())
