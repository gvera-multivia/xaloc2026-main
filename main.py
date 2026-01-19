"""
Menú principal interactivo para pruebas de automatización.
NOTA: Los protocolos actuales usan datos DUMMY y no envían información real.
"""
import argparse
import asyncio
import logging
import sys
import inspect
import os

from core.site_registry import get_site, get_site_controller, list_sites

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def clear_screen():
    """Limpia la pantalla de la terminal."""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    """Imprime el encabezado del menú."""
    print("=" * 60)
    print("    XALOC 2026 - AUTOMATIZACIÓN DE TRÁMITES")
    print("=" * 60)
    print()
    print("    ⚠️  MODO PRUEBAS - DATOS DUMMY ⚠️")
    print("    Los protocolos NO envían datos reales.")
    print()
    print("-" * 60)


def print_site_info(site_id: str):
    """Muestra información sobre el sitio seleccionado."""
    site_info = {
        "base_online": {
            "nombre": "BASE On-line",
            "descripcion": "Portal de la Diputación de Tarragona",
            "subprocesos": {
                "P1": "Identificación de conductor (M250)",
                "P2": "Alegaciones (M203)",
                "P3": "Recurso de reposición (recursTelematic)",
            }
        },
        "madrid": {
            "nombre": "Ayuntamiento de Madrid",
            "descripcion": "Portal de trámites del Ayuntamiento de Madrid",
            "subprocesos": None
        },
        "xaloc_girona": {
            "nombre": "Xaloc Girona",
            "descripcion": "Portal de la Diputación de Girona",
            "subprocesos": None
        }
    }
    return site_info.get(site_id, {})


