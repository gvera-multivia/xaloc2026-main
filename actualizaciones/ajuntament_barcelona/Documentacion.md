# Ajuntament Barcelona — Certificat Negatiu de Deute (T19b)

## URL objetivo

```
https://seuelectronica.ajuntament.barcelona.cat/oficinavirtual/ca/tramit/20200001444
```

## Arquitectura de ficheros

```
actualizaciones/ajuntament_barcelona/
├── config.py          → AjuntamentBarcelonaConfig (dataclass)
├── data_models.py     → AjuntamentBarcelonaTarget (dataclass)
├── controller.py      → AjuntamentBarcelonaController + get_controller()
├── automation.py      → AjuntamentBarcelonaAutomation (orquestador async)
└── flows/
    ├── login.py       → run_login        — navegación inicial
    ├── formulario.py  → run_formulario   — inicio de trámite
    ├── documentos.py  → run_documentos   — relleno del formulario T19b
    ├── confirmacion.py→ run_confirmacion — descarga del certificado PDF
    └── multes.py      → run_multes       — consulta y descarga de multes
```

## Config (`config.py`)

| Campo | Valor |
|---|---|
| `site_id` | `ajuntament_barcelona` |
| `url_base` | sede electrónica del trámite 20200001444 |
| `url_confirm_ca` | URL directa a pantalla de confirmación (catalán) |
| `url_confirm_es` | URL directa a pantalla de confirmación (castellano) |
| `dir_logs` | `actualizaciones/ajuntament_barcelona/` |
| `telefono_principal` | `722761154` |
| `default_timeout` | 30 000 ms |
| `navigation_timeout` | 60 000 ms |
| Browser | Chrome (forzado vía `navegador.canal = "chrome"`) |

## Data model (`data_models.py`)

`AjuntamentBarcelonaTarget`

| Campo | Tipo | Descripción |
|---|---|---|
| `idRecurso` | `int \| None` | ID interno del recurso |
| `expediente` | `str` | Número de expediente |
| `archivos_adjuntos` | `list[Path]` | Ficheros a adjuntar |
| `payload` | `dict[str, Any]` | Datos del trámite + resultados acumulados |
| `headless` | `bool` | Modo sin cabecera (default: `True`) |

## Flujo completo (`automation.py`)

`AjuntamentBarcelonaAutomation.ejecutar_flujo_completo()` ejecuta los pasos en orden:

```
run_login → run_formulario → run_documentos → run_confirmacion → run_multes
```

Al terminar (con éxito o error) hace screenshot completo en:
```
<dir_screenshots>/ajuntament_barcelona_standalone.png
```
Y pausa esperando Enter en consola antes de cerrar el navegador.

---

## Flows en detalle

### 1. `login.py` — `run_login`

1. Configura timeouts desde config.
2. Navega a `url_base` (`wait_until="domcontentloaded"`).
3. Espera `networkidle`; si falla, cae a `domcontentloaded`.
4. Devuelve la página activa (maneja páginas cerradas con `_get_alive_page`).

### 2. `formulario.py` — `run_formulario`

1. Si ya está en `/formulari/.../init/`, retorna inmediatamente (trámite ya iniciado).
2. Busca el botón "Inicia el tràmit" (primero en `#starter-buttons`, luego global); 3 reintentos con 800 ms de espera entre intentos.
3. Tras el click, detecta pantalla intermedia de selección de certificado (`#btnContinuaCert` / `[data-testid='certificate-btn']`): hasta 8 sondeos cada 700 ms.
4. Si el botón de certificado aparece, lo pulsa y espera `networkidle`.

### 3. `documentos.py` — `run_documentos`

Rellena el formulario real del trámite T19b:

| Campo | Acción |
|---|---|
| Botón certificado | Click si está presente (`[data-testid='certificate-btn']`) |
| `#T19b_REP_docTipus` | Selecciona `PR.R.DNI` |
| Teléfono principal | Rellena con `config.telefono_principal` (label o selector por ID/name) |
| Tipo de certificat | Marca radio "Certificat negatiu de deute" (`#T19b_tipcert__XX.K.NEGDEUDA`) |
| Idioma | Marca radio Català (`#T19b_idioma__DV.R.ID_CA`) |
| Botón "Continuar" | Click en `#continuar` |
| Botón "Enviar" | Click (timeout 90 s) + espera `networkidle` |

### 4. `confirmacion.py` — `run_confirmacion`

1. Busca el enlace "Certificat negatiu de deute / Certificado negativo de deuda".
2. Si no aparece (timeout 5 s), navega directamente a `url_confirm_ca` o `url_confirm_es` según el idioma de la URL actual.
3. Descarga el PDF al hacer click en el enlace.
4. Guarda el fichero en `actualizaciones/ajuntament_barcelona/downloads/<suggested_filename>`.
5. Escribe la ruta en `datos.payload["ajuntament_barcelona_download_pdf_path"]`.

### 5. `multes.py` — `run_multes`

Flujo de consulta de multes de trànsit de Barcelona Hisenda:

1. Navega a `https://ajuntament.barcelona.cat/hisenda/ca/tramits-gestions/multes-de-transit?profile=1#procedures`.
2. Intenta expandir el acordeón (`.field > div:nth-child(5)`).
3. Busca el enlace "Consulta multes pagades i/o pendents" (`a[href*='ptbportal/login.do'][target='_blank']`); lo abre en popup.
4. En el popup, pulsa el botón de certificado si existe; luego "Accedir a la meva carpeta" (fallback: "Accedir").
5. Hace click en la pestaña "Multes" (`a#contact-tab`; fallback: `role=tab`).
6. Abre popup "Multes pendents" (fallback: "eMultes").
7. Selecciona año `TOTS` en `select[name='anySeleccio']`.
8. **Si hay multes**: extrae los datos de cada formulario `form[id^='form']` a un DataFrame de pandas con columnas: `Identif`, `Fet denunciat`, `Adreça`, `Data`, `Situació`, `Expedient`, `Import`.
9. Llama a `descargar_documentos()` para cada multa:
   - Navega al detalle vía `document.getElementById('form{i}').submit()`.
   - Descarga todos los formularios `form[action*='getDocument']`.
   - Guarda los ficheros en `downloads/documentos_multas/<ident>_<j>_<filename>`.
   - Vuelve al listado con `go_back`.
10. Escribe `datos.payload["ajuntament_barcelona_multes_no_trobat_remeses_exists"]` (`True` si no hay multes).

---

## Outputs generados

| Fichero | Descripción |
|---|---|
| `downloads/<filename>.pdf` | Certificat Negatiu de Deute descargado |
| `downloads/documentos_multas/<ident>_<j>_<filename>` | Documentos asociados a cada multa |
| `<dir_screenshots>/ajuntament_barcelona_standalone.png` | Screenshot final de la ejecución |
| `ajuntament_barcelona.log` | Log completo de la ejecución |

## Payload resultante (claves añadidas)

| Clave | Descripción |
|---|---|
| `ajuntament_barcelona_download_pdf_path` | Ruta local del PDF del certificat |
| `ajuntament_barcelona_multes_no_trobat_remeses_exists` | `True` si no se encontraron multes |

## Estado actual

- Flujo completo funcional: login → formulario T19b → descarga certificat → consulta multes.
- Autenticación mediante certificado digital del navegador (sin usuario/contraseña explícitos).
- Descarga de documentos asociados a multes implementada y probada (ver `downloads/documentos_multas/`).
