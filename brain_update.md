# brain_update.md — Estudio y tareas para completar la integración del orquestador

## Objetivo
Completar `brain.py` para que siga el **mismo flujo y características** de `claim_one_resource.py`, pero **reclamando múltiples recursos por ciclo**, y que sea **funcional para Xaloc (xaloc_girona)** desde el primer entregable, dejando el diseño preparado para añadir más webs (site_id) sin rehacer el flujo.

> Nota: en el request se menciona “barin.py”; en el repo el fichero es `brain.py`.

---

## Flujo real en `claim_one_resource.py` (lo que funciona hoy)
1. Login en XVIA con `aiohttp` (`create_authenticated_session_in_place`).
2. Obtiene el **nombre real** del usuario autenticado (scraping de `/home`).
3. Consulta SQL Server buscando **candidatos** con:
   - `Organisme LIKE config.query_organisme`
   - `TExp IN (config.filtro_texp)`
   - `Estado IN (0,1)` (libre o ya en curso)
   - `Expedient` válido por regex (`config.regex_expediente`)
   - Incluye `UsuarioAsignado` y hace join para datos extra + adjuntos.
4. Selección del candidato:
   - Si `Estado == 0`: es “LIBRE” → intenta claim vía POST a `/AsignarA`.
   - Si `Estado == 1`: **solo es elegible si** `UsuarioAsignado == authenticated_user` → se considera “ya asignado a ti” y **se salta el POST**.
5. Verificación post-claim:
   - Comprueba en SQL Server que el recurso quedó en `Estado=1` y asignado al usuario autenticado.
6. Encola la tarea en SQLite con un **payload completo para Xaloc** (motivos, mandatario, matrícula, etc.).

---

## Estado actual de `brain.py` (gaps vs. `claim_one_resource.py`)
**Lo que ya hace bien**
- Tiene bucle y multi-claim (`MAX_CLAIMS_PER_CYCLE`).
- Hace login y obtiene `authenticated_user`.
- Reclama vía POST `/AsignarA` y verifica en DB (aunque sin retries/esperas).
- Inserta en `tramite_queue`.

**Gaps que impiden “integración completa” para Xaloc**
1. **Consulta SQL incompleta**: solo trae `Estado=0` y pocos campos (no matrícula, no datos mandatario, no `UsuarioAsignado`, no adjuntos).
2. **No soporta recuperar “Estado=1 asignado a mí”** (caso crítico para resiliencia/reintentos).
3. **Payload insuficiente para `worker.py` + `sites/xaloc_girona/controller.py`**:
   - Faltan campos obligatorios para Xaloc: `user_email`, `denuncia_num`, `plate_number`, `expediente_num`, `motivos`, `mandatario`, etc.
4. **Adjuntos**:
   - El worker solo descarga adjuntos si `payload.adjuntos[]` incluye `id`, `filename` y `url`. `brain.py` no los prepara.
5. **Verificación de claim frágil**:
   - `brain.py` verifica inmediatamente; `claim_one_resource.py` espera (mínimo) y reduce falsos negativos.
6. **Extensibilidad por site_id**:
   - `brain.py` tiene un `build_payload()` “genérico” que no escala a múltiples webs (cada web necesita mapping distinto).

---

## Diseño propuesto (Xaloc-first, extensible)

### Principio
Separar en el orquestador lo que es **común** (login, claim, verify, encolar, métricas) de lo que es **por site** (query + payload + reglas extra).

### Abstracción mínima
Crear un “adapter” por `site_id` con responsabilidades:
- `fetch_candidates(config, conn_str, authenticated_user) -> list[Candidate]`
  - Hace la query (incluyendo joins), agrupa adjuntos y aplica filtros finales.
- `build_payload(candidate, config) -> dict`
  - Produce un payload compatible con el worker del site.

En el primer entregable solo existe `XalocAdapter` (xaloc_girona). Para otros `site_id`, el brain:
- o bien los ignora con warning (“adapter no implementado”),
- o bien queda controlado por una allowlist configurable.

---

## Tareas a implementar (sin código aún)

### P0 — Dejar Xaloc funcionando end-to-end
- [ ] **Añadir un mecanismo “Xaloc-only” flexible**:
  - Opción A: env `BRAIN_ENABLED_SITES=xaloc_girona` (allowlist CSV).
  - Opción B: filtro en `get_active_configs()` que solo retorne los `site_id` permitidos.
  - Criterio: con config de otros sites activos, `brain.py` no debe romper ni intentar encolar payloads incorrectos.

