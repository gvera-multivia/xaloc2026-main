"""
Módulo para clasificar direcciones postales usando IA (Groq).
Adaptado para cumplir con el catálogo oficial de tipos de vía del formulario.
"""

import os
import json
import re
import unicodedata
from typing import Optional
from groq import Groq

# Modelo a usar
MODELO = "llama-3.3-70b-versatile"

# Lista oficial extraída del select proporcionado
VIAS_VALIDAS = [
    "ACCESO", "AGREGADO", "ALAMEDA", "ANDADOR", "ARRABAL", "ARROYO", "AUTOPISTA", "AUTOVIA", 
    "AVENIDA", "BAJADA", "BARRANCO", "BARRANQUIL", "BARRIO", "BLOQUE", "BULEVAR", "CALEYA", 
    "CALLE", "CALLEJA", "CALLEJON", "CALLIZO", "CAMINO", "CAMPO", "CANAL", "CANTON", 
    "CARRERA", "CARRETERA", "CARRIL", "CASERIO", "CAÑADA", "CHALET", "CINTURON", "COLEGIO", 
    "COLONIA", "COMPLEJO", "CONCEJO", "CONJUNTO", "COSTANILLA", "CUESTA", "DETRÁS", 
    "DIPUTACION", "DISEMINADOS", "EDIFICIO", "EDIFICIOS", "ENTRADA", "ESCALINATA", 
    "ESPALDA", "ESTACION", "EXPLANADA", "EXTRAMUROS", "EXTRARRADIO", "FERROCARRIL", 
    "FINCA", "FUENTE", "GALERIA", "GLORIETA", "GRAN VIA", "GRUPO", "HUERTA", "JARDIN", 
    "JARDINES", "LADO", "LAGO", "LUGAR", "MALECON", "MANZANA", "MASIAS", "MERCADO", 
    "MONTE", "MONUMENTO", "MUELLE", "MUNICIPIO", "PARAMO", "PARQUE", "PARTICULAR", 
    "PARTIDA", "PASADIZO", "PASAJE", "PASEO", "PISTA", "PLACETA", "PLAZA", "PLAZUELA", 
    "POBLADO", "POLIGONO", "PROLONGACION", "PUENTE", "PUERTA", "QUINTA", "RACONADA", 
    "RAMAL", "RAMBLA", "RAMPA", "RIERA", "RINCON", "RIO", "RONDA", "RUA", "SALIDA", 
    "SALON", "SECTOR", "SENDA", "SOLAR", "SUBIDA", "TERRENOS", "TORRENTE", "TRANSVERSAL", 
    "TRASERA", "TRAVESIA", "URBANIZACION", "VALLE", "VEREDA", "VIA", "VIADUCTO", "VIAL"
]

_WORD_RE = re.compile(r"[0-9A-ZÁÉÍÓÚÜÑ]+", flags=re.IGNORECASE)


def _token_key(token: str) -> str:
    txt = (token or "").strip().upper()
    if not txt:
        return ""
    # Normalizamos a NFD para separar los acentos de las letras.
    # Pero queremos mantener la Ñ/ñ si es posible, aunque NFD la separa en N + tilde combinada.
    txt = unicodedata.normalize("NFD", txt)
    # Eliminamos marcadores de acentuación (Mn = Mark, Nonspacing)
    txt = "".join(ch for ch in txt if unicodedata.category(ch) != "Mn")
    return txt


def _restore_street_spelling(calle_candidate: str, direccion_raw: str) -> str:
    """
    Restaura grafía original desde direccion_raw (incluyendo Ñ/acentos) cuando
    la IA devuelve formas simplificadas como NUNEZ.
    """
    calle_up = (calle_candidate or "").strip().upper()
    raw_up = (direccion_raw or "").strip().upper()
    if not calle_up or not raw_up:
        return calle_up

    # Mapear tokens normalizados a su versión original con Ñ/acentos
    raw_map: dict[str, str] = {}
    for m in _WORD_RE.finditer(raw_up):
        tok = m.group(0).upper()
        key = _token_key(tok)
        if key and key not in raw_map:
            raw_map[key] = tok

    def _replace(match: re.Match[str]) -> str:
        tok = match.group(0).upper()
        key = _token_key(tok)
        # Si el token normalizado existe en el original, restauramos la grafía (Ñ, tildes)
        return raw_map.get(key, tok)

    return _WORD_RE.sub(_replace, calle_up)

