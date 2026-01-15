"""
Punto de entrada principal para Xaloc Automation
"""
import asyncio
import sys
from pathlib import Path
from config import Config, DatosMulta
from xaloc_automation import XalocAsync


# Configurar encoding para Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')


async def main():
    """Función principal"""
    config = Config()
    
    # Datos de prueba
    datos = DatosMulta(
        email="test@example.com",
        num_denuncia="DEN/2024/001",
        matricula="1234ABC",
        num_expediente="EXP/2024/001",
        motivos="Alegación de prueba. Texto de ejemplo para testing de automatización.",
        archivo_adjunto=Path("test_files/documento.pdf")  # Opcional
    )
    
    print("\n" + "="*60)
    print("🚀 XALOC AUTOMATION - TRAMITACIÓN DE ALEGACIONES")
    print("="*60 + "\n")
    
    async with XalocAsync(config) as bot:
        try:
            screenshot_path = await bot.ejecutar_flujo_completo(datos)
            print("\n" + "="*60)
            print("✅ PROCESO FINALIZADO CON ÉXITO")
            print("="*60)
            print(f"\n📸 Screenshot final: {screenshot_path}")
            print("\n⚠️  NOTA: El botón 'Enviar' NO fue pulsado (modo testing)")
            
        except Exception as e:
            print("\n" + "="*60)
            print("❌ ERROR EN LA EJECUCIÓN")
            print("="*60)
            print(f"\n{e}")
        
        finally:
            input("\n\nPulsa ENTER para cerrar...")


if __name__ == "__main__":
    asyncio.run(main())
