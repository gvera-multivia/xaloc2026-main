# Investigación profunda: firmado/autenticación con certificado en Docker Linux con Playwright y por qué se queda “colgado” en el selector

## Contexto y síntoma observado

El patrón que describes (en **Windows** funciona en tu ordenador, pero en **Docker Linux** se queda en la pantalla tipo “¿qué certificado quieres usar?” y no avanza) encaja con el caso clásico de **TLS Client Authentication / mTLS** en navegadores basados en Chromium: el servidor solicita un certificado cliente durante el *handshake* TLS y, si el navegador no puede elegirlo automáticamente, muestra un *certificate chooser* (una UI del navegador, fuera del DOM). Esto es especialmente problemático en automatización: Playwright no puede “clickar” ese selector como si fuera HTML, porque no es un `<div>` de la página sino una ventana/diálogo propio del navegador (y en headless histórico, directamente falla o se queda sin completar el handshake). citeturn16view0turn2view1turn9view1

A partir de aquí, los dos grandes ejes del problema suelen ser:

- **El certificado no está realmente disponible en el “almacén” que usa ese Chromium dentro del contenedor**, o no está confiada la cadena/intermedia/CA en NSS, o se está ejecutando con otro “perfil”/HOME distinto al que tú crees. citeturn2view1turn10search3turn10search6  
- **La auto-selección (política `AutoSelectCertificateForUrls`) no está aplicada**, está mal formateada/ubicada, o no filtra lo suficiente y Chromium insiste en mostrar el selector. citeturn14view0turn15view0turn11view1  

En tu diagnóstico ya aparece un factor que agrava muchísimo todo esto: *profile lock* + “fallback a perfil temporal clonado”. Cualquier salto de perfil/HOME puede destruir la premisa “he importado el PFX en el lugar correcto” y también hace difícil asegurar que la política efectiva sea la que tú has escrito.

## Cómo funciona la autenticación por certificado en Chromium en Linux y por qué se atasca con automatización

### El selector de certificado no es “automatizable” como DOM

Cuando un servidor requiere certificado cliente (mTLS), envía un `CertificateRequest` en el handshake. En modo “normal”, Chromium puede:

- auto-elegir un certificado si hay reglas/políticas y un único candidato, o
- pedir intervención del usuario con un diálogo para elegir certificado.

Ese diálogo **no está expuesto como un prompt DOM estándar** y no hay un API general en CDP/Playwright para “seleccionar certificado” dentro del diálogo (históricamente fue un hueco muy comentado; de ahí que Playwright añadiera una vía alternativa: **pasar el certificado al contexto**). citeturn16view0turn14view0turn19view1

### El papel de `AutoSelectCertificateForUrls`

La política `AutoSelectCertificateForUrls` (en Chrome/Chromium/Edge) permite decir: “para este patrón de URL, selecciona automáticamente un certificado que cumpla este filtro”. Importante:

- El **tipo de dato es una *lista de strings***, y cada elemento es un **JSON “stringificado”** con `pattern` y `filter`. Esto no es un detalle menor: si lo escribes como “lista de objetos JSON” (sin escapado) puedes quedarte con una política silenciosamente ignorada o con error de esquema. citeturn14view0turn15view0  
- El filtro **no fuerza un certificado que el servidor no acepte**. Incluso con filtro `{}`, “solo se consideran” certificados que encajen con la `CertificateRequest` del servidor (por CA aceptadas, EKU, etc.). citeturn15view0  

### Headless: pasado y presente

Durante años, fue relativamente común que **headless “antiguo”** no respetara bien ciertas políticas/flows de certificados y que la conexión fallase o no se seleccionara el certificado (hay reportes en Selenium/Puppeteer y foros). citeturn9view0turn9view1turn1view7  

Desde **Chrome/Chromium 112**, existe “new headless” unificado con headful (mismo código, sin limitaciones funcionales), y Google ha ido retirando el headless antiguo del binario principal. citeturn9view3turn9view2  

