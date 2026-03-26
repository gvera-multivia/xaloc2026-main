# 13 - Como Crear Nuevos Sites

## Objetivo
Definir un procedimiento completo para crear un nuevo site Playwright y llevarlo de standalone local a integracion productiva con brain/worker/dashboard.

## Flujo recomendado
```mermaid
graph LR
    A[Standalone local] --> B[Registro site runtime]
    B --> C[Adapter + Brain claim]
    C --> D[Pipeline queue/worker]
    D --> E[Dashboard config/visibilidad]
    E --> F[Hardening cert/firma]
    F --> G[Go live controlado]
```

## Fase 1: Standalone (smoke local)
1. Crear `sites/<site_id>/`:
- `config.py`
- `data_models.py`
- `controller.py`
- `automation.py`
- `flows/*.py`

2. Registrar en `core/site_registry.py`.

3. Crear script tipo `main_<site_id>_payload_by_id.py`:
- consulta SQL por `idRecurso`.
- construye payload.
- prueba `--dump-only` y `--run-flow`.

4. Validar punto de parada seguro (si aplica "no enviar" en esta fase).

## Fase 2: Integracion productiva
1. Adapter:
- crear `sites/adapters/<site_id>.py` con:
  - `fetch_candidates(...)`
  - `build_payloads(...)`
- exportar en `sites/adapters/__init__.py`.

2. Brain:
- registrar adapter en `services/brain_claim/app.py` (`self.adapters`).

3. Config:
- anadir entrada en `organismo_config.json`.
- sincronizar/actualizar en PG (`organismo_config`).

4. Worker:
- confirmar que payload preserva `idRecurso`.
- validar cierre XVIA (`mark_resource_complete`) o excepcion documentada por site.

5. Dashboard:
- validar `GET /api/config`.
- validar visibilidad en `/gestion` (`KNOWN_SITES` si aplica).

## Fase 3: Certificado y login
Actualizar origenes/patrones en:
- `core/base_automation.py`
- `infra/docker/playwright-runner-entrypoint.sh`
- `url-cert-config.bat` (si aplica entorno Windows policy)

## Validacion final
1. Compilar modulos tocados.
2. Ejecutar ciclo controlado con pocos recursos.
3. Verificar:
- claim brain ok
- paso por streams (`candidates -> validated -> jobs`)
- worker ejecuta flow sin errores sistemicos
- recurso completado o incidencias explicables
- justificante/path final correcto

## Comandos utiles
```powershell
# Validacion de imports
python -m py_compile core/site_registry.py
python -m py_compile services/brain_claim/app.py
python -m py_compile sites\\<site_id>\\automation.py
python -m py_compile sites\\adapters\\<site_id>.py

# Logs de pipeline durante canary
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=200 brain-claim-service payload-validator-service batcher-dispatcher-service worker-orchestrator-service playwright-runner-service
```

## Puntos criticos
- Si el adapter no se registra en brain, el site nunca entra en flujo.
- Si falta config activa en `organismo_config`, brain lo ignorara aunque exista codigo.
- Sin ajustes de certificado/origen, login por cert puede fallar aunque el flow sea correcto.
- Publicar sin canary aumenta riesgo de blacklists masivas por reglas incompletas.

## Checklist de done
- [ ] Site ejecuta standalone con payload real.
- [ ] Site/adapters registrados y compilando.
- [ ] Config activa en dashboard y control plane.
- [ ] Pipeline end-to-end validado en entorno controlado.
- [ ] Runbook operativo especifico del site creado en `/docs` o docs internas del site.