def _get_groq_client(api_key: Optional[str] = None) -> Groq:
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY no está configurada en el entorno")
    return Groq(api_key=key)

def _build_prompt_sistema() -> str:
    """Construye el prompt del sistema incluyendo las vías permitidas."""
    vias_str = ", ".join(VIAS_VALIDAS)
    return f"""
    Actúas como un experto en el catastro de España. Tu objetivo es parsear direcciones de forma ultra-limpia.
    
    VALORES PERMITIDOS PARA 'via':
    [{vias_str}]

    Devuelve exclusivamente un objeto JSON con los siguientes campos:
    - via: (DEBE ser uno de los valores de la lista anterior. Si no encaja, usa 'CALLE')
    - calle: (Nombre limpio de la vía. Corrige truncamientos. PRESERVA las Ñ y tildes si las detectas)
    - numero: (Solo el número o S/N)
    - escalera: (Solo el identificador)
    - planta: (Piso. Normaliza: 'P'->'PRINCIPAL', 'BJ'->'BAJO', '3º'->'3')
    - puerta: (Solo el identificador final. ELIMINA 'NAVE', 'PTA', 'LOCAL', etc.)

    REGLAS:
    1. Si recibes 'CL' o 'C/', mapealo a 'CALLE'. Si recibes 'AV' a 'AVENIDA', etc.
    2. En 'puerta', si el valor es 'NAVE 8', pon solo '8'.
    3. NO elimines la letra Ñ de los nombres de calle (ej. NUÑEZ no debe ser NUNEZ).
    4. JSON puro, sin comentarios.
    """

async def classify_address_with_ai(
    direccion_raw: str,
    poblacion: str = "",
    numero: str = "",
    piso: str = "",
    puerta: str = "",
    *,
    api_key: Optional[str] = None
) -> dict:
    try:
        client = _get_groq_client(api_key)
        
        datos_ia = [f"calle: {direccion_raw}"]
        if numero: datos_ia.append(f"numero: {numero}")
        if poblacion: datos_ia.append(f"poblacion: {poblacion}")
        if piso: datos_ia.append(f"piso: {piso}")
        if puerta: datos_ia.append(f"puerta: {puerta}")
        
        texto_entrada = ", ".join(datos_ia)
        
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": _build_prompt_sistema()},
                {"role": "user", "content": f"Limpia y estructura esta dirección:\n{texto_entrada}"}
            ],
            model=MODELO,
            response_format={"type": "json_object"},
            temperature=0.1
        )
        
        respuesta = json.loads(chat_completion.choices[0].message.content)
        
        # Validar que la vía devuelta esté en nuestra lista
        via_ia = (respuesta.get("via") or "").strip().upper()
        if via_ia not in VIAS_VALIDAS:
            via_ia = "CALLE" # Fallback de seguridad

        return {
            "tipo_via": via_ia,
            "calle": _restore_street_spelling((respuesta.get("calle") or "").strip(), direccion_raw),
            "numero": (respuesta.get("numero") or "").strip().upper(),
            "escalera": (respuesta.get("escalera") or "").strip().upper(),
            "planta": (respuesta.get("planta") or "").strip().upper(),
            "puerta": (respuesta.get("puerta") or "").strip().upper()
        }
        
    except Exception as e:
        # Si falla la IA, usamos el fallback local
        return classify_address_fallback(direccion_raw)