En la práctica: hoy **sí** puede hacerse mTLS en headless si (a) el certificado está en NSS correctamente y (b) hay una regla de auto-selección aplicable o se pasa el certificado al contexto. citeturn2view2turn19view1

## Hipótesis de causa raíz más probables en tu runner Docker

A partir de tu descripción (NSS + policy + Playwright + Docker + locks), estas son las causas que más a menudo explican “se queda en el selector y no avanza” en Linux:

### Ruta de políticas equivocada por el cambio a Chrome for Testing en Playwright

Desde Playwright **1.57**, Playwright pasó de usar “Chromium” a usar **Chrome for Testing** por defecto (también en Python). citeturn18view0turn11view0  

Eso es crítico porque, en Linux, Chromium documenta **directorios base distintos** para políticas según el tipo de build:

- `/etc/chromium/policies` para builds Chromium,
- `/etc/opt/chrome/policies/` para Chrome oficial,
- `/etc/opt/chrome_for_testing/policies/` para Chrome for Testing. citeturn11view1  

Si tu entrypoint escribe siempre en `/etc/chromium/policies/managed` pero en runtime el binario real es “Chrome for Testing”, el navegador **no leerá** tu política (y te aparecerá el chooser). Esta hipótesis encaja extraordinariamente bien con “en Windows funcionaba / antes funcionaba / en Docker no”, porque el entorno Docker y la versión pueden haber cambiado sin que el “script de políticas” se adaptara.

### Formato de `AutoSelectCertificateForUrls` incorrecto o mal escapado

La definición de la política en los templates de Chromium muestra claramente el `example_value` como una lista con un string JSON escapado. citeturn14view0  

Además, hay casos reales donde un carácter (por ejemplo comillas dentro del CN/Issuer) rompe el JSON stringificado y la política queda con error de esquema. citeturn12search2  

Si el policy file existe pero el valor no pasa validación, el síntoma práctico es igual: el navegador se comporta como si no existiera y muestra el selector.

### El filtro no “identifica” un certificado único o no coincide con lo que el servidor pide

La política no selecciona “por nombre interno del certificado” de forma universal; filtra por atributos del certificado (ISSUER/SUBJECT y campos como CN/O/OU/L) y, aun así, **solo puede elegir** dentro de los certificados aceptables para el servidor. citeturn15view0turn14view0  

Si en tu NSS hay más de un certificado candidato, o si tu filtro no coincide exactamente (CN distinto, OU duplicadas, etc.), Chromium puede seguir pidiendo selección manual.

### El certificado está importado en NSS, pero no en el NSS que usa *ese* proceso

En Linux, la forma típica de hacer que Chromium vea certificados cliente es importarlos en un **NSS DB** accesible para el navegador; muchas guías y ejemplos usan `sql:$HOME/.pki/nssdb` y `pk12util`. citeturn2view1turn2view4turn10search13  

Tu runner ya apunta a que hay *fallback* a un perfil temporal. Si ese fallback cambia `HOME`/user-data-dir o apunta a un directorio sin la `.pki/nssdb` con el certificado, Chromium se queda sin candidato real; puede mostrar chooser vacío, fallar el handshake o no redirigir. El “lock detectado” suele ser el origen de estos cambios de directorio.

### Falta de trust flags/cadena CA en NSS

Incluso si importas el `.pfx/.p12`, en escenarios mTLS es bastante común necesitar que la CA/intermedia esté considerándose “confiable” en NSS (trust flags). Un ejemplo explícito es ajustar flags con `certutil -M ... -t "C,,"` tras importar. citeturn2view1turn10search6  

Si la cadena no está bien, el certificado puede estar “instalado” pero Chromium no lo ofrece para el handshake o el servidor lo rechaza.

## Soluciones viables y comparadas

### Solución recomendada A: pasar el certificado desde Playwright con `client_certificates`

