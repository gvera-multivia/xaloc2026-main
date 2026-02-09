# Auditoría Técnica: Xaloc Automation

**Fecha:** 24 Octubre 2023
**Auditor:** Senior Full-Stack Architect
**Versión:** 1.0

Este documento detalla los hallazgos de la auditoría técnica realizada sobre el repositorio `xaloc_automation`. El objetivo es identificar deuda técnica, riesgos de seguridad y oportunidades de mejora arquitectónica, proporcionando una hoja de ruta para la refactorización conservadora.

---

## 📂 Módulo: Core (`core/`)

### 🔴 Problemas Detectados
- **[Arquitectura]**: La clase `SQLiteDatabase` en `core/sqlite_db.py` es una "God Class". Maneja conexiones, migraciones, colas de trabajo, logs de jobs, y configuración de organismos.
- **Impacto**: Dificulta el testing unitario y viola el Principio de Responsabilidad Única (SRP). Un cambio en la lógica de logs podría romper la gestión de colas.
- **[Rendimiento]**: Se crea una nueva conexión a SQLite (`sqlite3.connect`) en cada llamada a método.
- **Impacto**: Aunque SQLite es ligero, esto introduce overhead innecesario en operaciones de alta frecuencia (worker loop).
- **[Malas Prácticas]**: Uso extensivo de "Magic Strings" para estados (`'pending'`, `'processing'`, `'completed'`).

### 🛠 Solución Propuesta
- **Refactorización**:
    1.  Extraer la lógica de conexión a un `DatabaseManager` o usar un context manager que reutilice la conexión en un scope definido.
    2.  Mover las constantes de estado a un `Enum` (`TaskStatus`).
    3.  Separar repositorios: `JobRepository`, `ConfigRepository`, `QueueRepository`.

### 💻 Ejemplo de Código (Antes vs Después)

**Antes (`core/sqlite_db.py`):**
```python
def update_task_status(self, task_id: int, status: str, ...):
    conn = self.get_connection() # Nueva conexión
    # ...
    query = f"UPDATE tramite_queue SET status = ? ..." # String literal
```

**Después (Propuesto):**
```python
# core/enums.py
class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"

# core/repositories/queue_repository.py
class QueueRepository:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def update_status(self, task_id: int, status: TaskStatus, ...):
        with self.db.get_connection() as conn:
            # ...
```

---

## 📂 Módulo: Brain & Worker (`brain.py`, `worker.py`)

### 🔴 Problemas Detectados
- **[Seguridad]**: Inyección SQL potencial en `brain.py` al usar f-strings para construir queries dinámicas.
- **Impacto**: Si `config["query_organisme"]` es comprometido (Second Order SQL Injection), se podría alterar la consulta a SQL Server.
- **[Malas Prácticas]**: Duplicación de lógica de negocio (DRY). La construcción de payloads y la lógica de conexión a SQL Server se repite en `brain.py`, `worker.py` y `xaloc_task.py`.
- **[Malas Prácticas]**: URLs hardcoded (`http://www.xvia-grupoeuropa.net/...`) dispersas en múltiples archivos.

### 🛠 Solución Propuesta
- **Refactorización**:
    1.  Centralizar URLs en `core/config.py` o variables de entorno.
    2.  Usar query building seguro o validación estricta para `query_organisme`.
    3.  Crear un módulo `core/services/payload_builder.py` compartido.

### 💻 Ejemplo de Código (Antes vs Después)

**Antes (`brain.py`):**
```python
query = SQL_FETCH_RECURSOS.format(
    organisme_like_clause=organisme_like_clause, # Peligroso si no se sanea
    texp_list=texp_placeholders
)
```

**Después (Propuesto):**
```python
# Usar construcción condicional segura
clauses = []
params = []
if config["query_organisme"]:
    clauses.append("rs.Organisme LIKE ?")
    params.append(config["query_organisme"])
```

---

## 📂 Módulo: Sites (`sites/xaloc_girona/`)

