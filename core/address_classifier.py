"""
Módulo para clasificar direcciones postales usando IA (Groq).
Adaptado de scripts/llamar_ia.py para uso con payloads del worker.
"""

import os
import json
from typing import Optional
from groq import Groq


# Modelo a usar (mismo que llamar_ia.py)
MODELO = "llama-3.3-70b-versatile"


def _get_groq_client(api_key: Optional[str] = None) -> Groq:
    """Obtiene el cliente de Groq con la API key."""
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY no está configurada en el entorno")
    return Groq(api_key=key)


def _build_prompt_sistema() -> str:
    """Construye el prompt del sistema para la IA."""
    return """
    Actúas como un experto en el catastro de España. Tu objetivo es parsear direcciones de forma ultra-limpia.
    Devuelve exclusivamente un objeto JSON con los siguientes campos:
    
    - via: (CALLE, AVENIDA, PLAZA, etc.)
    - calle: (Nombre limpio de la vía. Corrige truncamientos si es obvio por la ciudad)
    - numero: (Solo el número o S/N)
    - escalera: (Solo el identificador)
    - planta: (Piso. Normaliza: 'P'->'PRINCIPAL', 'BJ'->'BAJO', '3º'->'3')
    - puerta: (Solo el identificador final. ELIMINA prefijos como 'NAVE', 'PTA', 'PUERTA', 'LOCAL', 'PUESTO'. Ejemplo: 'NAVE 8' -> '8', 'PTA 3' -> '3')

    REGLAS DE ORO:
    1. En 'puerta', si el valor es 'NAVE 8', pon solo '8'. Si es 'LOCAL 2', pon '2'.
    2. No inventes datos. Si no existe, deja "".
    3. No “corrijas” nombres de calles ni completes direcciones: respeta el texto proporcionado.
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
    """
    Clasifica una dirección usando IA (Groq).
    
    Args:
        direccion_raw: Dirección completa o calle (ej: "CL MAYOR 15")
        poblacion: Población/municipio (opcional, ayuda al contexto)
        numero: Número de la calle desde la DB (opcional)
        piso: Piso/planta (opcional)
        puerta: Puerta (opcional)
        api_key: API key de Groq (opcional, usa GROQ_API_KEY del entorno si no se proporciona)
    
    Returns:
        {
            "tipo_via": "CALLE",
            "calle": "MAYOR",
            "numero": "15",
            "escalera": "",
            "planta": "2",
            "puerta": "A"
        }
    
    Raises:
        ValueError: Si GROQ_API_KEY no está configurada
        Exception: Si la llamada a la IA falla
    """
    try:
        client = _get_groq_client(api_key)
        
        # Construir el texto de entrada similar a llamar_ia.py
        datos_ia = [
            f"calle: {direccion_raw}",
        ]
        if numero:
            datos_ia.append(f"numero: {numero}")
        if poblacion:
            datos_ia.append(f"poblacion: {poblacion}")
        if piso:
            datos_ia.append(f"piso: {piso}")
        if puerta:
            datos_ia.append(f"puerta: {puerta}")
        
        texto_entrada = ", ".join(datos_ia)
        
        # Llamar a la IA
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": _build_prompt_sistema()},
                {"role": "user", "content": f"Limpia y estructura esta dirección:\n{texto_entrada}"}
            ],
            model=MODELO,
            response_format={"type": "json_object"},
            temperature=0.1
        )
        
        # Parsear respuesta
        respuesta = json.loads(chat_completion.choices[0].message.content)
        
        # Normalizar campos al formato esperado por Madrid
        via = (respuesta.get("via") or "").strip().upper()
        calle = (respuesta.get("calle") or "").strip().upper()
        numero = (respuesta.get("numero") or "").strip()
        escalera = (respuesta.get("escalera") or "").strip().upper()
        planta = (respuesta.get("planta") or "").strip().upper()
        puerta_parsed = (respuesta.get("puerta") or "").strip().upper()
        
        return {
            "tipo_via": via or "CALLE",  # Fallback a CALLE si no se detecta
            "calle": calle,
            "numero": numero,
            "escalera": escalera,
            "planta": planta,
            "puerta": puerta_parsed
        }
        
    except Exception as e:
        raise Exception(f"Error al clasificar dirección con IA: {e}") from e


def classify_address_fallback(direccion_raw: str) -> dict:
    """
    Clasificación fallback sin IA (lógica simple).
    Usa heurísticas básicas para parsear la dirección.
    
    Args:
        direccion_raw: Dirección completa (ej: "CL MAYOR 15")
    
    Returns:
        Diccionario con campos básicos parseados
    """
    import re
    
    if not direccion_raw:
        return {
            "tipo_via": "CALLE",
            "calle": "",
            "numero": "",
            "escalera": "",
            "planta": "",
            "puerta": ""
        }
    
    # Mapeo de abreviaturas a tipos de vía
    via_map = {
        "CL": "CALLE",
        "CALLE": "CALLE",
        "C/": "CALLE",
        "AV": "AVENIDA",
        "AVDA": "AVENIDA",
        "AVENIDA": "AVENIDA",
        "RD": "RONDA",
        "RONDA": "RONDA",
        "PS": "PASEO",
        "PASEO": "PASEO",
        "CTRA": "CARRETERA",
        "CARRETERA": "CARRETERA",
        "PL": "PLAZA",
        "PLAZA": "PLAZA"
    }
    
    parts = direccion_raw.strip().upper().split()
    if not parts:
        return {
            "tipo_via": "CALLE",
            "calle": "",
            "numero": "",
            "escalera": "",
            "planta": "",
            "puerta": ""
        }
    
    stop_tokens = {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y"}

    # Intentar detectar tipo de vía en el primer token
    first_token = parts[0]
    tipo_via = via_map.get(first_token, "CALLE")
    
    # Intentar extraer número (buscar dígitos en los tokens)
    numero = ""
    calle_parts = []
    
    for i, token in enumerate(parts):
        # Si es el primer token y es tipo de vía, saltar
        if i == 0 and first_token in via_map:
            continue
        if token in stop_tokens:
            continue
        
        # Si contiene dígitos, podría ser el número
        if re.search(r'\d', token):
            if not numero:
                numero = token
        else:
            calle_parts.append(token)
    
    calle = " ".join(calle_parts)
    
    return {
        "tipo_via": tipo_via,
        "calle": calle,
        "numero": numero,
        "escalera": "",
        "planta": "",
        "puerta": ""
    }
