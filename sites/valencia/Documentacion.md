# Valencia — Sede Electrónica del Ayuntamiento de Valencia

## URLs objetivo

| Código | URL |
|---|---|
| `MU.DE.30` | `https://sede.valencia.es/sede/registro/procedimiento/MU.DE.30` |
| `MU.DE.50` | `https://sede.valencia.es/sede/registro/procedimiento/MU.DE.50` |
| `MU.SA.40` | `https://sede.valencia.es/sede/registro/procedimiento/MU.SA.40` |

## Arquitectura de ficheros

```
sites/valencia/
├── config.py          → ValenciaConfig (dataclass)
├── data_models.py     → ValenciaTarget (dataclass)
├── controller.py      → ValenciaController + get_controller()
├── automation.py      → ValenciaAutomation (orquestador async)
└── flows/
    ├── common.py      → helpers de relleno, utilidades de documento, upload
    ├── login.py       → run_login       — selección de procedimiento + autenticación
    ├── formulario.py  → run_formulario  — relleno del formulario de instancia
    ├── documentos.py  → run_documentos  — subida de ficheros adjuntos
    └── confirmacion.py→ run_confirmacion — firma y presentación
```

---

## Config (`config.py`)

| Campo | Valor |
|---|---|
| `site_id` | `valencia` |
| `url_base` | `https://sede.valencia.es` |
| `url_mu_de_30` | Procedimiento alegaciones denuncia tránsito |
| `url_mu_de_50` | Procedimiento identificación conductor |
| `url_mu_sa_40` | Procedimiento recurso reposición (sanción/embargo) |
| `iniciar_tramite_selector` | `[id="formIniciarTramite:iniciarTramite"]` |
| `save_form_selector` | `[id="formularioInstancia:saveForm"]` |

---

## Data model (`data_models.py`)

`ValenciaTarget`

### Identificación

| Campo | Tipo | Descripción |
|---|---|---|
| `idRecurso` | `int \| None` | ID interno del recurso |
| `idExp` | `int \| None` | ID de expediente interno |
| `expediente` | `str` | Número de expediente MU (ej: `MU DE 30 2024 123456`) |
| `fase_procedimiento` | `str` | Fase de la denuncia (determina el tipo de trámite) |
| `tramite_tipo` | `str` | Tipo lógico inferido (ver tabla de tipos) |
| `tramite_code` | `str` | Código de procedimiento (`MU.DE.30`, `MU.DE.50`, `MU.SA.40`) |

### Datos del solicitante

| Campo | Tipo | Descripción |
|---|---|---|
| `tipodecliente` | `str` | `"1"` = persona física, `"2"` = empresa |
| `nif` | `str` | NIF/NIE del solicitante |
| `nifempresa` | `str` | CIF de la empresa (si `tipodecliente == "2"`) |
| `nombre` | `str` | Nombre de pila |
| `apellido1` | `str` | Primer apellido |
| `apellido2` | `str` | Segundo apellido |
| `nombrefiscal` | `str` | Razón social (empresas) |

### Datos del conductor (solo `MU.DE.50`)

| Campo | Tipo | Descripción |
|---|---|---|
| `conduc_nom` | `str` | Nombre completo del conductor |
| `conduc_dni` | `str` | DNI/NIE del conductor |
| `conduc_codpost` | `str` | Código postal del conductor |
| `conduc_adr` | `str` | Dirección del conductor |
| `texp` | `int` | Tipo de expediente (3/4 → priorizar datos secundarios `*2`) |

### Matrícula y textos

| Campo | Tipo | Descripción |
|---|---|---|
| `matricula` | `str` | Matrícula principal |
| `matricula2` | `str` | Matrícula alternativa 1 |
| `matricula3` | `str` | Matrícula alternativa 2 |
| `expone` | `str` | Texto del bloque "Expone/Hechos" |
| `solicita` | `str` | Texto del bloque "Solicita" |
| `archivos_para_subir` | `list[Path]` | Ficheros a adjuntar |
| `payload` | `dict` | Datos originales completos |
| `headless` | `bool` | Modo sin cabecera (default: `True`) |

---

## Tipos de trámite

El `ValenciaController` infiere el tipo de trámite a partir de `fase_procedimiento` (normalizado sin tildes, en minúsculas):

