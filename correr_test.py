import json
import os
from pathlib import Path
from collections import defaultdict
import re

# --- CONFIGURACIÓN DE PRUEBA ---
# Si tu JSON tiene otro nombre, cámbialo aquí
JSON_INPUT = "dataset_clientes.json"
JSON_OUTPUT = "resultados_simulacion.json"


# Mapeo de categorías y keywords
CATEGORIES_BASE = {
    "AUT": ["aut"],
    "DNI": ["dni", "nie", "pasaporte"],
    "CIF": ["cif", "nif"],
    "ESCR": ["escr", "constitu"]
}

def _calculate_file_score(filename: str, categories_found: list[str]) -> int:
    score = 0
    name = filename.lower()
    path_upper = filename.upper()
    ext = Path(filename).suffix.lower()

    # 1. Filtro de extensión básico
    if ext == ".pdf": score += 50
    elif ext in [".jpg", ".jpeg", ".png"]: score += 20
    else: return -1000

    # 2. EL FACTOR DETERMINANTE: FIRMA (CF vs SF)
    # Le damos el peso más alto de todos para que salte entre carpetas si es necesario
    es_cf = any(k in name for k in [" cf", "_cf", "-cf", "con firma", "confirma", " firmad", " firmat"])
    es_sf = any(k in name for k in [" sf", "_sf", "-sf", "sin firma", "sinfirma"])

    if es_cf:
        score += 1500  # Prioridad máxima
    elif es_sf:
        score -= 100   # Penalización ligera para que prefiera el archivo "limpio"
    
    # 3. PRIORIDAD DE UBICACIÓN (RECURSOS)
    # Es alta, pero menor que un CF confirmado
    if "RECURSOS" in path_upper:
        score += 800

    # 4. Especificidad vs Combos (Evitar AUTDNI.pdf si hay sueltos)
    if len(categories_found) > 1: score -= 45 
    elif len(categories_found) == 1: score += 35

    # 5. Keywords de Confianza adicionales
    if any(k in name for k in ["original", "completo", "definitivo"]):
        score += 50
    if "comp." in name or "comprimido" in name:
        score += 20

    # 6. Detección de Fragmentos / Secuenciales
    is_frag = any(k in name for k in ["anverso", "reverso", "cara", "part", "darrera", "trasera", "pag"])
    has_num = bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", name))
    if is_frag or has_num: score += 15

    # 7. Penalización de archivos antiguos
    if any(k in name for k in ["old", "antiguo", "vencido", "copia"]):
        score -= 500

    return score

def seleccionar_documentos_simulados(is_company: bool, filenames: list[str]):
    # NOTA: Ya no filtramos 'filenames' por carpeta Recursos aquí. 
    # Mantenemos todos para permitir el "relleno de huecos".

    buckets = defaultdict(list)
    categories_map = {
        "AUT": ["aut"],
        "DNI": ["dni", "nie", "pasaporte"],
        "CIF": ["cif", "nif"],
        "ESCR": ["escr", "constitu", "titularidad", "notar", "poder", "acta", "mercantil"]
    }
    
    for fname in filenames:
        cats = [cat for cat, keys in categories_map.items() if any(k in fname.lower() for k in keys)]
        if not cats: continue
        
        score = _calculate_file_score(fname, cats)
        if score < 0: continue
        
        for cat in cats:
            # Determinamos si es fragmento para la lógica de ventana
            is_fragment = any(x in fname.lower() for x in ["anverso", "reverso", "cara", "part", "darrera", "trasera"]) or \
                          bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", fname.lower()))
            
            buckets[cat].append({
                "name": fname, 
                "score": score, 
                "is_fragment": is_fragment
            })

    seleccion_final = []
    categorias_a_procesar = ["AUT", "DNI"]
    if is_company: categorias_a_procesar.extend(["CIF", "ESCR"])
    
    for cat in categorias_a_procesar:
        cands = buckets.get(cat, [])
        if not cands: continue
        
        # Ordenar por score (la mezcla de CF + Recursos hará que ganen los mejores)
        cands.sort(key=lambda x: x["score"], reverse=True)
        best = cands[0]
        
        # --- LÓGICA DE SELECCIÓN ---
        # 1. Ventana de 20 pts para capturar múltiples socios/DNIs
        top_tier = [c["name"] for c in cands if c["score"] > (best["score"] - 20)]
        seleccion_final.extend(top_tier)
        
        # 2. Ventana de 65 pts si el mejor es un fragmento (Anverso/Reverso)
        if best["is_fragment"]:
            fragmentos = [c["name"] for c in cands if c["is_fragment"] and c["score"] > (best["score"] - 65)]
            seleccion_final.extend(fragmentos)
            
    return list(dict.fromkeys(seleccion_final)), buckets

def ejecutar_test():
    if not os.path.exists(JSON_INPUT):
        print(f"Error: No se encuentra el archivo {JSON_INPUT}")
        return

    with open(JSON_INPUT, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Diccionario para almacenar el reporte final
    reporte_final = {}

    print("="*80)
    print(f"{'SIMULANDO HEURÍSTICA Y GENERANDO JSON':^80}")
    print("="*80)

    for cliente, info in data.items():
        if not info["files"]: continue
        
        is_comp = info["is_company"]
        # Ejecutamos la lógica
        seleccionados, buckets = seleccionar_documentos_simulados(is_comp, info["files"])
        
        if not buckets: continue

        # Estructuramos el resultado del cliente para el JSON
        resultado_cliente = {
            "cliente": cliente,
            "tipo": "Empresa" if is_comp else "Particular",
            "decision_final": seleccionados,
            "status": "OK" if seleccionados else "ERROR_MISSING_DOCS",
            "analisis_detallado": {}
        }

        # Guardamos el desglose de puntos para auditoría
        for cat, cands in buckets.items():
            resultado_cliente["analisis_detallado"][cat] = [
                {
                    "archivo": c["name"],
                    "puntos": c["score"],
                    "es_fragmento": c["is_fragment"]
                } for c in cands
            ]

        reporte_final[cliente] = resultado_cliente
        print(f"✅ Procesado: {cliente[:40]:<40} | Docs: {len(seleccionados)}")

    # Guardar el resultado en un archivo JSON
    with open(JSON_OUTPUT, "w", encoding="utf-8") as f_out:
        json.dump(reporte_final, f_out, indent=4, ensure_ascii=False)

    print("\n" + "="*80)
    print(f"SIMULACIÓN COMPLETADA")
    print(f"Resultados guardados en: {JSON_OUTPUT}")
    print("="*80)

if __name__ == "__main__":
    ejecutar_test()