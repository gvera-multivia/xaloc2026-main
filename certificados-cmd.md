# Configurar autoselección de certificado en Edge (sin PowerShell)

Estas instrucciones sirven cuando en el servidor está deshabilitada la ejecución de scripts en PowerShell y no puedes usar `setup_worker_env.ps1`.

## Requisitos

- Windows + Microsoft Edge instalado.
- Abrir `cmd.exe` como **Administrador** (la política se guarda en `HKLM`).

## 1) (Recomendado) Forzar el certificado por CN

1. Ajusta el CN (sale del `Subject` del certificado, campo `CN=...`).
2. Ejecuta en `cmd` (Admin):

```bat
set "CN=TU_CN_AQUI"
rem Recomendado: limpiar y volver a crear la policy para evitar valores viejos
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f

reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://sede.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 2 /t REG_SZ /d "{\"pattern\":\"https://servcla.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 3 /t REG_SZ /d "{\"pattern\":\"https://servpub.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 4 /t REG_SZ /d "{\"pattern\":\"https://www.xalocgirona.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 5 /t REG_SZ /d "{\"pattern\":\"https://seu.xalocgirona.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 6 /t REG_SZ /d "{\"pattern\":\"https://www.base.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 7 /t REG_SZ /d "{\"pattern\":\"https://www.baseonline.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 8 /t REG_SZ /d "{\"pattern\":\"https://valid.aoc.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 9 /t REG_SZ /d "{\"pattern\":\"https://cert.valid.aoc.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 10 /t REG_SZ /d "{\"pattern\":\"https://cas.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 11 /t REG_SZ /d "{\"pattern\":\"https://pasarela.clave.gob.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 12 /t REG_SZ /d "{\"pattern\":\"https://[*.]madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 13 /t REG_SZ /d "{\"pattern\":\"https://[*.]clave.gob.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 14 /t REG_SZ /d "{\"pattern\":\"https://cas.madrid.es:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 15 /t REG_SZ /d "{\"pattern\":\"https://pasarela.clave.gob.es:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 16 /t REG_SZ /d "{\"pattern\":\"https://cert.valid.aoc.cat:443/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
```

## 2) Sin filtrar por certificado (Edge elige el disponible)

Útil si solo hay 1 certificado válido instalado.

```bat
rem Recomendado: limpiar y volver a crear la policy para evitar valores viejos
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f

reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://sede.madrid.es/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 2 /t REG_SZ /d "{\"pattern\":\"https://servcla.madrid.es/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 3 /t REG_SZ /d "{\"pattern\":\"https://servpub.madrid.es/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 4 /t REG_SZ /d "{\"pattern\":\"https://www.xalocgirona.cat/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 5 /t REG_SZ /d "{\"pattern\":\"https://seu.xalocgirona.cat/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 6 /t REG_SZ /d "{\"pattern\":\"https://www.base.cat/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 7 /t REG_SZ /d "{\"pattern\":\"https://www.baseonline.cat/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 8 /t REG_SZ /d "{\"pattern\":\"https://valid.aoc.cat/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 9 /t REG_SZ /d "{\"pattern\":\"https://cert.valid.aoc.cat/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 10 /t REG_SZ /d "{\"pattern\":\"https://cas.madrid.es/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 11 /t REG_SZ /d "{\"pattern\":\"https://pasarela.clave.gob.es/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 12 /t REG_SZ /d "{\"pattern\":\"https://[*.]madrid.es/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 13 /t REG_SZ /d "{\"pattern\":\"https://[*.]clave.gob.es/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 14 /t REG_SZ /d "{\"pattern\":\"https://cas.madrid.es:443/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 15 /t REG_SZ /d "{\"pattern\":\"https://pasarela.clave.gob.es:443/*\",\"filter\":{}}" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 16 /t REG_SZ /d "{\"pattern\":\"https://cert.valid.aoc.cat:443/*\",\"filter\":{}}" /f

```

## 3) Aplicar cambios

- Cierra Edge por completo (todos los procesos `msedge.exe`) y vuelve a abrir.

## 4) Verificar

```bat
reg query "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls"
```

## 5) Rollback (volver al modo interactivo)

```bat
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f
```
