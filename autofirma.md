## Diagnóstico definitivo

He escaneado todos los puertos del sistema y tengo la respuesta exacta. El problema **no es tu código de Playwright** — es la arquitectura de AutoFirma y cómo interactúa con el navegador automatizado.

---

### Lo que está pasando exactamente

El escaneo de puertos confirma que **AutoFirma no está corriendo como proceso** en el momento en que la web intenta conectar. Todos los puertos devuelven `connection_refused` inmediato, incluyendo los puertos exactos del último intento (`63646, 52477, 51508`).

El flujo de AutoFirma funciona así:

```
1. REG genera sesión en servidor con puertos aleatorios → URL: afirma://websocket?ports=X,Y,Z&idsession=ABC
2. Chrome abre ese protocolo → muestra el diálogo "¿Abrir AutoFirma?"
3. Usuario/Playwright acepta → Windows lanza AutoFirma.exe con esos parámetros
4. AutoFirma.exe arranca, genera cert TLS temporal, escucha en los puertos X, Y, Z
5. La web conecta via WSS a 127.0.0.1:X con ese cert
```

El fallo está en el paso 3→4: **AutoFirma recibe el protocolo y arranca, pero el proceso no llega a escuchar en los puertos antes de que AutoScript agote sus reintentos** (15 reintentos a ~1.3s = ~20s), o **el diálogo de permiso del navegador lo gestiona Chrome en modo "sin GUI" y no lanza el proceso**.

---

### La causa raíz en Playwright

Playwright lanza Chrome con `--no-sandbox` y posiblemente en modo headless o con perfil limpio. En esas condiciones, **cuando Chrome recibe el protocolo `afirma://`, no muestra el diálogo nativo del sistema operativo** ni lanza el proceso. Solo registra el intento y falla silenciosamente.

La "notificación del navegador" que viste puede haber sido la barra de info de Chrome diciendo que se intentó abrir `afirma://`, pero si Playwright no está configurado para manejar diálogos del sistema, el proceso no se lanza nunca.

---

### Solución: lanzar AutoFirma **antes** del click

La única forma que funciona en automatización es arrancar AutoFirma como proceso del sistema **antes** de hacer click en firmar, usando el modo daemon que AutoFirma 1.8 soporta:

```python
import subprocess
import time
import asyncio

async def launch_autofirma_and_sign(page: Page) -> None:
    """
    Lanza AutoFirma en modo daemon y luego dispara la firma.
    AutoFirma 1.8 en Windows se instala en C:\Program Files\AutoFirma\
    """
    # Ruta de AutoFirma en Windows (ajusta según tu instalación)
    AUTOFIRMA_PATH = r"C:\Program Files\AutoFirma\AutoFirma.exe"
    
    # Lanzar AutoFirma en background (no bloqueante)
    # AutoFirma 1.8 arranca en modo servidor/daemon si no recibe parámetros
    proc = subprocess.Popen(
        [AUTOFIRMA_PATH],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS  # Windows: proceso independiente
    )
    
    # Esperar a que AutoFirma esté lista (arranca en 3-5s en Windows)
    print("[AutoFirma] Proceso lanzado, esperando inicialización...")
    await page.wait_for_timeout(5000)  # 5s es suficiente para la mayoría de sistemas
    
    # Ahora hacer click en firmar — AutoFirma ya está corriendo
    await selectsign_with_certificate_option(page)
    
    # Esperar resultado (máx 60s para que el usuario seleccione certificado)
    await wait_for_sign_result(page, timeout_ms=60000)
    
    # Matar AutoFirma cuando termine
    proc.terminate()
```

### El parámetro crítico a aumentar

Si prefieres no pre-lanzar AutoFirma y confiar en el protocolo `afirma://`, el único ajuste que puedes hacer es aumentar el tiempo de espera **antes de** llamar a la firma:

