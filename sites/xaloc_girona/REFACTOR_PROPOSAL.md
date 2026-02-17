# Propuesta de Refactorización - Xaloc Girona

Este sitio presenta una configuración parcial (`XalocConfig`) pero mantiene lógica importante y valores constantes dentro de los flujos, especialmente en `login.py`.

## 1. Análisis del Estado Actual

El código mezcla la configuración básica (URLs, selectores principales) con constantes globales (`DELAY_MS`) y listas "quemadas" en el código (patrones de cookies). Además, se observan accesos a atributos de configuración mediante `getattr`, lo que sugiere que el modelo de datos no está completo o sincronizado con el uso.

## 2. Valores Hardcodeados Identificados

### Constantes y Listas
En `flows/login.py`:
```python
DELAY_MS = 500

posibles = [
    r"Acceptar",
    r"Aceptar",
    # ...
]
```

### Expresiones Regulares
Aunque `tramite_link_pattern` está en `config`, en `login.py` se vuelve a definir o usar de forma redundante:
```python
name=re.compile(
    r"Tramitaci[oó] en l[ií]nia|Tramitaci[oó]n en l[ií]nea",
    re.IGNORECASE,
)
```

### Timeouts Específicos
```python
await boton.first.click(timeout=1500)
await enlace.wait_for(state="visible", timeout=10000)
await boton_cert.wait_for(state="visible", timeout=15000)
```

## 3. Propuesta de Refactorización

### Estructura de Configuración Completa

Se propone expandir `XalocConfig` para incluir todos estos aspectos, eliminando constantes globales y listas ocultas.

```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class XalocSelectors:
    cert_button: str = "#btnContinuaCert, [data-testid='certificate-btn']"
    cookie_buttons: List[str] = field(default_factory=lambda: [
        r"Acceptar", r"Aceptar", r"Aceptar todo", r"Accept all"
    ])
    tramite_link_regex: str = r"Tramitaci[oó] en l[ií]nia|Tramitaci[oó]n en l[ií]nea"

@dataclass
class XalocTimeouts:
    # Heredar o componer con Timeouts base si existe
    cookie_click: int = 1500
    link_appear: int = 10000
    cert_button_appear: int = 15000
    login_process: int = 60000
    short_delay: int = 500

@dataclass
class XalocConfig(BaseConfig):
    # URLs
    url_base: str = "https://www.xalocgirona.cat/seu-electronica?view=tramits&id=11"
    url_post_login: str = "**/seu.xalocgirona.cat/sta/**"

    # Componentes
    selectors: XalocSelectors = XalocSelectors()
    timeouts: XalocTimeouts = XalocTimeouts()

    # Eliminar getattr(config, "delay_ms") y usar config.timeouts.short_delay
```

### Estandarización de Uso
Refactorizar `flows/login.py` para inyectar `config.selectors.cookie_buttons` en la lógica de aceptación de cookies, haciendo el flujo agnóstico a los textos específicos.

## 4. Beneficios
1.  **Centralización**: Si cambian los textos de las cookies o los botones de la web, solo se edita `config.py`.
2.  **Tipado Fuerte**: Elimina la necesidad de `getattr` y posibles errores de atributos faltantes.
3.  **Limpieza**: `login.py` se reduce a lógica pura, sin datos.
