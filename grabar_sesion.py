"""
Script auxiliar para grabar la sesión de usuario (cookies, local storage).
Ejecuta playwright codegen para que el usuario haga login manual con certificado.
El estado se guarda en auth/auth_state.json para futuras ejecuciones.
"""
import subprocess
import sys
from pathlib import Path
import os

def main():
    # Definir rutas
    base_dir = Path(__file__).parent
    auth_dir = base_dir / "auth"
    auth_file = auth_dir / "auth_state.json"
    
    # Asegurar que existe el directorio
    auth_dir.mkdir(exist_ok=True)
    
    print("\n" + "="*60)
    print("🎥 GRABADOR DE SESIÓN XALOC")
    print("="*60)
    print("1. Se abrirá una ventana de navegador.")
    print("2. Navega a la web y haz LOGIN con tu CERTIFICADO DIGITAL.")
    print("3. Una vez logueado y veas la pantalla de inicio de trámite, CIERRA EL NAVEGADOR.")
    print(f"4. La sesión se guardará en: {auth_file}")
    print("="*60 + "\n")
    
    input("Pulsa ENTER para comenzar la grabación...")
    
    # Comando para lanzar codegen y guardar estado
    # Usamos shell=True en Windows para evitar problemas con npx
    cmd = [
        "npx", 
        "playwright", 
        "codegen", 
        "--save-storage", str(auth_file),
        "https://www.xalocgirona.cat/seu-electronica?view=tramits&id=11"
    ]
    
    try:
        if sys.platform == "win32":
            subprocess.run(cmd, shell=True, check=True)
        else:
            subprocess.run(cmd, check=True)
            
        print("\n✅ Grabación finalizada.")
        if auth_file.exists():
            print(f"📂 Archivo de sesión creado correctamente: {auth_file}")
            print("Ahora puedes ejecutar 'main.py' y debería entrar sin pedir certificado.")
        else:
            print("❌ ADVERTENCIA: No se encontró el archivo de sesión. ¿Cerraste el navegador correctamente?")
            
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error al ejecutar Playwright Codegen: {e}")
    except KeyboardInterrupt:
        print("\n\n⚠️ Operación cancelada por el usuario.")

if __name__ == "__main__":
    main()
