---
name: xaloc-project-connection-ops
description: Operar Xaloc en VM (morrigan) y validar conectividad end-to-end (SSH, env, SQLServer, Docker Compose, API y dashboard). Usar cuando haya que arrancar, desplegar, comprobar salud o resolver problemas de conexion y configuracion.
---

# Xaloc Project Connection Ops

## Overview

Skill operativa para ejecutar y mantener Xaloc en la VM de produccion, con foco en conectividad y consistencia de entorno.

## Workflow

1. Validar acceso base y rutas.
- SSH a VM `morrigan@192.168.184.130`
- Repo: `/opt/xaloc/xaloc2026-main`
- Env: `/opt/xaloc/env/xaloc.env`

2. Confirmar prerequisitos de entorno.
- Docker daemon accesible.
- `xaloc.env` presente y con claves SQLServer.
- Certificado presente en ruta persistente:
`/opt/xaloc/certificates/certificate.pfx`

3. Arrancar o reconstruir stack.
- Arranque normal:
`python3 scripts/stack_control.py --start --env-file /opt/xaloc/env/xaloc.env --compose-file infra/docker/docker-compose.microservices.yml`
- Rebuild completo:
`python3 scripts/stack_control.py --restart-rebuild --env-file /opt/xaloc/env/xaloc.env --compose-file infra/docker/docker-compose.microservices.yml`

4. Verificar conectividad funcional.
- Health global: `http://127.0.0.1/health`
- Swagger global: `http://127.0.0.1/docs`
- Cartociudad OpenAPI: `http://127.0.0.1/cartociudad/openapi.json`
- Estado contenedores: `docker compose ... ps`

5. Verificar inyeccion SQLServer en runtime.
- Comprobar `SQLSERVER_*` en servicios criticos:
`xaloc-dashboard-backend`, `xaloc-brain-claim`, `xaloc-worker-orchestrator`
- Revisar logs ultimos minutos buscando `08001`.

6. Corregir y revalidar si falla.
- Si falta variable en contenedor: corregir `infra/docker/docker-compose.microservices.yml`.
- Si falta valor: sincronizar `.env` local a `/opt/xaloc/env/xaloc.env`.
- Recreate del servicio afectado y repetir checks.

## Required References

- Deploy CI runner:
`docs/15-ci-cd-runner-prod.md`
- Sync de mapas cartociudad:
`docs/16-cartociudad-mapas-sync.md`

## Output Contract

Al cerrar una ejecucion con esta skill, devolver:

1. Estado del stack (`up/healthy` por servicio).
2. Estado de endpoints clave (`/health`, `/docs`, `/cartociudad/openapi.json`).
3. Estado SQLServer (`SQLSERVER_*` inyectadas y errores `08001` recientes).
4. Acciones aplicadas (archivo/servicio tocado).
5. Riesgos abiertos si los hubiera.

## Non-goals

- No modificar logica de negocio de sites.
- No cambiar credenciales funcionales sin validacion explicita.
- No abrir puertos publicos extra fuera de lo acordado.