- [ ] **Unificar query de Xaloc con joins y adjuntos (como mínimo lo que necesita el payload)**:
  - Basarse en `sync_by_id_to_worker.py` (`BASE_SELECT_QUERY`) o en el SELECT de `claim_one_resource.py`.
  - Incluir campos necesarios para Xaloc: `Expedient`, `FaseProcedimiento`, `matricula`, `sujeto_recurso`, datos de mandatario (CIF/NIF/razón social/nombre/apellidos) y adjuntos (`adjunto_id`, `adjunto_filename`).
  - Cambiar filtro a `Estado IN (0,1)` + traer `UsuarioAsignado`.

- [ ] **Implementar soporte para “Estado=1 asignado a mí”**:
  - Si `Estado==1` y `UsuarioAsignado == authenticated_user`: **no hacer POST**, pero **sí encolar**.
  - Si `Estado==1` y `UsuarioAsignado != authenticated_user`: descartar.

- [ ] **Reemplazar `BrainOrchestrator.build_payload()` por builder Xaloc (payload completo)**:
  - Reutilizar la lógica de `sync_by_id_to_worker.py::_map_payload()` (recomendado) o `claim_one_resource.py::enqueue_task()`.
  - Debe cumplir mínimos para `sites/xaloc_girona/controller.py`:
    - `user_email` (o `email`)
    - `denuncia_num`
    - `plate_number`
    - `expediente_num`
    - `motivos`
    - `mandatario`
    - `fase_procedimiento`
  - Mantener compatibilidad con `mark_resource_complete()`:
    - incluir `idRecurso`, `expediente` (alias) y `sujeto_recurso` (o `SujetoRecurso`).

- [ ] **Adjuntos: construir `payload.adjuntos[]` con `url`**:
  - `url` debe seguir el template que ya usa `AttachmentDownloader.URL_TEMPLATE`:
    - `/servicio/recursos/expedientes/pdf-adjuntos/{id}`
  - Criterio: si hay adjuntos en SQL, el worker debe poder descargarlos sin `KeyError`.

- [ ] **Verificación de claim con retries/backoff**:
  - Tras POST a `/AsignarA`, reintentar `verify_claim_in_db()` 3–5 veces con espera corta (p.ej. 0.5s, 1s, 2s…).
  - Criterio: reducir falsos negativos por latencia de actualización en SQL Server.

- [ ] **Evitar duplicados en la cola** (especialmente para los “Estado=1”):
  - Opción A: añadir columnas `remote_id`/`id_recurso` en `tramite_queue` + índice UNIQUE `(site_id, remote_id)` (recomendado).
  - Opción B: buscar duplicados por JSON en `payload` (más frágil).
  - Criterio: un mismo `idRecurso` no debe generar múltiples filas `pending/processing` para el mismo `site_id`.

### P1 — Refactor para extensibilidad real (sin cambiar el flujo)
- [ ] **Crear interfaz/contrato de “site adapter”**:
  - `supports(site_id)`, `fetch_candidates(...)`, `build_payload(...)`.
  - En `brain.py`, resolver adapter por `site_id` y si no existe → warning + skip.

- [ ] **Extraer utilidades comunes de XVIA** (para no duplicar):
  - Obtener `authenticated_user` (scraping `/home`).
  - Claim POST + obtención token CSRF (idealmente usando `core.xvia_auth.extract_csrf_token`).
  - Verify claim (con retries).

- [ ] **Centralizar construcción de payload Xaloc**:
  - Mover la lógica compartida (motivos + mandatario + normalización matrícula) a un módulo reusable (p.ej. `core/payloads/xaloc.py`).
  - Objetivo: que `claim_one_resource.py`, `sync_by_id_to_worker.py` y `brain.py` usen la misma fuente.

### P2 — Observabilidad / operativa
- [ ] **Métricas por ciclo y por site**:
  - candidatos vistos, descartados (regex/usuario), claimed (POST), encolados, duplicados evitados, errores.
- [ ] **Modo “solo recuperar asignados”** (operativo):
  - env `BRAIN_RECOVER_ONLY=1` para procesar solo `Estado=1` asignados a mí.

---

## Checkpoints de validación (qué debería probarse al implementar)
- [ ] **Dry-run**: `python brain.py --once --dry-run` no debe hacer POST ni insertar, pero sí loguear candidatos y decisiones (Estado 0 vs 1).
- [ ] **Payload contract**: una tarea encolada para `xaloc_girona` debe pasar `sites/xaloc_girona/controller.py:create_target()` sin `ValueError` por campos faltantes.
- [ ] **Adjuntos**: si hay `adjunto_id` en SQL, el worker debe descargarlo (sin `KeyError: 'url'`).
- [ ] **Recuperación**: si un recurso queda `Estado=1` asignado a mi usuario y el worker cayó, al reiniciar `brain.py` debe re-encolarlo **una sola vez**.

