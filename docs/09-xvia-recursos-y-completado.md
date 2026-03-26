# 09 - XVIA: Seleccion de Recursos y Completado

## Objetivo
Documentar como el sistema selecciona recursos en XVIA, cuando los marca como completados y cuando los libera (deselect) en fallos finales.

## Flujo XVIA
```mermaid
graph TD
    A[Brain candidate SQL] --> B[POST /telematicos/Asignado recursosSel=0]
    B --> C[verify claim in SQL Estado=1 UsuarioAsignado=auth_user]
    C --> D[publish candidate -> cola]

    D --> E[Worker ejecuta tramite]
    E -->|success y policy permite| F[POST /telematicos/Completado]
    E -->|fallo final/non-retry| G[POST /telematicos/Asignado recursosSel=0 (deselect)]
    G --> H[block_resource en blacklist]
```

## Seleccion de recurso (claim)
- Se ejecuta en `services/brain_claim/app.py`.
- Operacion:
  - obtiene CSRF token de telematicos.
  - hace POST a endpoint `Asignado` con `id` y `recursosSel=0`.
- Luego verifica en SQL Server que el recurso quedo asignado al usuario autenticado.

## Marcado como completado
- Se ejecuta desde `core/worker_execution/task_orchestrator.py`.
- Llama `mark_resource_complete(...)` en `core/xvia_auth.py`.
- Endpoint: `/servicio/recursos/telematicos/Completado`.
- Condiciones:
  - normalmente en `outcome.success`.
  - algunos sites aplican restricciones por justificante/flags.

## Deseleccion (liberar recurso)
- Se ejecuta en fallos no reintentables o reintentos agotados.
- Llama `deselect_resource(...)` en `core/xvia_deselect.py`.
- Endpoint: `/servicio/recursos/telematicos/Asignado`.
- Tras fallo final puede bloquear el recurso en blacklist para evitar bucles.

## Puntos criticos
- Claim y complete dependen de sesion XVIA viva; redireccion a login invalida operacion.
- No todo success de browser equivale a complete en XVIA; hay que validar respuesta.
- Deseleccion + blacklist se usan para contener errores repetitivos.

## Comandos utiles
```powershell
# Buscar llamadas a completado/deselect
rg -n "mark_resource_complete|deselect_resource|Completado|Asignado" core services

# Ver logs worker de cierre XVIA
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=300 worker-orchestrator-service
```

## Checklist operativo
- [ ] Brain reclama y verifica en SQL (estado/usuario).
- [ ] Worker marca completado solo tras exito real.
- [ ] Fallo final libera recurso en XVIA cuando procede.
- [ ] Recursos fallidos finales se bloquean para evitar retrabajo automatico.