| Palabra clave en `fase_procedimiento` | `tramite_tipo` | `tramite_code` |
|---|---|---|
| `identific` | `identificacion_conductor` | `MU.DE.50` |
| `denuncia` o `propuesta` | `alegaciones_denuncia_transito` | `MU.DE.30` |
| `sancion`, `embargo` o `apremio` | `recurso_reposicion` | `MU.SA.40` |
| (resto / no reconocido) | `alegaciones_denuncia_transito` | `MU.DE.30` |

---

## Controller (`controller.py`)

### `map_data(data)`
Normaliza un dict crudo (de BD o JSON) al formato que espera `ValenciaTarget`:
- Aliases de campos: `Expedient` → `expediente`, `FaseProcedimiento` → `fase_procedimiento`, `Apellido1` → `apellido1`, `ConducNom` → `conduc_nom`, etc.
- Infiere `tramite_tipo` y `tramite_code` si no vienen explícitos.
- Llama a `_resolve_expone_solicita` para generar los textos si faltan.

### `_resolve_expone_solicita`
1. Si el payload ya trae `expone` y `solicita`, los usa directamente.
2. Si no, busca la `fase_procedimiento` (normalizada) en `config_motivos.json` (raíz del proyecto).
3. Aplica el template de la entrada encontrada con `{expediente}` y `{sujeto_recurso}` como variables.
4. `sujeto_recurso` = campo explícito del payload > `nombrefiscal` > nombre completo.

### `config_motivos.json`
Fichero externo en la raíz del proyecto con plantillas de texto indexadas por `fase_procedimiento` normalizada. Estructura de cada entrada:
```json
{
  "fase normalizada": {
    "expone": "Texto con {expediente} y {sujeto_recurso}",
    "solicita": "Texto con {expediente} y {sujeto_recurso}"
  }
}
```

---

## Flujo completo (`automation.py`)

`ValenciaAutomation.ejecutar_flujo_completo()` ejecuta en orden:

```
run_login → run_formulario → run_documentos → run_confirmacion
```

Al terminar con éxito hace screenshot en `<dir_screenshots>/valencia_standalone.png` y espera 200 s antes de cerrar el navegador (para revisión manual).
En caso de error, guarda `valencia_error.png` y relanza la excepción con el snapshot del `ValenciaTarget`.

---

## Flows en detalle

### 1. `login.py` — `run_login`

1. Navega a la URL del procedimiento según `tramite_code`.
2. Click en `[id="formIniciarTramite:iniciarTramite"]` + espera `networkidle`.
3. **Solo para `MU.DE.30` y `MU.DE.50`:** click en botón "Següent / Siguiente".
4. Click en "Accedir amb certificat / Acceder con certificado".
5. Click en "Entitat / Entidad".
6. Intenta click en "Nou tràmit / Nuevo trámite" — opcional, continúa si no aparece.
7. **Solo `MU.DE.50`:** selecciona radio `MU.DE.50_002` + click "Siguiente".
8. Selecciona representación entidad: radio `[id="formRepresentacion:radioButtonRepresentacionEntidad:1"]`.
9. Click "Siguiente".
10. Click en botón "Iniciar" + espera `networkidle`.

### 2. `formulario.py` — `run_formulario`

Llama a helpers de `common.py` en este orden:

| Paso | Helper | Descripción |
|---|---|---|
| 1 | `fill_client_identification` | Tipo de ID, número de documento, nombre/apellidos o CIF+razón social |
| 2 | `fill_default_address` | Datos de contacto fijos (idioma, móvil, email, dirección) |
| 3 | `fill_identificacion_conductor` | Solo para `identificacion_conductor` — datos del conductor |
| 4 | `fill_mu_numbers` | Tokens del expediente MU + boletín + matrícula |
| 5 | `fill_text_if_present` | "Expone" y "Solicita" — obligatorio en `alegaciones_denuncia_transito` y `recurso_reposicion` |
| 6 | Guardar | Click en `[id="formularioInstancia:saveForm"]` + espera `networkidle` |

**`fill_client_identification`**
- Empresa (`tipodecliente == "2"`): tipo `"2"`, CIF + razón social.
- Persona física: detecta tipo de documento (NIF / NIE / CIF / PASAPORTE) por regex; selecciona opción `"1"`, `"3"` o `"4"`; rellena documento + nombre + ap1 + ap2.

**`fill_mu_numbers`**
- Divide `expediente` por espacios — requiere ≥ 5 tokens.
- `ref_mu1..4` = tokens[1..4].
- `numero_boletin` = expediente completo.
- `matricula_vehiculo` = primera matrícula válida de `matricula / matricula2 / matricula3`.

