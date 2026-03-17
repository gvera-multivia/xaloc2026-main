# Playwright + Certificado Del Sistema (Sin PFX En El Proyecto)

Guía exclusiva para usar certificado instalado en Windows (`certmgr.msc`) y evitar el popup con política de Edge/Chromium.

## 1. Objetivo

Usar Playwright **sin** `PLAYWRIGHT_CERT_PATH` ni `.pfx` en el repo.  
El navegador toma el certificado desde el almacén del sistema y lo auto-selecciona según dominio + filtro.

## 2. Requisitos

1. Windows.
2. Certificado ya instalado en el almacén del usuario o equipo.
3. Edge/Chromium gestionable por políticas.
4. Permisos de administrador para escribir en `HKLM` (recomendado).

## 3. Instalar/validar certificado en `certmgr.msc`

1. `Win + R` -> `certmgr.msc`.
2. Verifica que el certificado está en `Personal -> Certificates`.
3. Copia el `Subject`/`CN` exacto (espacios, paréntesis y mayúsculas tal cual).
4. Verifica que tiene clave privada y que no está caducado.

Comando opcional para listar CN desde PowerShell:

```powershell
Get-ChildItem Cert:\CurrentUser\My | Select-Object Subject, Thumbprint, NotAfter
```

## 4. Política que elimina el popup

La clave es:

`HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls`

Cada valor debe contener JSON string con este formato:

```json
{"pattern":"https://dominio/*","filter":{"SUBJECT":{"CN":"CN_EXACTO"}}}
```

## 5. Script `.bat` mínimo (sin PFX)

```bat
@echo off
chcp 65001 >nul

set "CN=TU_CN_EXACTO"

reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f >nul

reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://sede1.ejemplo/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 2 /t REG_SZ /d "{\"pattern\":\"https://sede2.ejemplo/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul

echo EXITOSOS
```

Notas:

1. Si hay varios certificados válidos, **usa filtro CN** para evitar selección errónea.
2. Si quieres que use cualquiera, `filter:{}` (no recomendado en entornos con varios certs).
3. Cierra y reabre Edge después de aplicar la policy.

## 6. Qué hace Playwright en este enfoque

Playwright no inyecta `pfxPath`. Solo abre navegador/contexto persistente.  
La selección automática la resuelve el navegador por policy + almacén del sistema.

Ejemplo Python:

```python
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="profiles/worker",
            headless=False,
            channel="msedge",
            ignore_https_errors=True,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://sede1.ejemplo")
        # flujo...
        await context.close()
```

## 7. Verificación rápida

1. Ejecuta el `.bat` como administrador.
2. Abre `edge://policy` y confirma `AutoSelectCertificateForUrls`.
3. Navega al dominio configurado y comprueba que no aparece popup.
4. Si aparece popup, revisa:
   - CN exacto incorrecto.
   - dominio/patrón no coincide.
   - certificado no está en el almacén esperado.
   - navegador abierto antes de aplicar policy.

## 8. Diagnóstico por síntomas

1. Sigue saliendo selector:
   policy no aplicada o patrón incorrecto.
2. Selecciona certificado incorrecto:
   filtro demasiado amplio; ajustar `CN`.
3. En una sede funciona y en otra no:
   falta regla para ese dominio exacto.
4. En modo manual funciona pero con Playwright no:
   Playwright abre otro canal/perfil; mantener `channel="msedge"` y perfil persistente.

## 9. Buenas prácticas

1. Mantener un `.bat` versionado con todos los dominios permitidos.
2. Evitar guardar `.pfx` en repositorio y en imágenes si ya se usa almacén del sistema.
3. Documentar el CN oficial por entorno (producción, pruebas).
4. Probar cada dominio nuevo añadiendo su regla explícita.

