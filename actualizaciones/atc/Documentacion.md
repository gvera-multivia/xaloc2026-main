# ATC — Certificat de Deute Tributari (Agència Tributària de Catalunya)

## URL objetivo

```
https://atc.gencat.cat/es/gestions/certificats/certificats-tributaris/
```

## Arquitectura de ficheros

```
actualizaciones/atc/
├── config.py          → AtcConfig (dataclass)
├── data_models.py     → AtcTarget (dataclass)
├── controller.py      → AtcController + get_controller()
├── automation.py      → AtcAutomation (orquestador async)
└── flows/
    ├── login.py       → run_login        — navegación inicial + cookies
    ├── formulario.py  → run_formulario   — apertura del tramit
    ├── documentos.py  → run_documentos   — selección de tipo de certificat
    └── confirmacion.py→ run_confirmacion — descarga del PDF + extracción de texto
```

## Config (`config.py`)

| Campo | Valor |
|---|---|
| `site_id` | `atc` |
| `url_base` / `url_certificats` | Landing de certificats tributaris de Gencat |
| `dir_logs` | `actualizaciones/atc/` |
| `start_cta_selector` | `a:has-text('Inicia el tramit'), a:has-text('Iniciar tramite'), a:has-text('Tramitar')` |
| `default_timeout` | 30 000 ms |
| `navigation_timeout` | 60 000 ms |
| Browser | Chrome (forzado vía `navegador.canal = "chrome"`) |

## Data model (`data_models.py`)

`AtcTarget`

| Campo | Tipo | Descripción |
|---|---|---|
| `idRecurso` | `int \| None` | ID interno del recurso |
| `expediente` | `str` | Número de expediente |
| `archivos_adjuntos` | `list[Path]` | Ficheros a adjuntar |
| `payload` | `dict[str, Any]` | Datos del trámite + resultados acumulados |
| `headless` | `bool` | Modo sin cabecera (default: `True`) |

## Flujo completo (`automation.py`)

`AtcAutomation.ejecutar_flujo_completo()` ejecuta los pasos en orden:

```
run_login → run_formulario → run_documentos → run_confirmacion
```

Al terminar (con éxito o error) hace screenshot completo en:
```
<dir_screenshots>/atc_standalone.png
```
Y pausa esperando Enter en consola antes de cerrar el navegador.

---

## Flows en detalle

### 1. `login.py` — `run_login`

1. Configura timeouts desde config.
2. Navega a `url_base` (`wait_until="domcontentloaded"`).
3. Espera `networkidle`.
4. Intenta aceptar el banner de cookies buscando el botón con regex:
   `Acéptalas todas | Aceptar todas | Accepta-les totes` (timeout 5 s; si no aparece, continúa).

### 2. `formulario.py` — `run_formulario`

1. Espera `domcontentloaded`.
2. Busca el enlace "Inicia el tràmit / Iniciar tramit" (`role=link`).
3. Hace click esperando un popup (timeout 8 s):
   - Si se abre popup, trabaja en esa nueva pestaña.
   - Si no hay popup, sigue en la misma pestaña.
4. Espera `domcontentloaded` + `networkidle` en la página activa y la devuelve.

### 3. `documentos.py` — `run_documentos`

1. Pulsa el botón de certificado digital (`[data-testid='certificate-btn']`).
2. Selecciona el tipo de certificat `GEN02` en el desplegable `#MainContent_CertificatDeuteControl_dpdTipusCertificat`.
3. Pulsa el botón "Comprova / Comprobar".
4. Espera `networkidle`.

### 4. `confirmacion.py` — `run_confirmacion`

1. Espera `domcontentloaded`.
2. Busca el botón "Visualitza document / Visualizar documento".
3. Descarga el PDF al pulsar el botón.
4. Guarda el fichero en `actualizaciones/atc/downloads/<suggested_filename>`.
5. Escribe la ruta en `datos.payload["atc_download_pdf_path"]`.
6. **Extracción de texto (pdfplumber, opcional):**
   - Si `pdfplumber` está instalado, extrae el texto de cada página.
   - Guarda `<filename>.txt` con el texto completo.
   - Guarda `<filename>.json` con metadatos: `pdf_path`, `txt_path`, `pages`, `chars`.
   - Añade al payload: `atc_pdf_text_path`, `atc_pdf_meta_path`, `atc_pdf_text_preview` (primeros 500 chars).
   - Si pdfplumber no está o falla, registra warning y continúa.

---

## Outputs generados

| Fichero | Descripción |
|---|---|
| `downloads/<filename>.PDF` | Certificat de deute tributari descargado |
| `downloads/<filename>.txt` | Texto extraído del PDF (si pdfplumber disponible) |
| `downloads/<filename>.json` | Metadatos del PDF (rutas, páginas, chars) |
| `<dir_screenshots>/atc_standalone.png` | Screenshot final de la ejecución |
| `atc.log` | Log completo de la ejecución |

## Payload resultante (claves añadidas)

| Clave | Descripción |
|---|---|
| `atc_download_pdf_path` | Ruta local del PDF del certificat |
| `atc_pdf_text_path` | Ruta del `.txt` con el texto extraído |
| `atc_pdf_meta_path` | Ruta del `.json` con metadatos |
| `atc_pdf_text_preview` | Primeros 500 caracteres del texto extraído |

## Estado actual

- Flujo completo implementado: login → apertura tramit → selección certificat GEN02 → descarga PDF.
- Autenticación mediante certificado digital del navegador.
- Extracción de texto del PDF via `pdfplumber` funcional (ver `downloads/` para ejemplo real).
- Aceptación de cookies multi-idioma (ca/es) en el login.

## Pendiente / A ajustar

- Verificar que el selector `#MainContent_CertificatDeuteControl_dpdTipusCertificat` y el tipo `GEN02` son correctos con inspección del portal.
- Definir pasos de identificación/firma si el camino de trámite lo requiere.
- Ajustar `SQL_BY_NUMCLIENT` y `build_payload_from_row()` en el script de entrada según la fuente de datos final.
