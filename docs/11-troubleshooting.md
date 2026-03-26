# 11 - Troubleshooting

## Objetivo
Proveer playbooks operativos por sintoma para resolver incidencias de cola, firma, certificados, runner, XVIA y dashboard.

## Flujo general de diagnostico
1. Identificar capa afectada: UI, API, cola, worker, runner, site, XVIA, almacenamiento.
2. Validar salud de contenedores y dependencias (Redis/Postgres).
3. Revisar logs del servicio exacto.
4. Corregir configuracion/datos.
5. Reintentar de forma controlada y confirmar cierre.

## Sintoma: cola atascada (jobs no avanzan)
### Senales
- `jobs` stream crece, pero worker no completa.
- Muchos pendientes en PEL/processing.

### Pasos
```powershell
docker compose -f infra/docker/docker-compose.microservices.yml ps
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=200 worker-orchestrator-service batcher-dispatcher-service payload-validator-service

docker exec -it xaloc-redis redis-cli XINFO GROUPS jobs
docker exec -it xaloc-redis redis-cli XPENDING jobs worker_group
```
- Verificar `QUEUE_STREAM_PENDING_CLAIM_MIN_IDLE_MS` y reclamacion de jobs huerfanos.
- Revisar pausas activas por site/recurso en dashboard.

### Checklist
- [ ] Worker online y consumiendo.
- [ ] No hay pausa global accidental.
- [ ] Reclaim/autoclaim activo para mensajes idle.

## Sintoma: fallo de firma/AutoFirma
### Senales
- Timeout tras disparar firma.
- No cambia estado a `Completada/Registrada`.

### Pasos
```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=300 playwright-runner-service worker-orchestrator-service
```
- Confirmar que handler `afirma://` captura URI.
- Confirmar modo correcto (websocket vs sign/bridge).
- Validar callback final y reflejo en pagina padre (no solo callback ok).

### Checklist
- [ ] URI capturada.
- [ ] Proxy/bridge activo segun modo.
- [ ] Estado final visible en UI objetivo.

## Sintoma: certificado no seleccionado
### Senales
- Popup de seleccion manual.
- Error de carga de client cert.

### Pasos
```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml config
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=300 playwright-runner-service
```
- Revisar `PLAYWRIGHT_CERT_PATH`, password, origins.
- Revisar policies escritas e import NSS exitosa.

### Checklist
- [ ] PFX accesible.
- [ ] Password valida.
- [ ] Origins exactos.
- [ ] Cert presente en NSS.

## Sintoma: recurso no se marca completado en XVIA
### Senales
- Tramite exitoso en sede pero sigue pendiente en XVIA.

### Pasos
- Revisar logs de `mark_resource_complete`.
- Confirmar sesion XVIA vigente (sin redirect a login).
- Confirmar que no se disparo regla de bloqueo por falta de justificante.

### Checklist
- [ ] POST `/Completado` responde ok.
- [ ] No hubo condicion `skip_auto_complete` inesperada.
- [ ] Hay evidencia de tramite completo.

## Sintoma: justificante no guardado en carpeta cliente
### Senales
- `*_justificante_descargado=false` o path vacio.

### Pasos
- Revisar logs de flow del site y `justificantes_storage`.
- Verificar montajes SMB y permisos de `/mnt/clientes`.
- Revisar resolucion identidad cliente/ruta fase.

### Checklist
- [ ] Carpeta cliente resoluble.
- [ ] Archivo temporal descargado.
- [ ] Copia final exitosa en RECURSOS TELEMATICOS.

## Sintoma: incidencia recurrente de expediente invalido
### Pasos
- Revisar adapter del site (`REGEX_DISCARDED` / `SITE_RULE_DISCARDED`).
- Revisar `organismo_config` (`query_organisme`, `regex_expediente`, `filtro_texp`).
- Ajustar reglas y validar con muestra real.

## Puntos criticos
- No desbloquear/reintentar masivamente sin entender causa raiz.
- Diferenciar problema infra (contenedor/dependencia) de problema negocio (datos/reglas).
- Registrar cada ajuste de reglas en changelog operativo.

## Checklist final de recuperacion
- [ ] Causa raiz identificada.
- [ ] Fix aplicado en capa correcta.
- [ ] Reintento controlado exitoso.
- [ ] Monitoreo post-fix sin regresion.