Desde Playwright **1.46**, Playwright permite suministrar certificados cliente a nivel de contexto (`browser.new_context()`), tanto para navegación como para API. citeturn19view1turn1view5turn16view0  

Esto es, en esencia, la solución “más limpia” para automatización porque:

- Evitas el selector UI (porque el stack TLS ya sabe qué cert presentar).
- Evitas depender de NSS/policies del sistema (menos fricción en contenedores).
- Puedes, en teoría, manejar diferentes certificados por contexto/origen sin tocar políticas globales del contenedor. citeturn19view1  

Ejemplo (Python, usando PFX en fichero):

```python
from playwright.sync_api import sync_playwright
import os

PFX_PATH = "/run/secrets/certificate.pfx"
PFX_PASSPHRASE = os.environ["CERT_PFX_PASSWORD"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        client_certificates=[
            {
                "origin": "https://valid.aoc.cat",
                "pfxPath": PFX_PATH,
                "passphrase": PFX_PASSPHRASE,
            }
        ]
    )
    page = context.new_page()
    page.goto("https://valid.aoc.cat/")
    # ... flujo ...
```

Puntos finos que suelen decidir el éxito/fracaso:

- `origin` debe ser **match exacto** de esquema+host (+puerto si aplica). Si el handshake real pasa por otro host (p.ej. `https://auth.valid.aoc.cat` o un reverse proxy diferente), necesitarás añadir otra entrada. citeturn1view5turn19view1  
- Si en tu flujo usas **proxy corporativo**, ha habido bugs/reportes en torno a certificados cliente y proxys, y a veces se necesita actualizar de versión (o aislar el problema sin proxy). citeturn1view4turn7view0  

En tu caso, esta vía también elimina gran parte de la complejidad de “perfil persistente + locks”, porque no dependes del almacén de certs del perfil para presentar el certificado al servidor.

### Solución recomendada B: arreglar la auto-selección con políticas y NSS, pero haciéndolo “a prueba de Playwright 1.57+”

Si por requisitos (p.ej. el criptográfico está en un token/hardware, o la entidad exige selección interactiva, o necesitáis simular comportamiento “real de navegador gestionado”) preferís continuar con NSS+policy, la solución robusta pasa por **tres garantías**: ruta correcta, formato correcto, y “NSS correcto para ese proceso”.

#### Asegurar la ruta correcta del policy file según el binario real

En Linux, Chromium documenta explícitamente las rutas base de políticas, incluyendo Chrome for Testing. citeturn11view1  

Dado que Playwright 1.57+ usa Chrome for Testing por defecto, una estrategia defensiva para Docker (si no queréis branching por versión) es escribir el mismo fichero en los tres destinos:

- `/etc/chromium/policies/managed/auto_select_cert.json`
- `/etc/opt/chrome/policies/managed/auto_select_cert.json`
- `/etc/opt/chrome_for_testing/policies/managed/auto_select_cert.json` citeturn11view1turn18view0  

Esto evita el “funcionaba hasta que actualizamos Playwright”.

#### Asegurar el formato correcto del valor

Fuentes “de plantilla” de Chromium dejan claro que `AutoSelectCertificateForUrls` es **tipo list**, y el ejemplo es una lista de strings con JSON escapado. citeturn14view0  

Además, Microsoft (para Edge, pero mismo motor de políticas) documenta la semántica del filtro y que el dato es “List of strings”. citeturn15view0  

Ejemplo de policy file correcto en Linux (nota: el JSON interno va como string escapado):

```json
{
  "AutoSelectCertificateForUrls": [
    "{\"pattern\":\"https://valid.aoc.cat\",\"filter\":{\"ISSUER\":{\"CN\":\"<CN_DE_LA_CA_EMISORA>\"},\"SUBJECT\":{\"CN\":\"<CN_DEL_CERT_CLIENTE>\"}}}"
  ]
}
```

