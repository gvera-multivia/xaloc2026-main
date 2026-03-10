# Certificate Injection Sites

## Objetivo

Mantener sincronizada la lista de webs donde el navegador debe autoseleccionar certificado cliente en login/firmado.

## Archivos que se deben actualizar juntos

1. `core/base_automation.py`
- `_DEFAULT_CERT_PATTERNS`
- `_DEFAULT_CLIENT_CERT_ORIGINS`

2. `infra/docker/playwright-runner-entrypoint.sh`
- `default_patterns` (policy `AutoSelectCertificateForUrls`)

3. `url-cert-config.bat`
- entradas `reg add ... AutoSelectCertificateForUrls`

## Regla operativa

Cuando un nuevo site o cambio de sede introduce host de login/certificado:

1. Agregar patron URL (`https://host/*`) en las listas de patrones.
2. Agregar origen (`https://host`) en lista de origenes para client certificates.
3. Si hay host con puerto fijo, agregar variante `:443` cuando aplique.
4. Mantener coherencia entre Linux Docker y Windows local.

## Validacion rapida

1. Revisar que los mismos hosts aparecen en los 3 archivos.
2. Iniciar runner y comprobar log:
- `AutoSelectCertificateForUrls aplicado con N reglas`
3. Ejecutar login del site y confirmar ausencia de popup manual de seleccion de certificado.
