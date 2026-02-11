# Propuesta de Refactorización - Base Online

Este documento detalla las áreas de mejora identificadas en el código del sitio `base_online` y propone una estructura de configuración para centralizar valores hardcodeados, mejorando la legibilidad y el mantenimiento.

## 1. Análisis del Estado Actual

El código actual contiene numerosos valores "hardcodeados" dispersos a lo largo de los módulos de flujo (`flows/*.py`) y la automatización principal. Esto incluye:
- Selectores CSS/XPath complejos.
- Tiempos de espera (timeouts) explícitos en llamadas a métodos de Playwright.
- Fragmentos de código JavaScript inyectados.
- Cadenas de texto para logs y valores por defecto.

## 2. Valores Hardcodeados Identificados

A continuación se presentan ejemplos específicos encontrados en el código:

### Timeouts y Esperas
En `flows/login.py` y `flows/p1.py`:
```python
await page.wait_for_selector(..., timeout=5000)
await page.wait_for_function(..., timeout=10000)
```

### Selectores
Los selectores están dispersos en la lógica, lo que dificulta su actualización si la web cambia.
```python
# flows/login.py
"#form_0\\:llistaMunicipis, #form_0\\:llistaPais, #form_0\\:llistaProvincia"
"input[type='submit'][value*='Continuar' i]"

# flows/p1.py
"#form\\:clau_expedient_id_ens"
"input[type='submit'][name='form:j_id20'][value='Continuar']"
```

### Scripts JavaScript
Bloques de JS incrustados directamente en cadenas de texto:
```python
"""
() => {
  const cpSel = document.querySelector('#form_0\\:llistaCP');
  return !!cpSel && cpSel.options && cpSel.options.length > 1;
}
"""
```

### Valores por Defecto y Magic Strings
```python
pais = address.get("pais") or "ESP"
sigla = address.get("sigla") or "CL"
addr["numero"] = "S/N"
```

## 3. Propuesta de Refactorización

Se propone centralizar estos valores en una estructura de configuración tipada, utilizando `dataclasses` o `Pydantic`. Esto debería integrarse en `config.py`.

### Estructura Propuesta

```python
from dataclasses import dataclass

@dataclass
class BaseOnlineTimeouts:
    selector_default: int = 5000
    popup_load: int = 10000
    ajax_idle: int = 3000

@dataclass
class BaseOnlineSelectors:
    # Login
    login_user_input: str = "#user"
    login_pass_input: str = "#pass"

    # Formulario P1
    p1_expedient_id: str = "#form\\:clau_expedient_id_ens"
    p1_btn_continuar: str = "input[type='submit'][name='form:j_id20'][value='Continuar']"

    # Popup Dirección
    popup_pais: str = "#form_0\\:llistaPais"
    popup_municipio: str = "#form_0\\:llistaMunicipis"

@dataclass
class BaseOnlineScripts:
    check_cp_loaded: str = """
        () => {
          const cpSel = document.querySelector('#form_0\\:llistaCP');
          return !!cpSel && cpSel.options && cpSel.options.length > 1;
        }
    """

@dataclass
class BaseOnlineDefaults:
    default_country: str = "ESP"
    default_street_type: str = "CL"
    default_number: str = "S/N"

@dataclass
class BaseOnlineConfig:
    # Configuración existente...
    timeouts: BaseOnlineTimeouts = BaseOnlineTimeouts()
    selectors: BaseOnlineSelectors = BaseOnlineSelectors()
    scripts: BaseOnlineScripts = BaseOnlineScripts()
    defaults: BaseOnlineDefaults = BaseOnlineDefaults()
```

### Beneficios
1.  **Mantenibilidad**: Si un ID cambia en la web, solo se actualiza en `config.py`.
2.  **Legibilidad**: El código de automatización leerá `self.config.selectors.p1_btn_continuar` en lugar de una cadena larga y críptica.
3.  **Reutilización**: Los scripts y tiempos pueden reutilizarse en diferentes partes del flujo.

## 4. Pasos Siguientes
1.  Crear las clases de configuración en `sites/base_online/config.py`.
2.  Refactorizar `flows/login.py`, `flows/p1.py`, etc., para importar y usar esta configuración en lugar de los valores hardcodeados.
