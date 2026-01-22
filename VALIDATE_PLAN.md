# 📋 VALIDATE_PLAN.md
## Módulo de Validación y Control de Errores (Playwright Edition)

> **Versión:** 1.0  
> **Fecha:** 2026-01-22  
> **Estado:** Pendiente de implementación

---

## 🎯 Objetivo

Implementar un sistema de validación exhaustiva que:
1. Valide campos **antes** de interactuar con el navegador
2. Detenga la ejecución ante errores críticos (pausa humana)
3. Genere reportes visuales de discrepancia
4. Descargue documentos dinámicamente desde URL construida

---

## 📁 Estructura de Directorios

```
core/
└── validation/
    ├── __init__.py               # Exports del módulo
    ├── validation_engine.py      # Motor principal de validación
    ├── validators.py             # Funciones de validación atómicas
    ├── geo_data.py               # Listas de provincias/ciudades válidas
    ├── discrepancy_reporter.py   # Generador de reportes HTML
    └── document_downloader.py    # Descargador de documentos por URL

tmp/
└── downloads/                    # Documentos descargados temporalmente

templates/
└── discrepancy_report.html       # Template HTML para reportes
```

---

## 🔄 Flujo de Ejecución

```
┌─────────────────────────────────────────────────────────────────┐
│                    ENTRADA: Filtros SQL Server                  │
│         (FaseProcedimiento, Organisme, fechas, etc.)            │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CONSULTA A BASE DE DATOS                   │
│   → Obtiene: idRecurso, Expedient, datos cliente, etc.          │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      VALIDATION ENGINE                          │
│   → Valida campos obligatorios, formatos, direcciones           │
│   → Si ERROR → DiscrepancyReporter → PAUSA HUMANA               │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DOCUMENT DOWNLOADER                          │
│   → Construye URL: {base_url}/{idRecurso}/{expediente}.pdf      │
│   → Descarga a tmp/downloads/                                   │
│   → Valida PDF (no corrupto, tamaño OK)                         │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PLAYWRIGHT EXECUTOR                          │
│   → Rellena formulario web                                      │
│   → Sube documento descargado                                   │
│   → Si ÉXITO → Marca Estado 2 (Hecho)                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## ✅ Validaciones a Implementar

### 1. Campos Obligatorios

| Campo | Regla | Severidad |
|-------|-------|-----------|
| `nif` | No nulo, no solo espacios | ERROR |
| `name` | No nulo, no solo espacios | ERROR |
| `notif_name` | No nulo (Madrid) | ERROR |
| `notif_surname1` | No nulo (Madrid) | ERROR |

### 2. Direcciones

| Validación | Descripción | Severidad |
|------------|-------------|-----------|
| **Dirección Sucia** | Si `address_street` contiene números Y `address_number` vacío | ERROR |
| **Atomización** | Calle, número, piso, puerta separados correctamente | ERROR |

### 3. Formatos

| Campo | Regla | Severidad |
|-------|-------|-----------|
| `address_zip` | 5 dígitos numéricos | ERROR |
| `nif` | Letra de control válida (NIF/NIE) | ERROR |
| `user_phone` | 9 dígitos, formato español | WARNING |
| `user_email` | Formato RFC 5322 | ERROR |
| `plate_number` | Formato español (NNNNLLL) | WARNING |

### 4. Geo-validación

| Campo | Regla | Severidad |
|-------|-------|-----------|
| `address_province` | Coincidir con lista válida | WARNING |
| `address_city` | Coincidir según provincia | WARNING |

### 5. Documentos Descargados

| Validación | Descripción | Severidad |
|------------|-------------|-----------|
| URL Construida | idRecurso + expediente correctos | ERROR |
| Descarga Exitosa | HTTP 200, archivo completo | ERROR |
| PDF Válido | Headers PDF correctos | ERROR |
| Tamaño | < límite formulario (10MB) | ERROR |

---

## 📄 Componentes Principales

### 1. `validation_engine.py`

```python
from dataclasses import dataclass

@dataclass
class ValidationError:
    field: str
    message: str
    severity: str  # "ERROR" | "WARNING"

@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[ValidationError]
    warnings: list[ValidationError]
    sanitized_payload: dict | None

class ValidationEngine:
    def __init__(self, site_id: str):
        self.site_id = site_id
    
    def validate(self, payload: dict) -> ValidationResult:
        """Ejecuta todas las validaciones y retorna resultado."""