async def classify_addresses_batch_with_ai(
    items: list[dict],
    *,
    api_key: Optional[str] = None,
) -> dict[str, dict]:
    """
    Clasifica un lote de direcciones en una sola llamada al LLM.

    Returns:
        Mapping { "<idRecurso>": {tipo_via, calle, numero, escalera, planta, puerta} }.
    """
    client = _get_groq_client(api_key)

    compact_items: list[dict] = []
    for it in items or []:
        rid = it.get("idRecurso")
        if rid is None:
            continue
        compact_items.append(
            {
                "idRecurso": str(rid),
                "direccion_raw": (it.get("direccion_raw") or "").strip(),
                "poblacion": (it.get("poblacion") or "").strip(),
                "numero": (it.get("numero") or "").strip(),
                "piso": (it.get("piso") or "").strip(),
                "puerta": (it.get("puerta") or "").strip(),
            }
        )

    if not compact_items:
        return {}

    system = (
        _build_prompt_sistema().strip()
        + "\n\n"
        + (
            "OBJETIVO EXTRA (BATCH):\n"
            "- Recibirás un JSON con una lista 'items'.\n"
            "- Devuelve EXCLUSIVAMENTE un objeto JSON cuyo mapping sea:\n"
            "  { \"<idRecurso>\": { via, calle, numero, escalera, planta, puerta } }\n"
            "- No incluyas claves adicionales fuera de ese mapping.\n"
            "- Si una dirección no se puede parsear, usa via='CALLE' y el resto vacío."
        )
    )

    user = json.dumps({"items": compact_items}, ensure_ascii=False)

    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=MODELO,
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    raw = chat_completion.choices[0].message.content
    respuesta = json.loads(raw)

    if not isinstance(respuesta, dict):
        raise ValueError("Respuesta batch no es un objeto JSON.")

    raw_by_id = {str(it.get("idRecurso")): (it.get("direccion_raw") or "") for it in compact_items}
    out: dict[str, dict] = {}
    for rid, val in respuesta.items():
        if not isinstance(val, dict):
            continue

        via_ia = (val.get("via") or "").strip().upper()
        if via_ia not in VIAS_VALIDAS:
            via_ia = "CALLE"

        src_direccion_raw = raw_by_id.get(str(rid), "")

        out[str(rid)] = {
            "tipo_via": via_ia,
            "calle": _restore_street_spelling((val.get("calle") or "").strip(), src_direccion_raw),
            "numero": (val.get("numero") or "").strip().upper(),
            "escalera": (val.get("escalera") or "").strip().upper(),
            "planta": (val.get("planta") or "").strip().upper(),
            "puerta": (val.get("puerta") or "").strip().upper(),
        }

    return out

def classify_address_fallback(direccion_raw: str) -> dict:
    """Mapeo manual extendido con las vías del formulario."""
    if not direccion_raw:
        return {"tipo_via": "CALLE", "calle": "", "numero": "", "escalera": "", "planta": "", "puerta": ""}

    # Mapeo de abreviaturas comunes a los términos exactos del select
    via_map = {
        "CL": "CALLE", "C/": "CALLE", "AV": "AVENIDA", "AVDA": "AVENIDA",
        "PZ": "PLAZA", "PZA": "PLAZA", "PL": "PLAZA", "PS": "PASEO",
        "TRAV": "TRAVESIA", "TRV": "TRAVESIA", "CTRA": "CARRETERA",
        "RD": "RONDA", "RDA": "RONDA", "URB": "URBANIZACION",
        "BL": "BLOQUE", "ED": "EDIFICIO", "POL": "POLIGONO",
        "GV": "GRAN VIA", "PJE": "PASAJE", "PR": "PROLONGACION"
    }
    
    parts = direccion_raw.strip().upper().split()
    first_token = parts[0].replace(".", "") # Limpiar puntos de abreviaturas
    
    # Buscar si el primer token coincide con una vía válida o una abreviatura
    tipo_via = "CALLE"
    if first_token in VIAS_VALIDAS:
        tipo_via = first_token
    elif first_token in via_map:
        tipo_via = via_map[first_token]
    
    # Lógica simple para extraer el número (primer token que contenga un dígito)
    numero = ""
    calle_parts = []
    
    start_idx = 1 if (first_token in VIAS_VALIDAS or first_token in via_map) else 0
    
    for token in parts[start_idx:]:
        if not numero and re.search(r'\d', token):
            numero = token
        else:
            calle_parts.append(token)
            
    return {
        "tipo_via": tipo_via,
        "calle": " ".join(calle_parts),
        "numero": numero,
        "escalera": "",
        "planta": "",
        "puerta": ""
    }
