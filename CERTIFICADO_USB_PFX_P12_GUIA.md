# Guia Detallada: Instalar Certificado `.pfx/.p12` desde USB (Windows + Docker)

Esta guia esta pensada para tu proyecto en:

- `C:\Users\Guillem Vera\Desktop\Proyectos\xaloc2026-main`

Objetivo:

1. Instalar el certificado en Windows (si lo necesitas para navegador/AutoFirma).
2. Dejarlo montado y usable por `signing-service` en Docker.
3. Verificar extremo a extremo que la arquitectura lo ve.

## 1. Antes de empezar

Necesitas:

- El archivo en USB: `.pfx` o `.p12`.
- La contrasena del certificado (PIN de importacion).
- Docker Desktop en estado `Engine running`.

Ruta esperada por esta arquitectura:

- Host: `certificates/certificate.pfx`
- Contenedor: `/data/certificates/certificate.pfx`
- Variable actual: `SIGNING_CERT_PATH=/data/certificates/certificate.pfx`

## 2. Copiar desde USB al repo

Abre PowerShell en la raiz del proyecto:

```powershell
cd "C:\Users\Guillem Vera\Desktop\Proyectos\xaloc2026-main"
```

Crea carpeta si no existe:

```powershell
New-Item -ItemType Directory -Force -Path .\certificates | Out-Null
```

Copia desde USB:

- Si el USB tiene `.pfx`, copialo como `certificate.pfx`.
- Si el USB tiene `.p12`, copialo igual pero renombrando a `certificate.pfx`.

Ejemplo (ajusta letra/ruta USB):

```powershell
Copy-Item "E:\MiCertificado.p12" ".\certificates\certificate.pfx" -Force
```

Verifica existencia:

```powershell
Test-Path .\certificates\certificate.pfx
```

Debe devolver `True`.

## 3. (Opcional) Instalar en Windows para navegador/AutoFirma

Si solo lo usa Docker, puedes saltar esta seccion.

1. Doble clic en `certificates\certificate.pfx`.
2. Elige `Usuario actual` (recomendado).
3. Introduce la contrasena.
4. Marca `Marcar esta clave como exportable` solo si lo necesitas.
5. Selecciona almacen `Personal`.
6. Finaliza.

Verificacion:

```powershell
certmgr.msc
```

Revisa `Personal > Certificados` y confirma que aparece con clave privada.

## 4. Verificar variables y compose

Confirma `.env`:

```powershell
Select-String -Path .\.env -Pattern "^SIGNING_CERT_PATH="
```

Debe ser:

- `SIGNING_CERT_PATH=/data/certificates/certificate.pfx`

Confirma montaje en compose:

```powershell
Select-String -Path .\infra\docker\docker-compose.microservices.yml -Pattern "certificates|signing-service"
```

Debe aparecer:

- `../../certificates:/data/certificates:ro`

## 5. Levantar/recrear servicios de firma

Para asegurar que el contenedor vea el fichero nuevo:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml up -d --build signing-service
```

Si quieres refrescar tambien backend/gateway:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml up -d --build dashboard-backend-service api-gateway signing-service
```

## 6. Verificar que el contenedor ve el certificado

Lista archivos dentro del contenedor:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec signing-service sh -lc "ls -l /data/certificates"
```

Debe verse `certificate.pfx`.

Comprueba el path de entorno dentro del contenedor:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.microservices.yml exec signing-service sh -lc "echo \$SIGNING_CERT_PATH"
```

Debe devolver:

- `/data/certificates/certificate.pfx`

Health del servicio:

```powershell
curl.exe http://localhost:8112/health
```

Debe devolver estado `200`.

## 7. Verificacion completa de arquitectura

Ejecuta tu validador:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate_migration.ps1 -SkipBuild
```

Revisa:

- `logs/migration_validation_*.log`
- `logs/migration_validation_*.summary.json`

## 8. Errores tipicos y solucion directa

`No such file or directory` en `/data/certificates/certificate.pfx`:

- El archivo no esta en `.\certificates\certificate.pfx` en host.
- Solucion: copiar bien desde USB y recrear `signing-service`.

Permisos denegados al copiar desde USB:

- Cierra explorador/antivirus sobre el archivo.
- Copia con PowerShell y verifica `Test-Path`.

`dockerDesktopLinuxEngine` acceso denegado:

- Docker Desktop no esta operativo o sin permisos.
- Abre Docker Desktop y espera `Engine running`.

Se usa otro nombre (`.p12`) y no lo detecta:

- En esta arquitectura el nombre esperado es `certificate.pfx`.
- Renombralo al copiar.

## 9. Seguridad recomendada (minimo)

- No subas `certificates/certificate.pfx` al repositorio.
- Mantener `certificates/` en `.gitignore`.
- No compartir la contrasena por chat/log.
- Si sospechas compromiso, revoca y reemite certificado.
