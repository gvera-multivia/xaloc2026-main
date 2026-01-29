import pandas as pd
import json
import time
import os
from groq import Groq

# ==========================================
# CONFIGURACIÓN
# ==========================================
API_KEY = os.getenv("GROQ_API_KEY")
INPUT_FILE = 'calles.xlsx'       
OUTPUT_FILE = 'resultado_ia.json' 
LIMITE_DIRECCIONES = 200          
LOTE_TAMANO = 30                 
MODELO = "llama-3.3-70b-versatile"
# ==========================================

client = Groq(api_key=API_KEY)

def preparar_lote_texto(lote):
    lineas = []
    mapa_originales = {}
    for index, row in lote.iterrows():
        id_actual = index + 1
        datos_ia = [
            f"calle: {row.get('calle', '')}",
            f"numero: {row.get('numero', '')}",
            f"piso: {row.get('piso', '')}",
            f"puerta: {row.get('puerta', '')}",
            f"poblacion: {row.get('poblacion', '')}"
        ]
        original_raw = ", ".join([str(val) for val in row.values if pd.notna(val) and str(val).lower() != 'null'])
        mapa_originales[id_actual] = original_raw
        lineas.append(f"ID {id_actual}: {', '.join(datos_ia)}")
    return "\n".join(lineas), mapa_originales

def llamar_ia(texto_lote):
    prompt_sistema = """
    Actúa como un experto en el catastro de España. Tu objetivo es parsear direcciones de forma ultra-limpia.
    Devuelve exclusivamente un objeto JSON con una lista bajo la clave 'direcciones'.
    
    Campos por objeto:
    - id: (proporcionado)
    - via: (CALLE, AVENIDA, PLAZA, etc.)
    - calle: (Nombre limpio de la vía. Corrige truncamientos si es obvio por la ciudad)
    - numero: (Solo el número o S/N)
    - escalera: (Solo el identificador)
    - planta: (Piso. Normaliza: 'P'->'PRINCIPAL', 'BJ'->'BAJO', '3º'->'3')
    - puerta: (Solo el identificador final. ELIMINA prefijos como 'NAVE', 'PTA', 'PUERTA', 'LOCAL', 'PUESTO'. Ejemplo: 'NAVE 8' -> '8', 'PTA 3' -> '3')

    REGLAS DE ORO:
    1. En 'puerta', si el valor es 'NAVE 8', pon solo '8'. Si es 'LOCAL 2', pon '2'.
    2. No inventes datos. Si no existe, deja "".
    3. JSON puro, sin comentarios.
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Limpia y estructura estas direcciones:\n{texto_lote}"}
            ],
            model=MODELO,
            response_format={"type": "json_object"},
            temperature=0.1 
        )
        return json.loads(chat_completion.choices[0].message.content)
    except Exception as e:
        print(f"Error: {e}")
        return {"direcciones": []}

def procesar():
    if not os.path.exists(INPUT_FILE):
        print(f"No encuentro {INPUT_FILE}")
        return

    df = pd.read_excel(INPUT_FILE).fillna("")
    df = df.head(LIMITE_DIRECCIONES)
    
    total_filas = len(df)
    print(f"Procesando {total_filas} filas con puerta optimizada...")
    
    resultados_globales = []

    for start in range(0, total_filas, LOTE_TAMANO):
        end = min(start + LOTE_TAMANO, total_filas)
        lote_df = df.iloc[start:end]
        
        print(f" -> Lote {start+1}-{end}...")
        texto_para_ia, mapa_originales_lote = preparar_lote_texto(lote_df)
        
        respuesta = llamar_ia(texto_para_ia)
        direcciones_procesadas = respuesta.get("direcciones", [])
        
        for dir_obj in direcciones_procesadas:
            id_ia = dir_obj.get("id")
            if id_ia in mapa_originales_lote:
                original = mapa_originales_lote[id_ia]
                nuevo_orden = {"id": id_ia, "Original": original}
                nuevo_orden.update({k: v for k, v in dir_obj.items() if k not in ["id", "Original"]})
                resultados_globales.append(nuevo_orden)
        
        time.sleep(1.2)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(resultados_globales, f, ensure_ascii=False, indent=4)
    
    print(f"\n¡Hecho! JSON generado con éxito en {OUTPUT_FILE}")

if __name__ == "__main__":
    procesar()