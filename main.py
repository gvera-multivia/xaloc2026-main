import asyncio
import sys
import logging

from config import Config, DatosMulta
from xaloc_automation import XalocAsync
from pathlib import Path
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')


async def main():
    """Ejecuta la automatización completa."""
    config = Config()
    
    datos = DatosMulta(
        email="test@example.com",
        num_denuncia="DEN/2024/001",
        matricula="1234ABC",
        num_expediente="EXP/2024/001",
        motivos="Alegación de prueba.",
        archivos_adjuntos=None,
        archivo_adjunto=Path("pdfs-prueba") / "test1.pdf"
    )

    print("\n" + "="*60)
    print("🚀 INICIANDO AUTOMATIZACIÓN XALOC")
    print("="*60)
    print("""
    El popup de certificado de Windows se aceptará automáticamente
    usando pyautogui. El primer certificado disponible será seleccionado.
    """)
    
    async with XalocAsync(config) as bot:
        try:
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print(f"\n✅ PROCESO FINALIZADO: {screenshot_path}")
            
        except Exception as e:
            print(f"\n❌ Error durante la ejecución: {e}")
        finally:
            input("\nProceso terminado. Pulsa ENTER para cerrar.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
