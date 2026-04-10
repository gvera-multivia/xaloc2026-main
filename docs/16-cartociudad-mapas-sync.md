# 16. Cartociudad MAPAS en VM

## Objetivo

Poblar `cartociudad-api/MAPAS` en la VM para que el bind mount del compose:

- `../../cartociudad-api/MAPAS:/app/MAPAS:ro`

quede con datos reales (`.gpkg`) dentro del contenedor `cartociudad-api`.

## Ruta esperada en VM

- Repo en VM: `/opt/xaloc/xaloc2026-main`
- Carpeta MAPAS en VM: `/opt/xaloc/xaloc2026-main/cartociudad-api/MAPAS`
- Ruta en contenedor: `/app/MAPAS`

## Sincronizar MAPAS desde tu equipo a VM

Ejecutar desde PowerShell local:

```powershell
scp -i "$env:USERPROFILE\.ssh\morrigan_vm_ed25519" -r `
  "C:\Users\Guillem Vera\Desktop\Proyectos\xaloc2026-main\cartociudad-api\MAPAS" `
  morrigan@192.168.184.130:/opt/xaloc/xaloc2026-main/cartociudad-api/
```

Si prefieres `rsync` (Linux/WSL):

```bash
rsync -av --delete -e "ssh -i ~/.ssh/morrigan_vm_ed25519" \
  /mnt/c/Users/Guillem\ Vera/Desktop/Proyectos/xaloc2026-main/cartociudad-api/MAPAS/ \
  morrigan@192.168.184.130:/opt/xaloc/xaloc2026-main/cartociudad-api/MAPAS/
```

## Permisos en VM

```bash
ssh -i ~/.ssh/morrigan_vm_ed25519 morrigan@192.168.184.130 \
  "chmod -R a+rX /opt/xaloc/xaloc2026-main/cartociudad-api/MAPAS"
```

## Rebuild/arranque del stack

En la VM:

```bash
cd /opt/xaloc/xaloc2026-main
python3 scripts/stack_control.py \
  --restart-rebuild \
  --env-file /opt/xaloc/env/xaloc.env \
  --compose-file infra/docker/docker-compose.microservices.yml
```

## Verificación

En la VM:

```bash
find /opt/xaloc/xaloc2026-main/cartociudad-api/MAPAS -maxdepth 2 -type f -name "*.gpkg" | head
docker exec cartociudad-api find /app/MAPAS -maxdepth 3 -type f -name "*.gpkg" | head
curl -fsS http://127.0.0.1/cartociudad/openapi.json >/dev/null && echo "cartociudad OK"
```

Si el primer `find` devuelve ficheros pero el segundo no, el contenedor está usando una versión anterior y hay que relanzar el `--restart-rebuild`.
