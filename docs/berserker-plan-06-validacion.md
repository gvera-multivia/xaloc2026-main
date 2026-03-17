# Fase 6: Validacion y plan de rollback

## Checklist pre-activacion

Antes de poner berserker x4 en produccion, todos estos puntos deben estar verificados:

### Aislamiento (Fases 1-2)

- [ ] `tmp/<job_id>/` se crea al inicio de cada job y se borra al final
- [ ] Con 2 jobs concurrentes, los archivos de uno NO aparecen en el workspace del otro
- [ ] `document_fetcher` descarga a `tmp/<job_id>/downloads/` y no a `tmp/downloads/`
- [ ] AutoFirma handler y proxy usan rutas por contenedor (o contenedores separados)
- [ ] `sign_with_pfx()` no usa rutas fijas en `/tmp` (audit confirmado)

### Concurrencia (Fases 3-4)

- [ ] Runner mantiene `_EXECUTE_LOCK` — cada replica serializa internamente
- [ ] Worker con `WORKER_ENFORCE_SINGLETON=0` procesa jobs en paralelo
- [ ] Cada worker tiene `worker_instance_id` unico (UUID + hostname)
- [ ] Redis Streams consumer group con N consumers — cada job entregado a exactamente 1 consumer
- [ ] Heartbeat funciona con N workers — reconciliacion detecta workers muertos

### Infraestructura (Fase 5)

- [ ] `docker-compose.berserker.yml` aplica override correcto
- [ ] `--scale=4` levanta 4 replicas de worker y runner
- [ ] DNS round-robin de Docker funciona entre workers y runners
- [ ] Healthcheck OK en todas las replicas
- [ ] Autoheal reinicia replicas que fallen
- [ ] Sin override berserker: todo funciona como antes (regresion)

## Test de carga: protocolo

### Preparacion

1. Encolar 20+ jobs de test (mix de sites: atc, xaloc_girona, madrid, valencia)
2. Levantar berserker x4

### Metricas a observar

| Metrica | Criterio de exito |
|---------|-------------------|
| Jobs procesados/minuto | >= 3x mejora vs 1 worker |
| Cero duplicados de `idRecurso` en `processing` | `SELECT count(*) FROM jobs WHERE status='processing' GROUP BY resource_id HAVING count(*)>1` = 0 |
| Cero perdida de archivos temporales | Ningun job falla por `FileNotFoundError` en tmp |
| Cero colision de firma | Ningun job falla por firma corrupta o timeout de proxy |
| Justificantes 100% descargados | Cada job exitoso tiene su PDF/justificante trazable |
| Workers vivos N=4 | `SELECT count(*) FROM worker_runtime WHERE status='online'` = 4 |
| RAM del host | Pico < 80% de RAM disponible |

### Duracion del test

Minimo 100 jobs procesados con 4 workers activos, sin errores atribuibles a concurrencia.

## Plan de rollback

### Rollback instantaneo (< 1 minuto)

Bajar berserker y levantar el stack normal:

```bash
# Parar berserker
./scripts/berserker_down.sh

# Levantar normal
cd infra/docker
docker compose -f docker-compose.microservices.yml up -d
```

El stack normal tiene:
- `WORKER_ENFORCE_SINGLETON=1` (default)
- `container_name` fijos
- 1 runner, 1 worker
- Puertos fijos al host

**No hay migracion de datos.** Los jobs en cola se procesan normalmente. Jobs en `processing` se reconcilian por heartbeat timeout.

### Rollback de codigo

Si los cambios de Fase 1 (tmp aislado) introducen bugs:

1. Poner `BERSERKER_MODE=0` en `.env`
2. Reiniciar workers — vuelven al comportamiento legacy (tmp global)
3. No hay cambios de schema ni migraciones

### Rollback parcial

Si un site especifico da problemas con concurrencia (ej: ATC no tolera 2 sessiones simultaneas):

```env
# Limitar berserker a sites compatibles
BERSERKER_SITE_BLACKLIST=atc
```

Implementar en `consumer.py`: si el job es de un site en blacklist, el worker espera a que no haya otros jobs del mismo site en processing antes de tomarlo.

## Limites por site (opcional, Fase 3+)

Algunos portales web pueden no tolerar multiples sesiones simultaneas del mismo certificado. Si se detecta esto:

```python
# En consumer.py, antes de process_task:
if _site_concurrency_limit_reached(job.site_id):
    await queue_gateway.release(job, reason="concurrency_limit_site")
    continue
```

Con Redis:
```python
def _site_concurrency_limit_reached(site_id: str) -> bool:
    max_concurrent = int(os.getenv(f"BERSERKER_MAX_{site_id.upper()}", "0"))
    if max_concurrent <= 0:
        return False
    key = f"berserker:active:{site_id}"
    current = int(redis.get(key) or 0)
    return current >= max_concurrent
```

## Dashboard — que mostrar

Actualizar el dashboard para reflejar berserker:

1. **Workers activos**: mostrar N workers con hostname y status
2. **Jobs en paralelo**: mostrar cuantos jobs estan en `processing` simultaneamente
3. **Throughput**: jobs/minuto con grafico temporal
4. **VNC links**: si hay puertos dinamicos, mostrar link a cada replica

## Cronograma estimado

| Fase | Duracion | Dependencia |
|------|----------|-------------|
| 1. Aislamiento tmp | 1 sesion de codigo + tests | Ninguna |
| 2. Aislamiento firma | 1 sesion (mayormente audit) | Ninguna |
| 3. Runner | 30 min (solo logging) | — |
| 4. Worker | 30 min (solo config) | — |
| 5. Compose infra | 1 sesion (crear override + scripts) | Fases 1-4 |
| 6. Validacion | 1 sesion de test de carga | Fase 5 |

Total estimado: **3-4 sesiones de trabajo** para tener berserker x4 validado.
