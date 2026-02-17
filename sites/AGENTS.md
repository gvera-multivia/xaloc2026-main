# AGENTS.md – Instrucciones del agente para añadir/entender sitios Playwright

## 1. Visión general
- Este repositorio expone un núcleo común (`core/`) que maneja Playwright y perfiles persistentes, y `sites/` que agrupan automatizaciones concretas (config, datos, flujos y controladores).  
- Cada sitio comparte `core/base_automation.py`, `core/base_config.py` y `core/site_registry.py`, pero define sus selectores, modelos y pasos propios.  
- El agente debe actuar al estilo *GetShitDone*: interpretar rápidamente las instrucciones que llegan en lenguaje natural (selector/flujo), montar la estructura mínima que respete el patrón y validar la ejecución básica antes de cerrar el ticket. Se prioriza avance incremental, pruebas pequeñas y retroalimentación clara.

## 2. Sitios disponibles (referencia rápida)
- `sites/xaloc_girona`: autenticación con certificado, rellena STA y genera evidencias sin pulsar “Enviar”. Flujo completo hasta confirmación, evita el submit final.  
- `sites/base_online`: login con certificado y tres protocolos (`P1`, `P2`, `P3`). Cada protocolo tiene su `flow` y detiene en la pantalla “Signar i Presentar” sin firmar. Ya maneja adjuntos por parámetro (`--p1-file`, `--p2-file`, `--p3-file`).  
- `sites/madrid`: navegador hasta el formulario, completa la pantalla posterior (con campos y adjuntos) pero deja pendiente el envío y la subida real de documentos.  
- `sites/ayunta_palma`: autenticación inicial en un modal (iframe `#ventanaModal` y tabla `#optSsl`), luego rutas de “Nuevo/a interesado/a”, “Indicar representante” y un formulario de alegaciones dentro del mismo iframe. Este flujo usa selectores dinámicos, espera al `#velo`, rellena correos/teléfonos con `[Otro]` y sube un archivo vía el input oculto del modal de documentos (todo ello descrito en `ayunta-palma/doc/AyuntaPalma.md`).  
- La carpeta `sites/adapters` contiene helpers compartidos y `__init__.py` expone reexpotadores viejos para compatibilidad.

## 3. Flujo “GetShitDone” para incorporar un nuevo sitio
1. **Entender el encargo**: leer la descripción Playwright (URLs, autenticación, pantallas clave, campos obligatorios), identificar acciones en la misma secuencia en la que Playwright debe ejecutarlas.  
2. **Esquema mínimo**: crea `sites/<nuevo_site>/` con `config.py`, `data_models.py`, `controller.py`, `automation.py` y subcarpeta `flows/`. Copia el patrón de los sitios existentes (por ejemplo `steps = Login`, `navigate`, `form`, `adjuntos`).  
3. **Configurar selectores y datos**: en `config.py` define URLs, timeouts y selectores necesarios. En `data_models.py` describe los campos que recibirá el worker (identidad, datos del trámite, adjuntos).  
4. **Automation y flows**: extiende `core.BaseAutomation`, reutiliza `run_phase()` y estructura los pasos en `flows/*.py`. Cada flujo debe manejar errores (capturar screenshot/log, reintentar cuando sea crítico).  
5. **Controlador y registro**: `controller.py` define `site_id` y expone `get_controller()`. Añade el sitio en `core/site_registry.py` para que `main.py` pueda seleccionarlo.  
6. **Comprobar ejecución básica**: lanza `python main.py --site <nuevo_site>` en modo visible o `--headless` si no hay bloqueos; valida que llegue al último paso seguro sin enviar datos y que genere logs/screenshot previstos.

## 4. Guía práctica para Playwright-specific instructions
- Usa `async`/`await` y arranca el navegador mediante `core.base_automation`. Cada sitio debe usar el `BrowserConfig` (perfiles persistentes y timeouts personalizados).  
- Prioriza la reutilización de `core/base_automation` para manejar contextos, captura automática de screenshots y logs (`logs/<site_id>.log`, `screenshots/`).  
- Cada `flow` debe ser pequeño, nominativo (login, navegación, formulario, adjuntos, confirmación) y debe exponer funciones claramente documentadas para poder escribir pruebas unitarias o snippet de validación.  
- Documenta cualquier comportamiento no obvio (popups de certificados, stops antes de enviar, pasos manuales) directamente en el `flow` o en un `README` dentro del sitio nuevo.

## 5. Checklist posterior a la integración
- Registrar el sitio en `core/site_registry.py` y verificar que `main.py --site <sitio>` enumera la opción.  
- Añadir entradas a `logs/` y `screenshots/` durante la validación (el agente puede describir qué capturas y con qué nombre) y confirmar que el worker respeta las paradas (“no enviar”).  
- Crear una breve nota (README o comentario en `AGENTS.md`) que explique el flujo principal y las diferencias con los sitios existentes.  
- Si hay requisitos adicionales (adjuntos, firmas, autenticar certificados), dejar claros los comandos de ejemplo (`python main.py --site ... --protocol ...`) y las variables de entorno necesarias.

## 6. Qué hacer cuando te entregan un “Playwright prompt”
- Extrae los pasos principales (login, navegación, formulario, botón de envío) en orden.  
- Identifica datos obligatorios (DNI, CIF, adjuntos) y cómo deben llegar al worker (vars/arguments).  
- Traduce los pasos a `flows/*.py` con nombres descriptivos y añade aserciones intermedias (await `page.wait_for_selector(...)`).  
- Verifica que el nuevo flujo no rompe el patrón “no enviar” si es necesario (detenerse antes de `click(Enviar)` y documentarlo).  
- Finaliza con un breve resumen en el ticket/nuevo `README` de sitio y lista los comandos de validación que ejecutaste.

## 7. Seguridad y mantenimiento
- Los certificados digitales pueden activar popups; la política de `AutoSelectCertificateForUrls` debe replicarse si la navegación es similar a `xaloc_girona`.  
- Mantén las evidencias en `logs/` y `screenshots/` alusivas al `site_id`.  
- Si se reutilizan flujos o adaptadores (p. ej. `flows/login_cert.py`), documenta la dependencia para futuras refactorizaciones.