def _prompt_site_id() -> str:
    """Solicita al usuario que seleccione la web a automatizar."""
    sites = list_sites()
    
    clear_screen()
    print_header()
    print()
    print("  📌 PASO 1: Selecciona la web a probar")
    print()
    
    for idx, sid in enumerate(sites, start=1):
        info = print_site_info(sid)
        nombre = info.get("nombre", sid)
        descripcion = info.get("descripcion", "")
        tiene_subprocesos = "✓ Subprocesos" if info.get("subprocesos") else ""
        
        print(f"    {idx}. {nombre}")
        print(f"       └─ {descripcion}")
        if tiene_subprocesos:
            print(f"          ({tiene_subprocesos})")
        print()
    
    print("-" * 60)
    
    while True:
        raw = input("\n  Introduce el número de tu elección: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(sites):
            return sites[int(raw) - 1]
        if raw in sites:
            return raw
        print(f"  ❌ Entrada inválida. Opciones válidas: 1-{len(sites)}")


def _prompt_protocol(site_id: str) -> str | None:
    """Solicita al usuario que seleccione el subproceso (si aplica)."""
    info = print_site_info(site_id)
    subprocesos = info.get("subprocesos")
    
    if not subprocesos:
        return None
    
    clear_screen()
    print_header()
    print()
    print(f"  📌 PASO 2: Selecciona el subproceso para {info.get('nombre', site_id)}")
    print()
    print("    ℹ️  Los subprocesos actuales son métodos de prueba DUMMY.")
    print("       No se enviarán datos reales al servidor.")
    print()
    
    opciones = list(subprocesos.keys())
    for idx, (key, desc) in enumerate(subprocesos.items(), start=1):
        print(f"    {idx}. [{key}] {desc}")
        print()
    
    print("-" * 60)
    
    while True:
        raw = input("\n  Introduce el número o código (P1/P2/P3): ").strip().upper()
        
        # Aceptar número
        if raw.isdigit() and 1 <= int(raw) <= len(opciones):
            return opciones[int(raw) - 1]
        
        # Aceptar código directo
        if raw in opciones:
            return raw
        
        print(f"  ❌ Entrada inválida. Opciones: 1-{len(opciones)} o {', '.join(opciones)}")


def _show_summary(site_id: str, protocol: str | None):
    """Muestra un resumen antes de ejecutar."""
    info = print_site_info(site_id)
    
    clear_screen()
    print_header()
    print()
    print("  📋 RESUMEN DE LA PRUEBA")
    print()
    print(f"    • Web:         {info.get('nombre', site_id)}")
    
    if protocol and info.get("subprocesos"):
        desc = info["subprocesos"].get(protocol, protocol)
        print(f"    • Subproceso:  [{protocol}] {desc}")
    
    print()
    print("  ⚠️  RECORDATORIO:")
    print("    - Esta es una prueba con datos DUMMY")
    print("    - Los protocolos NO envían información real")
    print("    - El popup de certificado se aceptará automáticamente")
    print()
    print("-" * 60)
    
    input("\n  Pulsa ENTER para iniciar la prueba...")


def _call_with_supported_kwargs(fn, **kwargs):
    sig = inspect.signature(fn)
    supported = {k: v for k, v in kwargs.items() if k in sig.parameters and v is not None}
    return fn(**supported)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Automatización de trámites - Modo pruebas")
    parser.add_argument("--site", default=None, help="ID del sitio (base_online, madrid, xaloc_girona)")
    parser.add_argument("--headless", action="store_true", help="Ejecutar sin interfaz gráfica")
    parser.add_argument(
        "--protocol",
        default=None,
        help="Solo para site 'base_online': rama del workflow (P1, P2 o P3).",
    )
    # Argumentos específicos de P3
    parser.add_argument("--p3-tipus-objecte", default=None, help="Solo P3: IBI | IVTM | Expediente Ejecutivo | Otros")
    parser.add_argument("--p3-dades", default=None, help="Solo P3: Dades especifiques")
    parser.add_argument("--p3-tipus-solicitud", default=None, help="Solo P3: value del tipo de solicitud (p.ej. 1)")
    parser.add_argument("--p3-exposo", default=None, help="Solo P3: texto de exposición")
    parser.add_argument("--p3-solicito", default=None, help="Solo P3: texto de solicitud")
    parser.add_argument("--p3-file", default=None, help="Solo P3: ruta del PDF a adjuntar")
    # Argumentos específicos de P1 y P2
    parser.add_argument("--p1-file", default=None, help="Solo P1: ruta del PDF a adjuntar")
    parser.add_argument("--p2-file", default=None, help="Solo P2: ruta del PDF a adjuntar")
    args = parser.parse_args()

    # Si no se pasan argumentos, mostrar menú interactivo
    if args.site is None:
        site_id = _prompt_site_id()
    else:
        site_id = args.site

    # Preguntar por subproceso si aplica
    if args.protocol is None:
        protocol = _prompt_protocol(site_id)
    else:
        protocol = args.protocol

    # Mostrar resumen antes de ejecutar
    _show_summary(site_id, protocol)

    controller = get_site_controller(site_id)
    config = _call_with_supported_kwargs(controller.create_config, headless=args.headless, protocol=protocol)
    datos = _call_with_supported_kwargs(
        controller.create_demo_data,
        protocol=protocol,
        p3_tipus_objecte=args.p3_tipus_objecte,
        p3_dades_especifiques=args.p3_dades,
        p3_tipus_solicitud_value=args.p3_tipus_solicitud,
        p3_exposo=args.p3_exposo,
        p3_solicito=args.p3_solicito,
        p3_archivos=args.p3_file,
        p1_archivos=args.p1_file,
        p2_archivos=args.p2_file,
    )

    print("\n" + "=" * 60)
    print(f"  🚀 INICIANDO AUTOMATIZACIÓN: {site_id.upper()}")
    if protocol:
        print(f"     Subproceso: {protocol}")
    print("=" * 60)

    AutomationCls = get_site(site_id)
    async with AutomationCls(config) as bot:
        try:
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\n  ✅ PROCESO FINALIZADO CON ÉXITO")
            print(f"     Screenshot: {screenshot_path}")
        except Exception as e:
            print(f"\n  ❌ ERROR durante la ejecución: {e}")
        finally:
            print()
            print("-" * 60)
            input("  Pulsa ENTER para cerrar...")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