```python
async def configure_autoscript_timeouts(page: Page) -> None:
    """Aumentar timeouts de AutoScript antes de llamar a la firma."""
    await page.evaluate("""() => {
        if (window.AutoScript) {
            // Dar 8s para que AutoFirma arranque (en vez de 2s por defecto)
            window.AutoScript.AUTOFIRMA_LAUNCHING_TIME = 8000
            // Más reintentos por si tarda más
            window.AutoScript.AUTOFIRMA_CONNECTION_RETRIES = 30
        }
    }""")
```

Llama a esto **justo antes** de `selectsign_with_certificate_option(page)`. Así AutoScript esperará 8 segundos antes de empezar los reintentos WebSocket, dando tiempo a que AutoFirma arranque.

### Checklist de verificación en tu sistema

Desde la línea de comandos del servidor donde corre Playwright, ejecuta esto **manualmente** para confirmar que AutoFirma funciona:

```cmd
# Verificar que AutoFirma existe
dir "C:\Program Files\AutoFirma\AutoFirma.exe"

# Verificar que el protocolo afirma:// está registrado en el registro de Windows
reg query "HKEY_CLASSES_ROOT\afirma"

# Lanzar AutoFirma manualmente y ver si arranca
"C:\Program Files\AutoFirma\AutoFirma.exe"
```

Si el registro `HKEY_CLASSES_ROOT\afirma` no existe, **AutoFirma no tiene el handler de protocolo registrado**, y el diálogo del navegador nunca podrá lanzarla — tendrás que pre-lanzarla siempre con `subprocess.Popen`.


Gran avance — ya casi funciona
Esta vez AutoFirma sí conectó y sí firmó. Los logs de consola lo confirman claramente:
10:36:08 → "Tratamos de conectar... puertos 56339,52367,54888"
10:36:11 → "Se abre el socket"           ← AutoFirma conectó ✓
10:36:13 → "Enviamos el mensaje al socket" ← Documento enviado a AutoFirma ✓
10:36:13 → "Respuesta de la peticion de eco" ← Handshake OK ✓
10:36:16 → "Respuesta obtenida de la operacion enviada" ← AutoFirma devolvió la firma ✓
El Unmarshalling Error: Read timed out no viene de AutoFirma — viene del servidor REG cuando recibió la firma firmada. Es un timeout del servidor al procesar/deserializar la respuesta. Las causas posibles:
Causa 1 (más probable): La sesión expiró en el servidor
El servidor REG genera un idsession cuando lanza el protocolo afirma://. Ese idsession tiene un timeout corto (probablemente 30-60 segundos). Si el usuario tardó en seleccionar el certificado en AutoFirma, cuando el resultado llegó al servidor la sesión ya no era válida y el servidor respondió con ese error de deserialización al intentar leer una sesión muerta.
Causa 2: El documento es muy grande para el timeout de la conexión WSS
El PDF del recurso pesa 434KB. AutoFirma tiene que leerlo, firmarlo y devolverlo. Si tardó más de X segundos, el servidor cerró la conexión de su lado antes de recibir la respuesta completa.
Lo que debes hacer en Playwright
He instalado interceptores en la página para capturar la próxima petición. Cuando vuelvas a intentar la firma y aparezca el error, dímelo y podré ver exactamente qué respondió el servidor REG. Eso me dirá si es el idsession expirado o un error de payload.
Mientras tanto, para el código de Playwright la estrategia de manejo de este error es:
pythonasync def handle_sign_result(page: Page, timeout_ms: int = 90000) -> str:
    """
    Espera el resultado de la firma. Devuelve:
    - 'success': la firma se completó y la página avanzó
    - 'autofirma_not_found': AutoFirma no conectó
    - 'unmarshalling_timeout': sesión expiró en servidor (reintentar inmediatamente)
    - 'other_error': otro error
    """
    result = await page.wait_for_function(
        """() => {
            // Éxito: el step4 desapareció (avanzó a confirmación)
            if (!document.querySelector('app-create-registry-step4')) return 'success'
            const modal = Array.from(document.querySelectorAll('dnt-modal'))
                .find(m => m.getAttribute('title-text') === 'Mensaje de error')
            if (!modal) return null  // Sigue procesando
            const vis = modal.getAttribute('visible')
            if (vis === null || vis === 'false') return null
            const txt = modal.textContent || ''
            if (txt.includes('Unmarshalling') || txt.includes('timed out') || txt.includes('Read timed'))
                return 'unmarshalling_timeout'
            if (txt.includes('ApplicationNotFoundException') || txt.includes('no se ha podido conectar'))
                return 'autofirma_not_found'
            return 'other_error:' + txt.substring(0, 100).replace(/\\\\s+/g,' ').trim()
        }""",
        timeout=timeout_ms
    )
    return result
