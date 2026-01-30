import pandas as pd
import requests
import json
import re

# --- CONFIGURACIÓN ---
INPUT_FILE = 'calles.xlsx'
OUTPUT_FILE = 'resultado_final.json'
DOCKER_URL = 'http://localhost:8080/parse'

MAPPER = {
    'c': 'CALLE', 'c/': 'CALLE', 'cl': 'CALLE', 'calle': 'CALLE', 'carrer': 'CALLE',
    'av': 'AVENIDA', 'avda': 'AVENIDA', 'avenida': 'AVENIDA', 'avinguda': 'AVINGUDA',
    'pl': 'PLAZA', 'pza': 'PLAZA', 'plaza': 'PLAZA', 'plaça': 'PLAZA',
    'ps': 'PASEO', 'pº': 'PASEO', 'passeig': 'PASEO',
    'ctra': 'CARRETERA', 'crta': 'CARRETERA', 'carretera': 'CARRETERA',
    'rbla': 'RAMBLA', 'rambla': 'RAMBLA', 'rda': 'RONDA', 'ronda': 'RONDA',
    'via': 'VIA', 'trav': 'TRAVESIA', 'lugar': 'LUGAR', 'poligono': 'POLIGONO',
}

def clean_val(s):
    if pd.isna(s) or str(s).lower() in ['nan', 'null', '']: return ""
    return str(s).strip()

def pre_procesar_madre(texto):
    """
    Normalización agresiva para direcciones españolas.
    """
    # 1. Eliminar CP (5 cifras) para que no lo confunda con el número de calle
    texto = re.sub(r'\b\d{5}\b', '', texto)
    
    # 2. Arreglar el patrón "16 - 5 1" -> "Numero 16, Piso 5, Puerta 1"
    # Detecta: numero + guion/espacio + numero + espacio + numero
    texto = re.sub(r'(\d+)\s*[-/]\s*(\d+)\s+(\d+)', r'Numero \1, Piso \2, Puerta \3', texto)

    # 3. Arreglar "64 B 2º B" -> "Numero 64, Escalera B, Piso 2, Puerta B"
    # Muy común en Madrid (ID 43)
    texto = re.sub(r'(\d+)\s+([A-Z])\s+(\d+)º?\s+([A-Z])', r'Numero \1, Escalera \2, Piso \3, Puerta \4', texto, flags=re.I)

    # 4. Naves y Locales: Forzar etiqueta Puerta
    texto = re.sub(r'\b(NAVE|LOCAL|PUESTO)\s*([\w/-]+)', r', Puerta \1 \2', texto, flags=re.I)
    
    # 5. C/ Pegado
    texto = re.sub(r'\bC/|C\.', 'CALLE ', texto, flags=re.I)
    
    return texto.strip()

def fix_output(text, label_used):
    if not text: return ""
    remplazos = {
        'IZQ': 'IZQUIERDA', 'IZ': 'IZQUIERDA', 'DR': 'DERECHA', 'DCHA': 'DERECHA', 
        'CTO': 'CENTRO', 'BJ': 'BAJO', 'BJO': 'BAJO', 'P': 'PRINCIPAL', 'PBJ': 'BAJO'
    }
    text = re.sub(rf'^{label_used}\s*', '', text, flags=re.I)
    val = re.sub(r'[ºª\.]|PISO|PTA|PUERTA|PLANTA|ESC|ESCALERA', '', text, flags=re.I).strip().upper()
    return remplazos.get(val, val)

def procesar():
    try:
        df = pd.read_excel(INPUT_FILE, header=0).head(200)
    except Exception as e:
        print(f"Error: {e}")
        return

    resultados = []

    for index, row in df.iterrows():
        # Captura cruda
        calle = clean_val(row.iloc[0])
        num   = clean_val(row.iloc[1])
        esc   = clean_val(row.iloc[2])
        piso  = clean_val(row.iloc[3])
        puert = clean_val(row.iloc[4])
        pob   = clean_val(row.iloc[6])

        # Construimos un string ayudando a la IA con etiquetas
        pistas = [calle]
        if num:   pistas.append(f"Numero {num}")
        if esc:   pistas.append(f"Escalera {esc}")
        if piso:  pistas.append(f"Piso {piso}")
        if puert: pistas.append(f"Puerta {puert}")
        if pob:   pistas.append(pob)

        raw_str = ", ".join(pistas)
        direccion_enviada = pre_procesar_madre(raw_str)

        try:
            r = requests.post(DOCKER_URL, json={"address": direccion_enviada}, timeout=10)
            parsed = r.json()

            out = {
                "id": index + 1,
                "Original": raw_str,
                "Tipo via": "CALLE",
                "Domicilio": calle,
                "Numero": num, "Escalera": esc, "Planta": fix_output(piso, 'Piso'), "Puerta": fix_output(puert, 'Puerta')
            }

            for item in parsed:
                val = item['value'].upper() if isinstance(item, dict) else item[0].upper()
                lab = item['label'] if isinstance(item, dict) else item[1]

                if lab == 'road':
                    # Si el domicilio contiene la población (Fallo ID 19), la quitamos
                    if pob.upper() in val:
                        val = val.replace(pob.upper(), "").strip(", ")
                    
                    val = re.sub(r'^(CALLE|C/|C\.|C|AVDA|AV)\s+', '', val, flags=re.I).strip()
                    tokens = val.split()
                    if tokens and tokens[0].lower().replace('.', '') in MAPPER:
                        out["Tipo via"] = MAPPER[tokens[0].lower().replace('.', '')]
                        out["Domicilio"] = " ".join(tokens[1:])
                    else:
                        out["Domicilio"] = val
                
                elif lab == 'house_number':
                    # Si la IA mete "16 5 1" en el numero, lo repartimos nosotros
                    parts = val.split()
                    if len(parts) >= 3:
                        out["Numero"], out["Planta"], out["Puerta"] = parts[0], parts[1], parts[2]
                    else:
                        out["Numero"] = val
                
                elif lab == 'staircase': out["Escalera"] = fix_output(val, 'ESCALERA')
                elif lab == 'level':     out["Planta"] = fix_output(val, 'PISO')
                elif lab == 'unit':      out["Puerta"] = fix_output(val, 'PUERTA')

            # Corrección final de "Naves" que se filtran al número
            if "NAVE" in out["Numero"]:
                out["Puerta"] = out["Numero"]
                out["Numero"] = ""

            resultados.append(out)
        except:
            continue

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=4)
    print("Procesamiento finalizado.")

if __name__ == "__main__":
    procesar()