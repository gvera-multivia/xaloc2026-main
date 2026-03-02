from __future__ import annotations

import asyncio
import os
from pathlib import Path

from core.process_launcher import setup_asyncio_policy
from sites.redsara.automation import RedsaraAutomation
from sites.redsara.controller import RedsaraController
from sites.redsara.flows import ejecutar_login_redsara, rellenar_paso1_datos_solicitante_redsara

BASE_PAYLOAD = {
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
}

SELECT_HEURISTIC_CASES = [
    {},
    {"represented_street_type": "calle", "interested_street_type": "calle"},
    {"represented_street_type": "C/"},
    {"represented_street_type": "Avenida", "interested_street_type": "Avenida"},
    {"represented_street_type": "avda", "interested_street_type": "avda"},
    {"represented_street_type": "plaza", "interested_street_type": "plaza"},
    {"represented_province": "madrid", "interested_province": "madrid"},
    {"represented_city": "Madrid", "interested_city": "Madrid"},
    {"represented_city": "madr", "interested_city": "madr"},
    {"interested_doc_type": "nif"},
    {"interested_doc_type": "N.I.F."},
    {"represented_province": "MADRÍD", "interested_province": "MADRÍD"},
    {"represented_city": "MADRÍD", "interested_city": "MADRÍD"},
    {"represented_street_type": "cl", "interested_street_type": "cl"},
    {"represented_street_type": "Calle ", "interested_street_type": " Calle"},
]


async def main() -> None:
    os.environ["XALOC_KEEP_BROWSER_OPEN"] = "1"
    os.environ["XALOC_KEEP_TAB_OPEN"] = "1"
    os.environ["XALOC_HEADLESS"] = "0"

    controller = RedsaraController()
    config = controller.create_config(headless=False)
    config.navegador.perfil_path = Path("profiles/worker").absolute()

    results: list[tuple[int, bool, str]] = []

    async with RedsaraAutomation(config) as bot:
        if not bot.page:
            raise RuntimeError("No se pudo inicializar pagina Playwright.")

        bot.page = await ejecutar_login_redsara(bot.page, config)

        for idx, overrides in enumerate(SELECT_HEURISTIC_CASES, start=1):
            payload = dict(BASE_PAYLOAD)
            payload.update(overrides)

            mapped = controller.map_data(payload)
            target = controller.create_target(**mapped)

            try:
                await bot.page.goto(config.url_nuevo_registro, wait_until="domcontentloaded", timeout=60000)
                await bot.page.locator(config.selectors.step1_heading).first.wait_for(state="visible", timeout=30000)
                await rellenar_paso1_datos_solicitante_redsara(bot.page, config, target)

                shot = config.dir_screenshots / f"redsara_step1_case_{idx:02d}.png"
                await bot.page.screenshot(path=shot, full_page=True)
                print(f"[OK] Case {idx:02d}/15 completado: {overrides}")
                results.append((idx, True, str(overrides)))
            except Exception as exc:
                print(f"[FAIL] Case {idx:02d}/15 fallo: {overrides} -> {exc}")
                results.append((idx, False, f"{overrides} :: {exc}"))

    ok = sum(1 for _, passed, _ in results if passed)
    ko = len(results) - ok
    print("\n=== RESUMEN BATTERIA STEP1 ===")
    print(f"Total: {len(results)} | OK: {ok} | FAIL: {ko}")
    for idx, passed, detail in results:
        status = "OK" if passed else "FAIL"
        print(f"{idx:02d} [{status}] {detail}")

    print("[INFO] Navegador mantenido abierto. Pulsa Ctrl+C para salir.")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    setup_asyncio_policy()
    asyncio.run(main())