### 🔴 Problemas Detectados
- **[Malas Prácticas]**: Selectores CSS/XPath y Regex hardcoded dentro de los flujos (`flows/login.py`).
- **Impacto**: Si el diseño de la web cambia, hay que buscar y reemplazar en múltiples archivos de lógica en lugar de un archivo de configuración.
- **[Robustez]**: Detección de login basada en strings parciales de URL (`if config.url_post_login in actual_url`). Esto es frágil ante redirecciones inesperadas.

### 🛠 Solución Propuesta
- **Refactorización**:
    1.  Mover *todos* los selectores a `sites/xaloc_girona/config.py` o un archivo `selectors.py`.
    2.  Usar Page Objects Pattern (o al menos un diccionario estructurado) para los selectores.

### 💻 Ejemplo de Código (Antes vs Después)

**Antes (`sites/xaloc_girona/flows/login.py`):**
```python
boton = page.get_by_role("button", name=re.compile(r"Acceptar|Aceptar", re.IGNORECASE))
```

**Después (Propuesto):**
```python
# sites/xaloc_girona/config.py
class XalocSelectors:
    COOKIE_BUTTON_REGEX = re.compile(r"Acceptar|Aceptar", re.IGNORECASE)

# flows/login.py
boton = page.get_by_role("button", name=config.selectors.COOKIE_BUTTON_REGEX)
```

---

## 📂 Seguridad General

### 🔴 Problemas Detectados
- **Hardcoded Secrets/Config**: Se detectaron emails hardcoded (`INFO@XVIA-SERVICIOSJURIDICOS.COM`) y URLs internas en el código.
- **Dependencias**: El archivo `requirements.txt` no fija versiones (e.g., `playwright`, `pandas`). Esto puede causar que builds futuros rompan si una librería introduce cambios (breaking changes).

### 🛠 Solución Propuesta
- **Acción Inmediata**:
    1.  Mover el email a `.env` (`DEFAULT_CONTACT_EMAIL`).
    2.  Generar un `requirements.lock` o fijar versiones en `requirements.txt` (e.g., `playwright==1.40.0`).

---

## 📉 Estrategia de Refactorización "Magic Strings"

El problema más recurrente es el uso de cadenas mágicas. Para solucionarlo sin romper el código ("Conservative Refactoring"), se sugiere:

1.  **Fase 1: Identificación y Centralización (No-Breaking)**
    - Crear `core/constants.py`.
    - Añadir `Enum` para estados: `TaskStatus`.
    - Añadir `Enum` para URLs base si son compartidas.

2.  **Fase 2: Reemplazo Progresivo**
    - Seleccionar un archivo (ej. `core/sqlite_db.py`).
    - Importar el `Enum`.
    - Reemplazar `'pending'` por `TaskStatus.PENDING.value`.
    - **Ejecutar Tests**.

3.  **Fase 3: Limpieza**
    - Una vez reemplazados todos los usos, eliminar las cadenas literales.

---

## 📘 Guía de Estilo Sugerida

Para mantener la calidad del código en el futuro:

1.  **Tipado Estricto**: Todo método nuevo debe tener Type Hints (`def funcion(a: int) -> str:`). Usar `mypy` en el CI.
2.  **No Magic Strings**:
    - Selectores -> `config.py` o `selectors.py`.
    - Estados/Tipos -> `Enums`.
    - Mensajes de Error -> Constantes o ficheros de traducción.
3.  **Logging Estructurado**: Usar siempre `logger.info(..., extra={"task_id": ...})` para facilitar la trazabilidad en herramientas de monitoreo.
4.  **Tests**: Cada fix de bug debe venir acompañado de un test que reproduzca el fallo (Regression Testing).

---

## 📚 Referencias

- **SOLID Principles**: Específicamente SRP (Single Responsibility Principle) para `SQLiteDatabase`.
- **OWASP Top 10**: Prevención de Inyección SQL y manejo seguro de configuraciones.
- **The Twelve-Factor App**: Configuración separada del código (Variables de entorno).
