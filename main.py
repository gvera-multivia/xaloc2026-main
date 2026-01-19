"""
Menú principal interactivo para pruebas de automatización.
NOTA: Los protocolos actuales usan datos DUMMY por defecto, 
a menos que se seleccione el MODO REAL.
"""
import argparse
import asyncio
import logging
import sys
import inspect
import os

from core.site_registry import get_site, get_site_controller, list_sites
from core.db import MockDatabase

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
        },
        "redsara": {
            "nombre": "RedSARA",
            "descripcion": "Registro Electrónico Común (Administración General del Estado)",
            "subprocesos": None
        }
    }
    return site_info.get(site_id, {})


def _prompt_site_id() -> str:
    """Solicita al usuario que seleccione la web a automatizar."""
    sites = list_sites()
    
    clear_screen()
    print_header()
    print("  --> PASO 1: Selecciona la web a probar")
    print()
    
    for idx, sid in enumerate(sites, start=1):
        info = print_site_info(sid)
        nombre = info.get("nombre", sid)
        descripcion = info.get("descripcion", "")
        tiene_subprocesos = "<3> Subprocesos" if info.get("subprocesos") else ""
        
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
        print(f"  !! Entrada inválida. Opciones válidas: 1-{len(sites)}")


def _prompt_protocol(site_id: str) -> str | None:
    """Solicita al usuario que seleccione el subproceso (si aplica)."""
    info = print_site_info(site_id)
    subprocesos = info.get("subprocesos")
    
    if not subprocesos:
        return None
    
    clear_screen()
    print_header()
    print(f"  --> PASO 2: Selecciona el subproceso para {info.get('nombre', site_id)}")
    print()
    
    opciones = list(subprocesos.keys())
    for idx, (key, desc) in enumerate(subprocesos.items(), start=1):
        print(f"    {idx}. [{key}] {desc}")
    
    print()
    print("-" * 60)
    
    while True:
        raw = input("\n  Introduce el número o código (P1/P2/P3): ").strip().upper()
        
        if raw.isdigit() and 1 <= int(raw) <= len(opciones):
            return opciones[int(raw) - 1]
        
        if raw in opciones:
            return raw
        
        print(f"  !! Entrada inválida. Opciones: 1-{len(opciones)} o {', '.join(opciones)}")


def _prompt_real_mode() -> bool:
    """Solicita al usuario si desea usar el modo real o dummy."""
    clear_screen()
    print_header()
    print("  --> PASO 3: Selección de origen de datos")
    print()
    print("    1. MODO PRUEBAS (Datos Dummy)")
    print("       └─ Usa datos estáticos locales para test rápido.")
    print()
    print("    2. MODO REAL (Base de Datos)")
    print("       └─ Busca trámites pendientes en la DB (Mock).")
    print()
    print("-" * 60)

    while True:
        raw = input("\n  Selecciona el modo (1 o 2): ").strip()
        if raw == "1":
            return False
        if raw == "2":
            return True
        print("  !! Entrada inválida. Por favor, selecciona 1 o 2.")


def _show_summary(site_id: str, protocol: str | None, is_real: bool):
    """Muestra un resumen antes de ejecutar."""
    info = print_site_info(site_id)
    
    clear_screen()
    print_header()
    print("  <> RESUMEN DE LA EJECUCIÓN")
    print()
    print(f"    • Web:         {info.get('nombre', site_id)}")
    
    if protocol and info.get("subprocesos"):
        desc = info["subprocesos"].get(protocol, protocol)
        print(f"    • Subproceso:  [{protocol}] {desc}")
    
    print(f"    • Modo:        {'REAL (Base de Datos)' if is_real else 'PRUEBAS (Dummy)'}")
    print()
    
    if is_real:
        print("  ! ADVERTENCIA: Se procesarán trámites reales de la DB.")
    else:
        print("  * Nota: Se utilizarán datos ficticios para la prueba.")

    print("    - El popup de certificado se aceptará automáticamente.")
    print()
    print("-" * 60)
    
    input("\n  Pulsa ENTER para iniciar la ejecución...")


