# Documentación de Arquitectura Brain 2.0

Este documento define la nueva arquitectura del sistema Brain para resolver problemas de eficiencia, rate limits y deuda técnica.

---

## 1. Análisis del Problema de Rate Limit (Groq)

**Diagnóstico:**
El sistema consumió 925 tokens (de un límite diario bajo) en un periodo corto, dejando solo 35 tokens disponibles. Esto se debe a que la función `classify_address_with_ai` en `core/address_classifier.py` se invoca indiscriminadamente para *cualquier* dirección que necesite normalización, sin filtrar por prioridad o necesidad real de IA.

**Causa Raíz:**
1.  **Falta de "Guardián":** No existe una lógica condicional que impida llamar a la API para casos triviales o de baja prioridad.
2.  **Polling Ineficiente:** El sistema actual consulta la web primero, obtiene listas largas de recursos (muchos irrelevantes o sucios) e intenta procesarlos todos, disparando llamadas a la IA para direcciones que quizás ni siquiera se pueden reclamar.

**Solución Inmediata:**
Implementar un "Token Guardian" que bloquee llamadas a menos que se cumplan criterios estrictos de negocio (Madrid + Reclamado o Prioridad P1).

---

## 2. Rediseño del Flujo de Polling (DB First)

El nuevo flujo invierte la responsabilidad. En lugar de "preguntar a la web qué hay", el sistema "pregunta a la base de datos qué necesita".

### Diagrama de Flujo (Ciclo de 60s)

```mermaid
graph TD
    A[Inicio Ciclo (60s)] --> B{Consulta DB Local}
    B -- Sin tareas pendientes --> C[Dormir]
    B -- Tareas pendientes encontradas --> D[Iterar Recursos]
    D --> E{¿Es Procesable?}
    E -- NO (Datos faltantes, bloqueado) --> F[Registrar Incidencia]
    F --> D
    E -- SÍ (Datos completos) --> G[Agrupar en Batch]
    G --> H[Ejecutar Navegación Web]
    H --> I{Resultado Web}
    I -- Éxito --> J[Marcar Completado en DB]
    I -- Fallo Web --> K[Registrar Incidencia Técnica]
```

### Lógica de Decisión (Paso E)
Antes de iniciar cualquier navegador o llamada HTTP externa:
1.  **Validación de Datos:** ¿Tenemos DNI, Referencia y Dirección?
2.  **Validación de Estado:** ¿El recurso ya fue reclamado por otro usuario (bloqueo Redis)?
3.  **Validación de Negocio:** ¿La fecha límite ha pasado?

Si alguna validación falla, se genera una **Incidencia** inmediatamente sin tocar la red.

---

## 3. Optimización Estricta de Groq (Protocolo de Seguridad)

Se implementará una clase `GroqTokenGuardian` que envolverá todas las llamadas a la API.

**Reglas de Disparo (AND lógico):**
Solo se permite la llamada a `client.chat.completions.create` si:

1.  **Criterio Geográfico/Estado:** El recurso pertenece a **Madrid** Y está en estado **Reclamado** (asignado a nosotros).
    *   *Razón:* Madrid requiere normalización estricta de direcciones para el éxito del trámite.
2.  **Criterio de Prioridad:** El recurso está marcado explícitamente como **P1** (Prioridad Alta) en la base de datos.

**Para todo lo demás:**
Se DEBE usar `classify_address_fallback` (lógica determinista con Regex/Diccionarios) o devolver la dirección tal cual si el riesgo es bajo.

### Pseudocódigo del Guardián

```python
class GroqTokenGuardian:
    def can_call_llm(self, context: ResourceContext) -> bool:
        if context.is_priority_p1:
            return True
        if context.site == "madrid" and context.status == "CLAIMED":
            return True
        return False

    def classify(self, address, context):
        if self.can_call_llm(context):
            return call_groq_api(address)
        else:
            return deterministic_fallback(address)
```

---

## 4. Refactorización de Capa de Datos (DRY)

Se elimina la duplicidad de lógica SQL y construcción de payloads mediante una arquitectura de capas clara.

### A. SQL Single Source (Repositorio)
Todas las consultas SQL residirán en archivos `.sql` o en una clase `Repository` dedicada, nunca en los controladores.

*   `repositories/resource_repository.py`:
    *   `get_pending_resources()`
    *   `mark_as_completed(id)`
    *   `log_incident(id, reason)`

### B. Data Mapper (Transformador)
Transforma la tupla cruda de la DB en un objeto de dominio rico y tipado.

```python
@dataclass
class ResourceDomain:
    id: int
    expediente: str
    direccion_raw: str
    prioridad: str
    site_id: str
    # ... otros campos limpios

class ResourceMapper:
    @staticmethod
    def from_row(row: dict) -> ResourceDomain:
        return ResourceDomain(
            id=row['idRecurso'],
            expediente=clean_expediente(row['Expedient']),
            # ... transformación y limpieza aquí
        )
```

### C. Adaptadores Simplificados
Los adaptadores (`sites/madrid/adapter.py`) ya no construyen SQL ni limpian datos. Reciben un `ResourceDomain` listo para usar.

```python
class MadridAdapter(BaseAdapter):
    def process(self, resource: ResourceDomain):
        # La lógica se centra SOLO en la navegación/interacción
        payload = self.build_payload(resource) # Resource ya está limpio
        self.browser.submit(payload)
```

---

## 5. Gestión de Incidencias (Electron App)

Para que las abogadas puedan gestionar los fallos desde la App Electron, las incidencias deben estructurarse formalmente en la base de datos.

**Definición de Incidencia:**
Una entrada en la tabla `Incidencias` (o `Tramites_Log`) que impide el procesamiento automático.

**Estructura de Datos Propuesta:**

| Campo | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | UUID | Identificador único de la incidencia. |
| `resource_id` | INT | FK al recurso afectado. |
| `timestamp` | DATETIME | Cuándo ocurrió. |
| `error_code` | VARCHAR | Código máquina (ej: `ADDR_MISSING`, `WEB_TIMEOUT`, `LOGIN_FAIL`). |
| `description` | TEXT | Descripción legible para la abogada ("Falta número de calle"). |
| `status` | ENUM | `NEW`, `REVIEWED`, `RESOLVED`. |
| `screenshot_path` | VARCHAR | (Opcional) Ruta a la captura si fue fallo visual. |

**Flujo de Resolución:**
1.  Brain detecta fallo -> Crea registro en DB.
2.  Electron App hace polling a tabla `Incidencias`.
3.  Abogada corrige datos en Electron -> App actualiza `Recursos` y marca Incidencia como `RESOLVED`.
4.  Brain retoma el recurso en el siguiente ciclo (60s).

---

## 6. Gestión de Archivos y Colas

**Colas (Recomendación):**
Dado el plan de migración a Redis, se debe utilizar **Redis Streams** (ya integrado parcialmente en `brain_claim`) como cola de tareas priorizada.
*   **Stream:** `brain:tasks:pending`
*   **Consumer Group:** `brain:workers`

Esto desacopla la decisión (Brain) de la ejecución (Workers), permitiendo escalar workers horizontalmente sin bloquear el Brain principal.

**Archivos:**
Estandarizar el almacenamiento temporal en `tmp/downloads/<session_id>/`.
Implementar una clase `FileManager` que asegure la limpieza automática de estos directorios post-proceso para evitar llenar el disco.

---

**Siguientes Pasos:**
1.  Refactorizar `brain_claim/app.py` para implementar el ciclo de 60s.
2.  Crear `core/guardians/groq_guardian.py`.
3.  Definir modelos Pydantic/Dataclasses para `ResourceDomain`.
