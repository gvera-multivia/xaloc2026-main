import subprocess
import sys
from pathlib import Path
import os

def main():
    # Definir rutas
    base_dir = Path(__file__).parent
    auth_dir = base_dir / "auth"
    auth_file = auth_dir / "auth_state.json"
    
    auth_dir.mkdir(exist_ok=True)
    
    print("\n" + "="*60)
    print("🎥 GRABADOR DE SESIÓN XALOC (Versión Python)")
    print("="*60)
    print("1. Se abrirá el navegador.")
    print("2. Haz LOGIN con tu CERTIFICADO DIGITAL.")
    print("3. Cuando veas tu área privada, CIERRA EL NAVEGADOR.")
    print(f"4. Destino: {auth_file}")
    print("="*60 + "\n")
    
    input("Pulsa ENTER para comenzar...")
    
    # Usamos sys.executable -m playwright para asegurar que usamos el venv
    cmd = [
        sys.executable, "-m", "playwright",
        "codegen",
        "--save-storage", str(auth_file),
        "https://www.xalocgirona.cat/seu-electronica?view=tramits&id=11"
    ]
    
    try:
        # En Python Playwright no solemos necesitar shell=True si usamos la lista de comandos
        subprocess.run(cmd, check=True)
            
        print("\n✅ Grabación finalizada.")
        if auth_file.exists():
            print(f"📂 Sesión guardada en: {auth_file}")
        else:
            print("❌ No se generó el archivo. ¿Cerraste el navegador antes de tiempo?")
            
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error al ejecutar Playwright: {e}")
        print("Prueba a ejecutar en la consola: playwright install")
    except KeyboardInterrupt:
        print("\n\n⚠️ Cancelado.")

if __name__ == "__main__":
    main()