Si tenéis caracteres especiales (comillas, barras) en CN/O/OU, revisad el escapado: hay casos donde un valor con comillas rompe el JSON y la política queda inválida. citeturn12search2  

#### Asegurar que el certificado está en el NSS que usa Chromium

`pk12util` está precisamente pensado para **importar certificados y claves desde PKCS#12 (p12/pfx) a “security databases” de NSS**. citeturn10search3turn10search7turn2view1  

`certutil` permite crear y modificar bases de datos de certificados y llaves (incluye listar y ajustar). citeturn10search6turn2view1  

En muchos setups (incluido Docker) la ruta de facto para Chrome/Chromium es:

- NSS DB: `sql:$HOME/.pki/nssdb` citeturn2view4turn10search13  

Comandos típicos para validar en el contenedor (antes de ejecutar Playwright):

```bash
# Ver certificados presentes
certutil -d sql:$HOME/.pki/nssdb -L

# Importar p12/pfx
pk12util -i /path/certificate.pfx -d sql:$HOME/.pki/nssdb -W "$PFX_PASSWORD"
```

Si necesitáis ajustar confianza de CA/intermedia, un patrón documentado es usar `certutil -M` para establecer trust flags. citeturn2view1  

#### Concurrencia y locks: el “talón de Aquiles” del enfoque policy+NSS

Un punto clave (y muy alineado con tu *profile lock*): la política `AutoSelectCertificateForUrls` es una configuración de nivel “sistema/gestión”; un autor que documenta mTLS en headless señala como limitación que no puedes (fácilmente) tener políticas distintas por cada browser si conviven en el mismo host/contenedor, y propone como workaround usar **`HOME` distinto por instancia** para que cada instancia vea un NSS DB distinto con un solo certificado. citeturn2view2turn2view1  

Si tu runner ejecuta múltiples jobs concurrentes con diferentes certificados, el enfoque policy+NSS **se vuelve frágil** salvo que:

- restrinjáis concurrencia por certificado/perfil, o
- separéis por contenedor (un contenedor por job/cert), o
- migréis a `client_certificates` por contexto (Solución A). citeturn2view2turn19view1  

### Solución C: ejecutar “headed” en Docker (Xvfb/noVNC) como herramienta de diagnóstico, no como solución final

Para depurar el punto exacto (si existe selector, si aparece error de certificado, si hay pantalla intermedia), la vía más directa es lanzar el navegador **headed** dentro del contenedor usando un servidor X virtual. La propia documentación de Playwright indica que en agentes Linux “headed execution requires Xvfb” y sugiere ejecutar con `xvfb-run`. citeturn3search15turn7view5  

Esto no sustituye un fix (porque en producción CI querer “headful” no es ideal), pero sí te da evidencia visual inmediata.

## Observabilidad práctica dentro de Docker sin necesidad de “ver” el popup

image_group{"layout":"carousel","aspect_ratio":"16:9","query":["Playwright Trace Viewer screenshot","Chrome client certificate selection dialog","noVNC web VNC interface screenshot"],"num_per_query":1}

### Trazas de Playwright

Aun cuando el selector de certificado sea una UI del navegador, las trazas de Playwright siguen siendo muy útiles para:

- ver la secuencia exacta de navegación/redirecciones,
- ver en qué URL/acción se queda el flujo,
- inspeccionar requests/responses y snapshots alrededor del “click” del login. citeturn7view3  

Playwright documenta cómo grabar trazas y abrirlas localmente (`playwright show-trace trace.zip`) o en el visor web (`trace.playwright.dev`). citeturn7view3  

### NetLog de Chromium para confirmar si *realmente* se envía el certificado al servidor

Para mTLS, el dato más determinante es: **¿el navegador envía un `Certificate` en el handshake tras `CertificateRequest`?** Si no, da igual lo que pase en el DOM: el login no avanzará.