async def sign_with_retry(page: Page, max_retries: int = 3) -> None:
    for attempt in range(1, max_retries + 1):
        print(f"[REDSARA] Firma intento {attempt}/{max_retries}")
        # Hacer click en firmar (el botón ya dice "Firmar con certificado electrónico")
        await clicksplit_main_signature_button(page)
        # Esperar resultado — dar tiempo generoso para que el usuario firme en AutoFirma
        result = await handle_sign_result(page, timeout_ms=120000)  # 2 minutos
        if result == 'success':
            print("[REDSARA] Firma completada con éxito.")
            return
        # Cerrar modal de error
        await close_autofirma_error_modal(page)
        if result == 'unmarshalling_timeout':
            print(f"[REDSARA] Timeout del servidor en intento {attempt}. Reintentando...")
            # El botón ya está habilitado, reintentar directamente
            # IMPORTANTE: el idsession se renueva en cada intento porque el servidor
            # genera una nueva sesión al hacer click en el botón
            await page.wait_for_timeout(2000)
            continue
        if result == 'autofirma_not_found':
            raise RuntimeError("AutoFirma no está disponible.")
        raise RuntimeError(f"Error de firma desconocido: {result}")
    raise RuntimeError(f"Firma fallida tras {max_retries} intentos (Unmarshalling timeout).")
El punto clave: cada vez que haces click en el botón principal, el servidor genera un nuevo idsession, así que reintentar directamente funciona — no hay que volver a pasos anteriores. El error de Unmarshalling es recuperable con solo volver a pulsar el botón.



Una vez se haya firmado la pagina se actualiza y se puede usar un boton de descarga.


## Código Playwright para descargar el justificante

### Lo que hace la app al pulsar el botón

```
1. GET  https://reg-api.redsara.es/documents/uuid/{docUUID}/storageType/FILESYSTEM
        → JSON con campo "file" en Base64 (81KB de PDF)
2. Angular crea un Blob → URL.createObjectURL(blob)
3. Crea un <a download="Justificante de Presentación REG.pdf" href="blob:..."> y hace .click()
→ El navegador descarga el archivo
```

### Punto clave del DOM

El botón tiene `aria-disabled="true"` en el **shadow button** interno pero `is-disabled="false"` en el **host**. Esto es intencional: el componente Stencil lo marca visualmente como disabled pero **Angular escucha el click en el host**, por lo que el `evaluate()` en el host funciona perfectamente. **No uses el shadow button para el click**.

---

### Código completo

