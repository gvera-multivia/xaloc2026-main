# Documentacion Operativa y de Desarrollo (Xaloc 2026)

## Objetivo
Centralizar en `/docs` la documentacion tecnica y operativa del proyecto: arquitectura, frontend/backend, brain/worker, colas, Docker, Playwright, certificados, XVIA, blacklist/incidencias, troubleshooting, expedientes validos y alta de nuevos sites.

## Flujo de lectura recomendado
### Perfil dev (implementacion)
1. [01-arquitectura-general.md](./01-arquitectura-general.md)
2. [03-backend-servicios.md](./03-backend-servicios.md)
3. [04-brain-worker-colas.md](./04-brain-worker-colas.md)
4. [06-bots-playwright.md](./06-bots-playwright.md)
5. [12-expedientes-validos.md](./12-expedientes-validos.md)
6. [13-crear-nuevos-sites.md](./13-crear-nuevos-sites.md)

### Perfil ops (operacion diaria)
1. [05-docker-despliegue.md](./05-docker-despliegue.md)
2. [07-certificados-y-autofirma.md](./07-certificados-y-autofirma.md)
3. [08-ciclo-tramite-y-documentos.md](./08-ciclo-tramite-y-documentos.md)
4. [09-xvia-recursos-y-completado.md](./09-xvia-recursos-y-completado.md)
5. [10-blacklist-e-incidencias.md](./10-blacklist-e-incidencias.md)
6. [11-troubleshooting.md](./11-troubleshooting.md)

### Perfil soporte (incidencias y seguimiento)
1. [02-frontend-dashboard.md](./02-frontend-dashboard.md)
2. [10-blacklist-e-incidencias.md](./10-blacklist-e-incidencias.md)
3. [11-troubleshooting.md](./11-troubleshooting.md)
4. [09-xvia-recursos-y-completado.md](./09-xvia-recursos-y-completado.md)

## Mapa de documentos
- [01-arquitectura-general.md](./01-arquitectura-general.md): vista extremo a extremo de componentes y dominios.
- [02-frontend-dashboard.md](./02-frontend-dashboard.md): estructura Next.js, paginas, auth y websocket.
- [03-backend-servicios.md](./03-backend-servicios.md): API dashboard y microservicios Python.
- [04-brain-worker-colas.md](./04-brain-worker-colas.md): claim, validacion, batch, jobs y consumo worker.
- [05-docker-despliegue.md](./05-docker-despliegue.md): compose, dependencias, arranque, diagnostico.
- [06-bots-playwright.md](./06-bots-playwright.md): ejecucion de bots por site, runner remoto y artefactos.
- [07-certificados-y-autofirma.md](./07-certificados-y-autofirma.md): inyeccion de certificado, policies, protocolo `afirma://`.
- [08-ciclo-tramite-y-documentos.md](./08-ciclo-tramite-y-documentos.md): ciclo de tramite y guardado de justificantes.
- [09-xvia-recursos-y-completado.md](./09-xvia-recursos-y-completado.md): seleccion, completado y deseleccion de recursos en XVIA.
- [10-blacklist-e-incidencias.md](./10-blacklist-e-incidencias.md): bloqueo de recursos e incidencias operativas.
- [11-troubleshooting.md](./11-troubleshooting.md): playbooks por sintoma.
- [12-expedientes-validos.md](./12-expedientes-validos.md): reglas por organismo/site para expedientes procesables.
- [13-crear-nuevos-sites.md](./13-crear-nuevos-sites.md): guia de alta de un site nuevo (standalone -> produccion).

## Puntos criticos globales
- El sistema usa Redis Streams como backbone de cola (`candidates`, `validated`, `jobs`, `dlq:*`).
- Brain y Worker se coordinan contra Postgres de control (`job_drafts`, `jobs`, runtime, blacklist, incidencias).
- El completado funcional no es solo "submit en web": incluye marcado XVIA, recibos y estado operacional.
- Certificados y AutoFirma requieren configuracion de navegador + handler de protocolo en runner.

## Comandos utiles
```powershell
# Levantar stack principal
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml up -d --build

# Ver logs de servicios clave
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml logs -f --tail=200 brain-claim-service payload-validator-service batcher-dispatcher-service worker-orchestrator-service playwright-runner-service

# Estado rapido de healthchecks
docker compose -f infra/docker/docker-compose.microservices.yml ps
```

## Checklist de mantenimiento de docs
- [ ] Los nombres de servicios y streams coinciden con `infra/docker/docker-compose.microservices.yml` y codigo actual.
- [ ] Los endpoints citados siguen existentes en `dashboard_api.py`.
- [ ] Los runbooks de certificados/firma reflejan el entrypoint actual de runner.
- [ ] Las guias de nuevos sites siguen el patron real de `sites/`, `sites/adapters` y `services/brain_claim/app.py`.






# IMPORTANTE

> Si se quieren aplicar cambios a las automatizaciones correr desde el directorio base del proyectos `python scripts/stack_control.py --restart`

> Si se quieren aplicar cambios a la naturaleza de docker (cambiar el compose o algo asi) `python scripts/stack_control.py --restart-rebuild`

> Si se quiere apagar todo `python scripts/stack_control.py --stop`

> Si se quiere iniciar `python scripts/stack_control.py --start`



USUARIO ADMINISTRADOR SEED -> TheMorrigan
PWD -> WeAreTheMorrigan


> Los datos en el .evn son criticos, si se borra la cuenta de correo de gvera@xvia-serviciosjuridicos.com tendreis que cambiar los datos. (cambiar cuenta y contraseña de la pagina de Juan para que no dependa de la mia)

> Lo mismo para el perfil movil de windows, habra que cambiarlo en el .env

> Y posiblemente lo mismo para la api de groq, habra que crear una nueva cuenta en groq y pillar un nuevo token, todo esto se pone en el .env del directorio base




> Por si os interesa hay una api de mapas de toda españa hosteada en este proyecto (CARTOCIUDAD) se puede ver en el puerto 8020


Si todo esta bien y corriendo en este ordenador podreis ver Morrigan corriendo en 192.184.168.72 (sin especificar puerto)

Y cartociudad api en 192.184.168.72:8020 o 192.184.168.72:8020/docs para ver el Swagger