Chromium recomienda NetLog (`chrome://net-export`) y también soporta logging desde arranque con flags `--log-net-log=...` y `--net-log-capture-mode=IncludeSensitive/Everything`. citeturn9view5turn9view7  

El modo `IncludeSensitive` se usa precisamente para incluir cookies/credenciales sin volcar cuerpos completos, según guías de captura de NetLog. citeturn9view6turn9view5  

Aplicación a tu runner: añadir a los args de Chromium algo como:

- `--log-net-log=/tmp/netlog.json`
- `--net-log-capture-mode=IncludeSensitive`

y persistir `/tmp/netlog.json` como artefacto del job. Si el NetLog muestra `CertificateRequest` sin respuesta de `Certificate`, la causa está en selección/presentación del cert (policy/NSS/client_certificates).

### Logs verbosos del navegador

Chromium documenta flags como `--enable-logging=stderr --v=1` para sacar logs a stderr. citeturn9view4  

Esto es útil para detectar:

- carga de políticas,
- errores de perfil,
- fallos de NSS,
- errores TLS más explícitos.

### Recomendaciones específicas para Docker/Playwright

La propia documentación oficial de Playwright sobre Docker remarca configuraciones recomendadas (por ejemplo `--ipc=host` para Chromium) y explica que, por defecto, el contenedor suele ejecutar como `root` y eso deshabilita sandbox. citeturn7view4  

No es la causa directa del selector, pero **sí** influye en estabilidad y en la trazabilidad de “qué HOME/perfil se está usando”, que en tu caso es central.

## Plan de cierre técnico orientado a tu caso `valid.aoc.cat` → STA

### Convertir el problema en un “test mínimo reproducible” dentro del contenedor

Antes de perseguir el flujo completo OIDC/STA, conviene aislar “mTLS funciona en este contenedor” con un endpoint que requiera certificado cliente.

Un repositorio público demuestra el patrón con `client.badssl.com` y `AutoSelectCertificateForUrls` como workaround para evitar el popup, además de usar `pk12util` para instalar el `.p12` en NSS. citeturn2view3turn2view4  

Aunque ese repo menciona limitaciones de headless, hay documentación más reciente que muestra que con “new headless” y política aplicada, mTLS puede funcionar en headless moderno. citeturn2view2turn9view3  

Este contraste es útil: si en tu contenedor el caso mínimo falla, el problema está en base (policy path, NSS, versión/headless).

### Prioridad de soluciones para tu arquitectura con concurrencia

- Si podéis adoptar Playwright ≥1.46 y mover el certificado al contexto (**Solución A**), es la vía con menos “magia” de sistema y menos impacto de locks/perfiles. citeturn19view1turn1view5turn16view0  
- Si necesitáis policy+NSS, el primer fix es “rutas de policy correctas para Chrome for Testing” (**Solución B**) + asegurar formato list-of-strings y escaping. citeturn11view1turn18view0turn14view0turn15view0  
- Para cerrar incertidumbre rápidamente, mantened un modo “headed de diagnóstico” con Xvfb/noVNC solo para reproducir y capturar evidencia. citeturn3search15turn7view5  

### Señales de éxito observables

Un cierre robusto no debería basarse solo en “ya navega”, sino en evidencias:

- En NetLog: ver `CertificateRequest` seguido de envío de `Certificate` del cliente en `valid.aoc.cat` durante el flujo. citeturn9view5turn9view7  
- En trazas Playwright: ver la cadena de redirecciones completarse y aterrizar en la URL de retorno a STA (sin bucles/errores). citeturn7view3  
- En runtime: ausencia del chooser (o, si aparece, confirmar visualmente que la política no está aplicada / el filtro no coincide). citeturn15view0turn14view0  

Con estos instrumentos, podrás distinguir con precisión si el bloqueo es “no se presenta certificado” (capa TLS/política/NSS) o “se presenta, pero el IdP/flow funcional cambia” (capa aplicación).