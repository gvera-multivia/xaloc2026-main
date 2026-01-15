import argparse
import asyncio
import logging
import sys
import inspect

from core.site_registry import get_site, get_site_controller, list_sites

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def _prompt_site_id() -> str:
    sites = list_sites()
    print("Selecciona la web a automatizar:")
    for idx, sid in enumerate(sites, start=1):
        print(f"  {idx}. {sid}")
    while True:
        raw = input("Introduce el número o el site_id: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(sites):
            return sites[int(raw) - 1]
        if raw in sites:
            return raw
        print(f"Entrada inválida. Opciones: {', '.join(sites)}")


def _prompt_protocol() -> str:
    opciones = ["P1", "P2", "P3"]
    print("Selecciona el protocolo para BASE On-line:")
    print("  P1 -> Identificación de conductor (M250)")
    print("  P2 -> Alegaciones (M203)")
    print("  P3 -> Recurso de reposición (recursTelematic)")
    while True:
        raw = input("Introduce P1, P2 o P3: ").strip().upper()
        if raw in opciones:
            return raw
        print("Entrada inválida. Opciones: P1, P2, P3")


def _call_with_supported_kwargs(fn, **kwargs):
    sig = inspect.signature(fn)
    supported = {k: v for k, v in kwargs.items() if k in sig.parameters and v is not None}
    return fn(**supported)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--protocol",
        default=None,
        help="Solo para site 'base_online': rama del workflow (P1, P2 o P3).",
    )
    args = parser.parse_args()

    site_id = args.site or _prompt_site_id()
    if site_id == "base_online" and not args.protocol:
        args.protocol = _prompt_protocol()

    controller = get_site_controller(site_id)
    config = _call_with_supported_kwargs(controller.create_config, headless=args.headless, protocol=args.protocol)
    datos = _call_with_supported_kwargs(controller.create_demo_data, protocol=args.protocol)

    print("\n" + "=" * 60)
    print(f"INICIANDO AUTOMATIZACION: {site_id}")
    print("=" * 60)
    print(
        """
    El popup de certificado de Windows se aceptará automáticamente
    usando pyautogui. El primer certificado disponible será seleccionado.
    """
    )

    AutomationCls = get_site(site_id)
    async with AutomationCls(config) as bot:
        try:
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\nOK. PROCESO FINALIZADO: {screenshot_path}")
        except Exception as e:
            print(f"\nERROR durante la ejecución: {e}")
        finally:
            input("\nProceso terminado. Pulsa ENTER para cerrar.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
