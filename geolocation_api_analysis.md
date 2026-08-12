# Análisis de Geolocalización y Clasificación de Direcciones - Proyecto Morrigan

Este documento detalla las implementaciones de clasificación, inferencia y validación geográfica dentro del proyecto, identificando las necesidades cubiertas y proponiendo una estructura de API para centralizar estas funcionalidades.

## 1. Inventario de Métodos de Clasificación y Uso de IA

El proyecto utiliza diversas técnicas para clasificar y estructurar localizaciones, adaptándose a las restricciones de las sedes electrónicas españolas.

### A. Clasificación Basada en LLM (Groq)
**Ubicación:** `core/address_classifier.py`
- **Uso:** Transformación de direcciones no estructuradas (ej: "C/ Mayor 5, 2B") en campos JSON.
- **Modelo:** `llama-3.3-70b-versatile`.
- **Lógica de Prompt:** Instruye al modelo para usar un catálogo cerrado de ~100 tipos de vía oficiales (vías permitidas).
- **Tratamiento de Datos:** Maneja campos como `via`, `calle`, `numero`, `escalera`, `planta` y `puerta`.
- **Optimizaciones:** Implementa `classify_addresses_batch_with_ai` para procesar múltiples registros en una sola consulta al LLM.
- **Preservación de Grafía:** Incluye una función `_restore_street_spelling` que utiliza `unicodedata` para comparar el resultado del LLM con el original y recuperar caracteres especiales (Ñ, tildes) que la IA suele omitir.

### B. Clasificación por Siglas y Formateo de Texto (Base Online)
**Ubicación:** `sites/base_online/flows/p1.py`
- **Uso:** Específico para el organismo BASE (Tarragona).
- **Lógica:** Valida las siglas de la vía contra un set estricto de 2 letras (`_SIGLES_PERMESES`) como AG, AL, AV, etc.
- **Formateo:** Reconstruye la dirección completa en un bloque de texto multilínea siguiendo un patrón postal estricto para su inserción en formularios.

### C. Normalización y Búsqueda Semántica (Madrid)
**Ubicación:** `sites/madrid/flows/formulario.py`
- **Normalización de Autocomplete:** Función `_normalizar_texto_autocomplete` que elimina acentos pero **preserva la Ñ** (usando normalización NFD y filtrado selectivo de categorías Mn).
- **Limpieza de Preposiciones:** Función `_texto_busqueda_nombre_via` que elimina partículas al inicio (DE, DEL, LA, EL, LOS, LAS) para mejorar los resultados en buscadores de calles con autocompletado de la administración.

### D. Clasificación Heurística (Fallback Manual)
**Ubicación:** `core/address_classifier.py` (`classify_address_fallback`)
- **Uso:** Actúa como red de seguridad si la API de Groq falla o no hay conexión.
- **Lógica:** Mapeo manual de abreviaturas (`CL` -> `CALLE`, `AVDA` -> `AVENIDA`) y extracción de números mediante expresiones regulares.

---

## 2. Inferencia de Localizaciones mediante Código Postal (CP)

El proyecto implementa lógica para deducir datos geográficos a partir de información parcial, esencial para completar formularios donde solo se dispone del CP.

### Inferencia de Provincia e Isla
**Ubicación:** `identificacion conductor.py`
- **Lógica de 2 Dígitos:** Mapeo de los dos primeros dígitos del CP a las 52 provincias españolas.
- **Excepciones Insulares (3 Dígitos):**
  - **Baleares (07):** Identifica Mallorca (070-076), Menorca (077) e Ibiza/Formentera (otros).
  - **Las Palmas (35):** Identifica Gran Canaria (350-354), Lanzarote (355) y Fuerteventura (otros).
  - **S.C. Tenerife (38):** Identifica Tenerife (380-386), La Palma (387), La Gomera (388) y El Hierro (otros).

---

## 3. Validaciones y Necesidades Cubiertas

### Necesidades que cubren estas funcionalidades:
1. **Normalización de Entrada:** Convierte texto libre de usuarios en datos estructurados que el sistema puede mapear a selectores HTML de tipo de vía.
2. **Corrección de "Dirección Sucia":** (`core/validation/validators.py`) Detecta si el nombre de la calle incluye el número (ej: "Serrano 42" en campo calle y número vacío) para forzar un re-procesado.
3. **Consistencia Geográfica:** (`core/validation/geo_data.py`) Verifica que la ciudad introducida sea válida para la provincia seleccionada, evitando errores de validación en el servidor de la administración.
4. **Optimización de Búsqueda:** Al eliminar preposiciones y normalizar caracteres, aumenta la tasa de éxito en los desplegables de autocompletado de las sedes electrónicas.
5. **Autocompletado Proactivo:** Infiere la provincia a partir del CP para reducir la carga de datos y errores manuales.

---

## 4. Conclusión: Diseño de la API de Geolocalización

Para sustituir toda la lógica dispersa en el proyecto por un único servicio de API, se requerirían los siguientes endpoints:

### Endpoints de Clasificación y Parsing
- `POST /v1/address/parse`:
  - **Input:** String de dirección.
  - **Output:** Objeto estructurado (`tipo_via`, `calle`, `numero`, `bloque`, etc.).
  - **Lógica:** Integraría Groq LLM con el catálogo de tipos de vía y la restauración de grafía (Ñ, tildes).
- `POST /v1/address/normalize-search`:
  - **Input:** String de calle.
  - **Output:** String optimizado para búsqueda (sin preposiciones, sin acentos pero con Ñ).

### Endpoints de Inferencia y Datos Maestros
- `GET /v1/geo/postal-code/{cp}`:
  - **Output:** Provincia, Isla (si aplica), Comunidad Autónoma.
- `GET /v1/geo/provinces`: Lista de todas las provincias.
- `GET /v1/geo/municipalities?province_id={id}`: Lista de municipios.
- `GET /v1/geo/street-types`: Catálogo oficial de tipos de vía con sus abreviaturas comunes y equivalencias de 2 letras (siglas BASE).

### Endpoints de Validación
- `POST /v1/address/validate`:
  - **Input:** Objeto de dirección.
  - **Checks:**
    - ¿La calle contiene números? (Dirección sucia).
    - ¿El municipio pertenece a la provincia?
    - ¿El CP es válido para esa provincia?
  - **Output:** Boolean + Lista de advertencias/errores.
