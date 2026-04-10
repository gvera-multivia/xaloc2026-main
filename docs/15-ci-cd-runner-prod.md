# 15. CI/CD runner self-hosted en VM Linux

## Objetivo

Cada `push` a `main` debe disparar un deploy automatico en la VM Linux de produccion usando GitHub Actions y un runner self-hosted.

## Convenciones operativas

- Runner labels esperadas:
  - `self-hosted`
  - `linux`
  - `xaloc-prod`
- Ruta fija del checkout persistente:
  - `/opt/xaloc/xaloc2026-main`
- `.env` operativo fuera del repo:
  - `/opt/xaloc/env/xaloc.env`
- Compose operativo:
  - `/opt/xaloc/xaloc2026-main/infra/docker/docker-compose.microservices.yml`
- Comando canonico de deploy:
  - `python3 scripts/stack_control.py --restart-rebuild`

## Workflow incluido

El workflow esta en:

- `.github/workflows/deploy-prod-vm.yml`

Orden de ejecucion:

1. `actions/checkout` del repo del workflow.
2. Prechecks del runner y del entorno de deploy.
3. Checks minimos previos.
4. `git fetch/reset/clean` sobre el checkout persistente de `/opt/xaloc/xaloc2026-main`.
5. `python3 scripts/stack_control.py --restart-rebuild ...`
6. Smoke checks HTTP basicos.
7. Si falla, recolecta `docker compose ps/logs` y los sube como artefacto.

## Scripts auxiliares

- `scripts/deploy_precheck.py`
- `scripts/collect_deploy_diagnostics.py`

## Provisionado minimo de la VM

Instalar Docker, Compose plugin, Python, Git y registrar el runner:

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates python3 python3-pip docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker <runner_user>
```

Crear rutas persistentes:

```bash
sudo mkdir -p /opt/xaloc
sudo mkdir -p /opt/xaloc/env
sudo chown -R <runner_user>:<runner_user> /opt/xaloc
```

Clonar repo:

```bash
git clone <repo_url> /opt/xaloc/xaloc2026-main
```

Copiar `.env` operativo:

```bash
cp /ruta/segura/xaloc.env /opt/xaloc/env/xaloc.env
chmod 600 /opt/xaloc/env/xaloc.env
```

## Instalar el runner de GitHub Actions

En la VM, con el usuario que ejecutara el runner:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-x64.tar.gz -L https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64.tar.gz
tar xzf actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/<owner>/<repo> --token <runner_registration_token> --labels self-hosted,linux,xaloc-prod --unattended
sudo ./svc.sh install
sudo ./svc.sh start
```

Verificar:

```bash
sudo ./svc.sh status
```

## Drift local y reset

El workflow resetea siempre el checkout persistente:

```bash
git -C /opt/xaloc/xaloc2026-main fetch --prune origin main
git -C /opt/xaloc/xaloc2026-main reset --hard origin/main
git -C /opt/xaloc/xaloc2026-main clean -fdx
```

Esto implica que:

- no debes guardar secretos dentro del repo
- `.env` debe vivir fuera del repo
- cualquier cambio manual en `/opt/xaloc/xaloc2026-main` se perdera en el siguiente deploy

## Verificacion manual

Puedes simular el deploy en la VM con:

```bash
cd /opt/xaloc/xaloc2026-main
python3 scripts/deploy_precheck.py \
  --repo-path /opt/xaloc/xaloc2026-main \
  --env-file /opt/xaloc/env/xaloc.env \
  --compose-file /opt/xaloc/xaloc2026-main/infra/docker/docker-compose.microservices.yml

python3 scripts/stack_control.py \
  --restart-rebuild \
  --env-file /opt/xaloc/env/xaloc.env \
  --compose-file /opt/xaloc/xaloc2026-main/infra/docker/docker-compose.microservices.yml \
  --timeout 1800 \
  --interval 5
```

## Comportamiento de concurrencia

- Solo se permite un deploy activo a la vez para `main`.
- Si entra un push mas nuevo, se cancela el deploy anterior en curso.
- El job tiene `timeout` explicito para que no quede colgado indefinidamente.