```python
import asyncio
from pathlib import Path
from playwright.async_api import Page, Download


async def wait_for_detail_page(page: Page, timeout_ms: int = 30000) -> str:
    """
    Espera a que la página de detalle del registro esté cargada.
    Devuelve el UUID del registro extraído de la URL.
    """
    await page.wait_for_selector(
        "app-detail-registry-view dnt-button[title-text='Descargar justificante']",
        state="attached",
        timeout=timeout_ms
    )
    # Extraer UUID del registro de la URL: /es/detalle-registro/{uuid}
    url = page.url
    import re
    match = re.search(r'detalle-registro/([a-f0-9-]+)', url)
    registry_uuid = match.group(1) if match else None
    print(f"[REDSARA] Página de detalle cargada. UUID: {registry_uuid}")
    return registry_uuid


async def wait_for_download_button_ready(page: Page, timeout_ms: int = 15000) -> None:
    """
    Espera a que el botón 'Descargar justificante' esté habilitado en el host.
    Nota: el shadow button interno puede tener aria-disabled=true permanentemente;
    lo que importa es que el host tenga is-disabled="false" (que ya lo tiene).
    """
    await page.wait_for_function(
        """() => {
            const host = document.querySelector(
                'app-detail-registry-view dnt-button[title-text="Descargar justificante"]'
            )
            if (!host) return false
            // Verificar que el host no esté deshabilitado
            const isDisabled = host.getAttribute('is-disabled')
            if (isDisabled === 'true' || isDisabled === '') return false
            // Verificar que el botón esté visible
            const rect = host.getBoundingClientRect()
            return rect.width > 0 && rect.height > 0
        }""",
        timeout=timeout_ms
    )


async def download_justificante(page: Page, save_path: Path) -> Path:
    """
    Descarga el justificante de presentación y lo guarda en save_path.
    Devuelve la ruta al archivo descargado.
    
    El botón dispara una descarga via Blob URL — hay que interceptarla con expect_download().
    """
    await wait_for_download_button_ready(page)

    # Usar expect_download() ANTES del click para interceptar la descarga del Blob
    async with page.expect_download(timeout=30000) as download_info:
        # Click en el HOST del dnt-button (no en el shadow button interno)
        # El shadow button tiene aria-disabled=true pero el host funciona correctamente
        clicked = await page.evaluate(
            """() => {
                const host = document.querySelector(
                    'app-detail-registry-view dnt-button[title-text="Descargar justificante"]'
                )
                if (!host) return false
                host.click()
                return true
            }"""
        )
        if not clicked:
            raise RuntimeError("REDSARA: no se encontró el botón 'Descargar justificante'.")

    download: Download = await download_info.value

    # Guardar el archivo
    save_path.parent.mkdir(parents=True, exist_ok=True)
    await download.save_as(save_path)

    # Verificar que se guardó correctamente
    if not save_path.exists() or save_path.stat().st_size == 0:
        raise RuntimeError(f"REDSARA: el justificante descargado está vacío: {save_path}")

    print(f"[REDSARA] Justificante descargado: {save_path} ({save_path.stat().st_size} bytes)")
    return save_path


# ─── Uso ────────────────────────────────────────────────────────────────────

async def step5_download_justificante(page: Page, output_dir: Path, id_recurso: str) -> Path:
    """
    Paso final: esperar la página de detalle y descargar el justificante.
    """
    # La navegación a la página de detalle ya ocurrió tras la firma exitosa
    registry_uuid = await wait_for_detail_page(page)

    save_path = output_dir / f"justificante_{id_recurso}_{registry_uuid}.pdf"

    return await download_justificante(page, save_path)
```

---

### Por qué `expect_download()` y no un fetch directo

La descarga ocurre vía `Blob URL` creada por Angular en el navegador. Playwright intercepta esto nativamente con `expect_download()`. No se puede hacer un fetch directo a `reg-api.redsara.es` porque los endpoints requieren las cookies de sesión de Angular y tienen CORS bloqueado para orígenes externos.

### Selectores confirmados

| Elemento | Selector |
|---|---|
| Botón descarga | `app-detail-registry-view dnt-button[title-text="Descargar justificante"]` |
| Alternativo | `dnt-button[title-text="Descargar justificante"]` |
| Número de registro | El texto `REGAGE...` en el DOM |
| UUID del registro | En la URL: `/es/detalle-registro/{UUID}` |