**`fill_identificacion_conductor`** (solo `MU.DE.50`)
- `texp` 3/4: prioriza campos secundarios (`Conducdni2`, `ConducNom2`, `ConducCodpost2`, `ConducAdr2`); fallback a los primarios.
- Demás `texp`: prioriza campos primarios.
- Rellena `cif_licencia` con el documento.
- NIF/NIE/PASAPORTE: radio "persona física", nombre + ap1 + ap2, permiso; opcionalmente dirección (provincia inferida por CP, calle, número).
- CIF: radio "persona jurídica", permiso, razón social, CIF.

### 3. `documentos.py` — `run_documentos`

1. Filtra `archivos_para_subir` a los que existen en disco.
2. Ordena con `order_documents_for_upload`:
   - **`identificacion_conductor`**: autorización (`AUTORIZ`/`AUTORITZ`) → recurso/justificante (`RECURSO`/`RECURS`/`JUSTIFICAT`/`JUSTIFICANTE`) → resto.
   - **Otros trámites**: recurso/justificante → autorización → resto.
3. Sube los documentos con `upload_documents`:
   - **Batch 1 y 2 (tipo1):** click en enlace "Seleccionar" (`.nth(0)`) → `input[id="uploadForm:upload"]` → "Acceptar".
   - **Batch 3+ (tipo2):** click en `input[type="submit"][value="Seleccionar"]` → rellena descripción con `stem` del fichero → input file → "Acceptar".

### 4. `confirmacion.py` — `run_confirmacion`

Secuencia de 6 pasos de firma y presentación:

| Paso | Acción | Selector principal |
|---|---|---|
| 1 | **Presentar** | `input[type="submit"][value="Presentar"]` |
| 2 | **Checkbox privacidad** | `[id="checkBoxPrivacidad"]` — marca si no está marcado |
| 3 | **Firmar i presentar** | `input[type="submit"][value*="Firmar"]` / `value*="Signar"` |
| 4 | **Acceptar modal** | `button:has-text("Acceptar")` en `div.ui-dialog-buttonset` |
| 5 | **Acceder con AutoFirma** | `a[title*="Firma con certificado local"]` — usa el 2.º si hay ≥2, si no el 1.º |
| 6 | **Firmar** (AutoFirma) | `[id="buttonSign"]` / `input.button_firmar` — busca también en frames |

Todos los pasos usan `_click_first_available` con fallback a `click(force=True)`.
El paso 6 es `required=False`: si el botón de AutoFirma no aparece, continúa con warning.

---

## Helpers de `common.py`

| Función | Descripción |
|---|---|
| `tipo_identificacion(doc)` | Detecta NIF / NIE / CIF / PASAPORTE por regex |
| `normalize_document(doc)` | Elimina puntos, guiones y espacios; convierte a mayúsculas |
| `split_full_name(full_name)` | Divide nombre completo en `(nombre, ap1, ap2)` |
| `get_matricula(*candidates)` | Devuelve la primera matrícula válida (`[A-Z0-9]{1,15}`) |
| `extraer_numero_direccion(dir)` | Extrae el primer número de una cadena de dirección |
| `provincia_por_cp(cp)` | `"VALENCIA"` / `"BARCELONA"` / `"MADRID"` / `"NO CONSTA"` por prefijo CP |
| `click_and_wait(page, locator)` | Click por selector + espera `networkidle` |
| `click_role_and_wait(page, role, name_pattern)` | Click por rol con regex + espera `networkidle` |

---

## Dirección de contacto fija

Todos los expedientes usan la misma dirección hardcoded en `fill_default_address`:

```
Idioma:    Valenciano (opción "1")
Móvil:     722761154
Email:     INFO@XVIA-SERVICIOSJURIDICOS.COM
Provincia: Valencia (opción "9")
Municipio: Valencia (opción "21")
Dirección: Carrer General Mitre, 169
CP:        08022
```

---

## Estado actual

- Flujo completo funcional para los tres procedimientos (`MU.DE.30`, `MU.DE.50`, `MU.SA.40`).
- Autenticación con certificado digital de entidad (sin usuario/contraseña explícitos).
- Subida de documentos con ordenación automática según tipo de trámite.
- Firma con AutoFirma mediante la secuencia: Presentar → checkbox → Firmar i presentar → Acceptar modal → Acceder → Firmar.
- Textos de `expone`/`solicita` generados desde `config_motivos.json` si no vienen en el payload.
- Pausa de 200 s tras finalizar para revisión visual antes de cerrar el navegador.
