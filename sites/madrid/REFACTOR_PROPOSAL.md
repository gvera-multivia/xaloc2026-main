# Propuesta de Refactorización - Madrid

Aunque el sitio `madrid` ya cuenta con una clase `MadridConfig` extensa que centraliza la mayoría de los selectores, el código aún presenta oportunidades de mejora para aumentar la legibilidad y la estructura.

## 1. Análisis del Estado Actual

La configuración (`config.py`) es una lista plana muy larga de atributos. Esto dificulta encontrar configuraciones específicas y contamina el espacio de nombres de la clase. Además, aún persisten "números mágicos" y timeouts hardcodeados directamente en la lógica de navegación.

## 2. Valores Hardcodeados Identificados

### Timeouts Ad-Hoc
En `flows/navegacion.py`:
```python
await _esperar_dom_estable(page, timeout_ms=2000)
await page.wait_for_timeout(int(getattr(config, "delay_ms", 500)))
await page.wait_for_selector(..., timeout=6000) # "Solo 5 segundos" (comentario vs código)
await _esperar_auth_o_servcla(..., timeout_ms=15000)
```

### URLs y Patrones
Aunque algunos están en config, otros strings de lógica de negocio o logging están dispersos.

## 3. Propuesta de Refactorización

### Reestructuración de la Configuración (Nesting)
Agrupar los selectores y configuraciones en subclases lógicas dentro de `MadridConfig`.

```python
from dataclasses import dataclass

@dataclass
class MadridSelectorsLogin:
    iniciar_tramitacion: str = "#btn_tramitar"
    certificado_login: str = "a[href*='loginCertificado']"
    continuar_post_auth: str = "input[value='Continuar']"

@dataclass
class MadridSelectorsForm:
    expediente_input: str = ".formula2_EXP1"
    # ... resto de campos del formulario

@dataclass
class MadridTimeouts:
    default: int = 30000
    navigation: int = 60000
    auth_wait: int = 15000
    dom_stable: int = 2000
    short_wait: int = 500

@dataclass
class MadridConfig(BaseConfig):
    # Agrupación jerárquica
    selectors_login: MadridSelectorsLogin = MadridSelectorsLogin()
    selectors_form: MadridSelectorsForm = MadridSelectorsForm()
    timeouts: MadridTimeouts = MadridTimeouts()

    # ...
```

### Eliminación de Números Mágicos
Reemplazar llamadas explícitas por referencias a la configuración:

*Antes:*
```python
await page.wait_for_selector(config.boton_nuevo, timeout=6000)
```

*Después:*
```python
await page.wait_for_selector(
    config.selectors.boton_nuevo,
    timeout=config.timeouts.short_interaction # 6000
)
```

## 4. Beneficios
1.  **Organización**: IDEs ofrecerán autocompletado lógico (`config.selectors.form.` vs una lista de 100 items).
2.  **Consistencia**: Evita discrepancias entre comentarios y código (ej: el timeout de 6000ms documentado como 5s).
3.  **Escalabilidad**: Facilita añadir nuevas secciones al formulario sin saturar la raíz de la configuración.
