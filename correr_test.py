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

    # 1. Filtro de extensión
    if ext == ".pdf": score += 50
    elif ext in [".jpg", ".jpeg", ".png"]: score += 20
    else: return -1000

    # 2. PRIORIDAD RECURSOS (Bonus masivo)
    if "RECURSOS" in path_upper:
        score += 1000

    # 3. Especificidad vs Combos
    if len(categories_found) > 1: score -= 45 
    elif len(categories_found) == 1: score += 35

    # 4. Keywords de Confianza
    if any(k in name for k in ["firmad", "firmat", "original", "completo"]):
        score += 50
    
    # REGLA "SOLO": Penalizamos la palabra 'solo' para que pierda contra la versión normal
    if "_solo_" in name or " solo " in name or name.endswith("solo.pdf"):
        score -= 10

    if "comp." in name or "comprimido" in name:
        score += 20

    # 5. Detección de Fragmentos
    is_frag = any(k in name for k in ["anverso", "reverso", "cara", "part", "darrera", "trasera", "front", "back", "pag"])
    has_num = bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", name))
    if is_frag or has_num: score += 15

    # 6. Penalización de basura
    if any(k in name for k in ["old", "antiguo", "vencido", "copia"]):
        score -= 200

    return score

def seleccionar_documentos_simulados(is_company: bool, filenames: list[str]):
    # --- REGLA DE ORO: SI HAY RECURSOS, IGNORAMOS EL RESTO ---
    has_recursos = any("DOCUMENTACION RECURSOS" in f.upper() for f in filenames)
    if has_recursos:
        filenames = [
            f for f in filenames 
            if not (("DOCUMENTACION" in f.upper() or "DOCUMENTACIÓN" in f.upper()) and "RECURSOS" not in f.upper())
        ]

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
            is_fragment = any(x in fname.lower() for x in ["anverso", "reverso", "cara", "part", "darrera", "trasera"]) or bool(re.search(r"[\s_-][0-9]{1,2}($|\.)", fname.lower()))
            buckets[cat].append({"name": fname, "score": score, "is_fragment": is_fragment})

    seleccion_final = []
    categorias_a_procesar = ["AUT", "DNI"]
    if is_company: categorias_a_procesar.extend(["CIF", "ESCR"])
    
    for cat in categorias_a_procesar:
        cands = buckets.get(cat, [])
        if not cands: continue
        
        cands.sort(key=lambda x: x["score"], reverse=True)
        
        # --- LÓGICA ESPECIAL PARA AUTORIZACIONES "SOLO" ---
        if cat == "AUT" and len(cands) > 1:
            nombres_con_solo = [c for c in cands if "solo" in c["name"].lower()]
            nombres_sin_solo = [c for c in cands if "solo" not in c["name"].lower()]
            
            # Si tenemos versiones SIN 'solo' con buena puntuación, descartamos las 'solo'
            if nombres_sin_solo:
                cands = [c for c in cands if "solo" not in c["name"].lower() or c["score"] > nombres_sin_solo[0]["score"]]

        if not cands: continue
        best = cands[0]
        
        # --- SELECCIÓN MULTI-SOCIO (Ventana de 20 pts) ---
        # Cogemos todos los que estén en el top para capturar varios socios
        top_tier = [c["name"] for c in cands if c["score"] > (best["score"] - 20)]
        seleccion_final.extend(top_tier)
        
        # --- SELECCIÓN FRAGMENTOS (Ventana de 65 pts) ---
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