from __future__ import annotations

import sys
from pathlib import Path

# Priorizar actualizaciones/core/ sobre el core/ raíz del proyecto.
_ACTUALIZACIONES_DIR = Path(__file__).parent
if str(_ACTUALIZACIONES_DIR) not in sys.path:
    sys.path.insert(0, str(_ACTUALIZACIONES_DIR))

import argparse
import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

from actualizaciones.atc.automation import AtcAutomation
from actualizaciones.atc.controller import AtcController


HARDCODED_NUMEROCLIENTE = 42249
LOG_PATH = Path("actualizaciones/atc/atc.log")


def _configure_logger() -> logging.Logger:
    logger = logging.getLogger("xaloc_automation.atc")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    has_file_handler = any(
        isinstance(h, logging.FileHandler) and Path(getattr(h, "baseFilename", "")).resolve() == LOG_PATH.resolve()
        for h in logger.handlers
    )
    if not has_file_handler:
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    return logger


def build_payload(numero_cliente: int = HARDCODED_NUMEROCLIENTE) -> dict[str, Any]:
    return {
        "idRecurso": None,
        "idExp": None,
        "expediente": "",
        "fase_procedimiento": "",
        "sujeto_recurso": "",
        "numclient": int(numero_cliente),
        "nombre": "",
        "apellido1": "",
        "apellido2": "",
        "nif": "",
        "nifempresa": "",
        "tramite_url": "https://atc.gencat.cat/es/gestions/certificats/certificats-tributaris/",
        "archivos": [],
    }


async def run_flow(payload: dict[str, Any], *, headless: bool) -> dict[str, Any]:
    logger = logging.getLogger("xaloc_automation.atc")
    controller = AtcController()
    mapped = controller.map_data(payload)
    mapped["headless"] = bool(headless)
    datos = controller.create_target(**mapped)
    config = controller.create_config(headless=bool(headless))
    logger.info("atc.main run_flow START numclient=%s headless=%s", payload.get("numclient"), headless)

    try:
        async with AtcAutomation(config) as bot:
            screenshot = await bot.ejecutar_flujo_completo(datos)
        payload_updates = {
            "atc_download_pdf_path": datos.payload.get("atc_download_pdf_path"),
        }
        logger.info("atc.main run_flow END success=1 screenshot=%s", screenshot)
        return {
            "success": True,
            "error": None,
            "screenshot": screenshot,
            "payload_updates": payload_updates,
        }
    except Exception as exc:
        logger.exception("atc.main run_flow END success=0 error=%s", exc)
        return {
            "success": False,
            "error": str(exc),
            "screenshot": None,
            "payload_updates": {},
        }


def main() -> None:
    logger = _configure_logger()
    parser = argparse.ArgumentParser(description="Standalone smoke test for atc.")
    parser.add_argument(
        "--numerocliente",
        type=int,
        default=HARDCODED_NUMEROCLIENTE,
        help=f"Numero de cliente (default hardcodeado: {HARDCODED_NUMEROCLIENTE})",
    )
    parser.add_argument("--dump-only", action="store_true", help="Solo generar JSON de validacion")
    parser.add_argument("--run-flow", action="store_true", help="Ejecutar flujo Playwright local")
    parser.add_argument("--headless", action="store_true", help="Ejecutar navegador oculto")
    args = parser.parse_args()
    logger.info(
        "atc.main START numerocliente=%s dump_only=%s run_flow=%s headless=%s",
        args.numerocliente,
        args.dump_only,
        args.run_flow,
        args.headless,
    )

    base_input: dict[str, Any] = {"numerocliente": int(args.numerocliente)}
    payload = build_payload(args.numerocliente)

    controller = AtcController()
    mapped = controller.map_data(payload)
    target = controller.create_target(**mapped)

    out = Path("tmp")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / "atc_base_input_numclient_{}.json".format(args.numerocliente)
    payload_path = out / "atc_payload_numclient_{}.json".format(args.numerocliente)
    mapped_path = out / "atc_mapped_numclient_{}.json".format(args.numerocliente)
    raw_path.write_text(json.dumps(base_input, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mapped_path.write_text(json.dumps(asdict(target), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] base input: {raw_path}")
    print(f"[OK] payload: {payload_path}")
    print(f"[OK] mapped target: {mapped_path}")
    logger.info("atc.main artifacts written payload=%s mapped=%s", payload_path, mapped_path)

    if args.dump_only and not args.run_flow:
        return

    if args.run_flow:
        result = asyncio.run(run_flow(payload, headless=bool(args.headless)))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    logger.info("atc.main END")


if __name__ == "__main__":
    main()