def _call_with_supported_kwargs(fn, **kwargs):
    sig = inspect.signature(fn)
    supported = {k: v for k, v in kwargs.items() if k in sig.parameters and v is not None}
    return fn(**supported)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Automatización de trámites - XALOC 2026")
    parser.add_argument("--site", default=None, help="ID del sitio (base_online, madrid, xaloc_girona)")
    parser.add_argument("--headless", action="store_true", help="Ejecutar sin interfaz gráfica")
    parser.add_argument("--real", action="store_true", help="Usar datos reales de la base de datos.")
    parser.add_argument("--protocol", default=None, help="Rama del workflow (P1, P2 o P3).")
    
    # Argumentos adicionales (P1, P2, P3)
    parser.add_argument("--p3-tipus-objecte", default=None)
    parser.add_argument("--p3-dades", default=None)
    parser.add_argument("--p3-tipus-solicitud", default=None)
    parser.add_argument("--p3-exposo", default=None)
    parser.add_argument("--p3-solicito", default=None)
    parser.add_argument("--p3-file", default=None)
    parser.add_argument("--p1-file", default=None)
    parser.add_argument("--p2-file", default=None)
    
    args = parser.parse_args()

    # --- LÓGICA DE SELECCIÓN INTERACTIVA ---
    
    # 1. Sitio
    site_id = args.site if args.site else _prompt_site_id()

    # 2. Protocolo
    protocol = args.protocol if args.protocol else _prompt_protocol(site_id)

    # 3. Modo Real vs Dummy
    # Preguntamos solo si NO se pasó el flag --real y NO se especificó site por comando
    if not args.real and args.site is None:
        is_real = _prompt_real_mode()
    else:
        is_real = args.real

    # 4. Resumen y Confirmación
    _show_summary(site_id, protocol, is_real)

    # --- INICIO DE EJECUCIÓN ---

    controller = get_site_controller(site_id)
    config = _call_with_supported_kwargs(controller.create_config, headless=args.headless, protocol=protocol)

    tramite_id = None
    db = None

    if is_real:
        db = MockDatabase()
        print(f"\n  >>> BUSCANDO TRÁMITE PENDIENTE EN DB para {site_id}...")
        tramite_result = db.get_pending_tramite(site_id, protocol)

        if not tramite_result:
            print(f"  !! No se encontraron trámites pendientes en la DB.")
            input("\n  Pulsa ENTER para salir...")
            return

        tramite_id, raw_data = tramite_result
        print(f"  <> Trámite encontrado ID: {tramite_id}")

        mapped_data = controller.map_data(raw_data)
        mapped_data.update({"protocol": protocol, "headless": args.headless})
        datos = _call_with_supported_kwargs(controller.create_target, **mapped_data)
    else:
        datos = _call_with_supported_kwargs(
            controller.create_target,
            protocol=protocol,
            p3_tipus_objecte=args.p3_tipus_objecte,
            p3_dades_especifiques=args.p3_dades,
            p3_tipus_solicitud_value=args.p3_tipus_solicitud,
            p3_exposo=args.p3_exposo,
            p3_solicito=args.p3_solicito,
            p3_archivos=args.p3_file,
            p1_archivos=args.p1_file,
            p2_archivos=args.p2_file,
            headless=args.headless,
        )

    print("\n" + "=" * 60)
    print(f"  >>> INICIANDO AUTOMATIZACIÓN: {site_id.upper()}")
    print("=" * 60)

    AutomationCls = get_site(site_id)
    async with AutomationCls(config) as bot:
        try:
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\n  <> PROCESO FINALIZADO CON ÉXITO")
            print(f"     Evidencia: {screenshot_path}")

            if is_real and db and tramite_id:
                db.mark_tramite_processed(tramite_id, "success", {"screenshot": str(screenshot_path)})

        except Exception as e:
            print(f"\n  !! ERROR: {e}")
            if is_real and db and tramite_id:
                db.mark_tramite_processed(tramite_id, "error", {"error": str(e)})

        finally:
            print("-" * 60)
            input("  Pulsa ENTER para cerrar el navegador y finalizar...")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())