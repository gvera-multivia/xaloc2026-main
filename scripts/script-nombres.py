import os
import json
import concurrent.futures
from pathlib import Path
import time

# Configuración
BASE_PATH = r"\\SERVER-DOC\clientes"
OUTPUT_JSON = "dataset_clientes.json"
MAX_WORKERS = 20  # Ajusta según la potencia de tu red/PC

# Carpetas donde realmente suele estar el oro
TARGET_SUBFOLDERS = {"DOCUMENTACION", "DOCUMENTACIÓN", "DOCUMENTACION RECURSOS"}

def analizar_carpeta_cliente(client_path):
    """Escanea una carpeta de cliente de forma rápida."""
    archivos = []
    try:
        # 1. Listamos la raíz del cliente (por si los docs están sueltos)
        with os.scandir(client_path) as it:
            for entry in it:
                if entry.is_file():
                    archivos.append(entry.name)
                elif entry.is_dir() and entry.name.upper() in TARGET_SUBFOLDERS:
                    # 2. Si es una carpeta de interés, entramos un nivel
                    try:
                        with os.scandir(entry.path) as sub_it:
                            for sub_entry in sub_it:
                                if sub_entry.is_file():
                                    # Guardamos como 'Carpeta/Archivo'
                                    archivos.append(f"{entry.name}/{sub_entry.name}")
                    except Exception: pass
    except Exception:
        return None

    # Detectar si es empresa por el nombre de la carpeta
    is_company = any(s in client_path.name.upper() for s in ["S.L", "SL", "S.A", "SA", "PROMOTORA"])
    
    return client_path.name, {"is_company": is_company, "files": archivos}

def generar_inventario_veloz():
    dataset = {}
    start_time = time.time()
    folders_to_process = []

    print("Cargando lista de carpetas...")
    # Listar carpetas Letra-Letra
    with os.scandir(BASE_PATH) as it:
        for alpha_folder in it:
            if alpha_folder.is_dir():
                # Listar clientes dentro de esa letra
                with os.scandir(alpha_folder.path) as client_it:
                    for client_entry in client_it:
                        if client_entry.is_dir():
                            folders_to_process.append(Path(client_entry.path))

    print(f"Total clientes encontrados: {len(folders_to_process)}. Iniciando escaneo multihilo...")

    # Usamos hilos para combatir la latencia de red
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_client = {executor.submit(analizar_carpeta_cliente, f): f for f in folders_to_process}
        
        for i, future in enumerate(concurrent.futures.as_completed(future_to_client)):
            result = future.result()
            if result:
                name, data = result
                dataset[name] = data
            
            if i % 100 == 0:
                print(f"Procesados {i}/{len(folders_to_process)} clientes...")

    # Guardar resultados
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=4, ensure_ascii=False)
    
    end_time = time.time()
    print(f"\n¡Listo! Escaneo completado en {int(end_time - start_time)} segundos.")
    print(f"Archivo generado: {OUTPUT_JSON}")

if __name__ == "__main__":
    generar_inventario_veloz()