```

### 2. `validators.py`

```python
def validate_nif(nif: str) -> tuple[bool, str | None]:
    """Valida NIF/NIE español con letra de control."""

def validate_dirty_address(street: str, number: str) -> tuple[bool, str | None]:
    """Detecta números en calle con campo número vacío."""

def validate_postal_code(cp: str) -> tuple[bool, str | None]:
    """Valida CP español de 5 dígitos."""

def validate_phone_es(phone: str) -> tuple[bool, str | None]:
    """Valida teléfono español (móvil o fijo)."""

def validate_email(email: str) -> tuple[bool, str | None]:
    """Valida formato email."""

def validate_plate_spain(plate: str) -> tuple[bool, str | None]:
    """Valida matrícula española."""
```

### 3. `document_downloader.py`

```python
@dataclass
class DownloadResult:
    success: bool
    local_path: Path | None
    error: str | None

class DocumentDownloader:
    def __init__(self, url_template: str):
        """
        url_template: 'http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/{idRecurso}'
        """
    
    def build_url(self, id_recurso: str, expediente: str) -> str:
        """Construye URL sustituyendo placeholders."""
    
    async def download(self, id_recurso: str, expediente: str) -> DownloadResult:
        """Descarga documento y retorna ruta local."""
```

### 4. `discrepancy_reporter.py`

```python
class DiscrepancyReporter:
    def generate_html(
        self, 
        payload: dict, 
        errors: list[ValidationError],
        id_exp: str
    ) -> Path:
        """Genera HTML con campos erróneos en rojo."""
    
    def open_in_browser(self, html_path: Path) -> None:
        """Abre reporte en navegador predeterminado."""
```

---

## 🔧 Integración con Worker

### Modificación en `worker.py`

```python
from core.validation import ValidationEngine, DiscrepancyReporter, DocumentDownloader

async def process_task(db, task_id, site_id, protocol, payload):
    # 1. VALIDAR PAYLOAD
    validator = ValidationEngine(site_id=site_id)
    result = validator.validate(payload)
    
    if not result.is_valid:
        reporter = DiscrepancyReporter()
        html_path = reporter.generate_html(
            payload, 
            result.errors, 
            payload.get("idRecurso", "N/A")
        )
        reporter.open_in_browser(html_path)
        
        logger.warning(f"Validación fallida para ID: {payload.get('idRecurso')}")
        logger.warning("Corrija los datos y reinicie el worker.")
        
        db.update_task_status(task_id, "validation_failed")
        return
    
    # 2. DESCARGAR DOCUMENTO
    downloader = DocumentDownloader(url_template=URL_TEMPLATE)
    download_result = await downloader.download(
        payload["idRecurso"], 
        payload["expediente"]
    )
    
    if not download_result.success:
        logger.error(f"Error descargando documento: {download_result.error}")
        db.update_task_status(task_id, "download_failed")
        return
    
    # 3. EJECUTAR AUTOMATIZACIÓN CON DOCUMENTO DESCARGADO
    payload["archivo_local"] = str(download_result.local_path)
    # ... continuar con Playwright
```

---

## 📝 Checklist de Implementación

- [ ] Crear directorio `core/validation/`
- [ ] Implementar `validators.py` (funciones atómicas)
- [ ] Implementar `geo_data.py` (provincias/ciudades)
- [ ] Implementar `validation_engine.py`
- [ ] Implementar `document_downloader.py`
- [ ] Implementar `discrepancy_reporter.py`
- [ ] Crear template `templates/discrepancy_report.html`
- [ ] Integrar validación en `worker.py`
- [ ] Escribir tests unitarios
- [ ] Probar flujo completo end-to-end

---

## ⚙️ Configuración Requerida

# En config.py o .env
DOCUMENT_URL_TEMPLATE = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/{idRecurso}"
DOWNLOAD_DIR = "tmp/downloads"
MAX_DOWNLOAD_SIZE_MB = 10
DOWNLOAD_TIMEOUT_SECONDS = 30

---

## 📊 Cronograma Estimado

| Fase | Tarea | Duración |
|------|-------|----------|
| 1 | Crear módulo `core/validation` | 2-3h |
| 2 | Implementar `ValidationEngine` | 1-2h |
| 3 | Crear `DiscrepancyReporter` + HTML | 1-2h |
| 4 | Implementar `DocumentDownloader` | 1h |
| 5 | Integrar en `worker.py` | 1h |
| 6 | Tests unitarios | 2h |
| 7 | Pruebas end-to-end | 1h |

**Total estimado: 9-12 horas**
