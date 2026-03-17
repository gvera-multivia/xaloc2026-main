# Inyección De Certificado Digital En Playwright (Desde Cero)

Esta guía explica cómo montar **desde un proyecto nuevo** la autenticación por certificado digital con Playwright y evitar el popup nativo de selección cuando sea posible.

## 1. Qué problema hay realmente

Hay dos capas distintas:

1. **TLS client certificate** en Playwright (`clientCertificates` / `client_certificates`).
2. **Autoselección del certificado** por política del navegador (Edge/Chromium) para evitar el diálogo nativo.

Solo con Playwright puede seguir apareciendo popup en algunos portales.  
Para que se acepte “solo”, normalmente necesitas también política de navegador.

## 2. Requisitos mínimos

1. Tener un certificado `.pfx` / `.p12` válido.
2. Conocer su contraseña.
3. Tener claro el/los dominios de login (`https://...`) donde el servidor pide client cert.
4. En Windows: ejecutar el navegador con política `AutoSelectCertificateForUrls`.
5. En Linux/Docker: además importar el PFX en NSS (`pk12util`) si el proveedor lo exige.

## 3. Variables de entorno recomendadas

```bash
PLAYWRIGHT_CERT_PATH=/ruta/al/certificado.pfx
PLAYWRIGHT_CERT_PASSWORD=tu_password
PLAYWRIGHT_CLIENT_CERT_ORIGINS=https://sede1.es,https://sede2.es
CERTIFICADO_CN=CN_EXACTO_DEL_CERT
```

Opcionales para autoselección:

```bash
XALOC_CERT_AUTOSELECT_VIA_POLICY=1
XALOC_CERT_AUTOSELECT_PATTERN=https://sede1.es/*
```

## 4. Implementación mínima en proyecto nuevo (Python)

```python
import os
from playwright.async_api import async_playwright

CERT_PATH = os.getenv("PLAYWRIGHT_CERT_PATH", "certificates/certificate.pfx")
CERT_PASS = os.getenv("PLAYWRIGHT_CERT_PASSWORD", "")
ORIGINS = [o.strip() for o in os.getenv("PLAYWRIGHT_CLIENT_CERT_ORIGINS", "").split(",") if o.strip()]

def build_client_certificates():
    certs = []
    for origin in ORIGINS:
        item = {"origin": origin, "pfxPath": CERT_PATH}
        if CERT_PASS:
            item["passphrase"] = CERT_PASS
        certs.append(item)
    return certs

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="profiles/worker",
            headless=False,
            channel="msedge",  # o quítalo para Chromium
            ignore_https_errors=True,
            client_certificates=build_client_certificates(),
            args=[
                "--start-maximized",
            ],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://tu-sede.ejemplo")
        # ... flujo
        await context.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## 5. Implementación mínima en proyecto nuevo (TypeScript/Node.js)

```ts
import { chromium } from "playwright";

const certPath = process.env.PLAYWRIGHT_CERT_PATH ?? "certificates/certificate.pfx";
const certPass = process.env.PLAYWRIGHT_CERT_PASSWORD ?? "";
const origins = (process.env.PLAYWRIGHT_CLIENT_CERT_ORIGINS ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const clientCertificates = origins.map((origin) => ({
  origin,
  pfxPath: certPath,
  ...(certPass ? { passphrase: certPass } : {}),
}));

async function main() {
  const context = await chromium.launchPersistentContext("profiles/worker", {
    headless: false,
    channel: "msedge",
    ignoreHTTPSErrors: true,
    clientCertificates,
    args: ["--start-maximized"],
  });

  const page = context.pages()[0] ?? (await context.newPage());
  await page.goto("https://tu-sede.ejemplo");
  // ... flujo
  await context.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

## 6. Autoselección en Windows (evitar popup nativo)

Crear política de Edge:

```bat
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://tu-sede.ejemplo/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"TU_CN_EXACTO\"}}}" /f
```

Notas:

1. Requiere permisos de administrador (HKLM).
2. Si no quieres filtrar por CN, puedes poner `"filter":{}`.
3. Reinicia Edge/Chromium tras aplicar la policy.

## 7. Linux/Docker: importación NSS (muy importante)

```bash
certutil -N --empty-password -d sql:/app/profiles/worker
printf "%s" "$PLAYWRIGHT_CERT_PASSWORD" > /tmp/p12_pass.txt
printf "\n" > /tmp/db_pass.txt
pk12util -i "$PLAYWRIGHT_CERT_PATH" -d sql:/app/profiles/worker -w /tmp/p12_pass.txt -k /tmp/db_pass.txt
certutil -L -d sql:/app/profiles/worker
```

Si no importas en NSS, en algunos entornos la negociación TLS del client cert falla o sigue pidiendo interacción.

## 8. Checklist rápido de validación

1. El archivo PFX existe y la password es correcta.
2. El `origin` de `clientCertificates` coincide exactamente con el host real del handshake.
3. El `CN` de la policy coincide exacto (espacios, paréntesis, todo).
4. La policy está aplicada en el navegador que usas (`edge://policy` o equivalente).
5. El perfil persistente (`launchPersistentContext`) es estable y siempre el mismo.
6. Si estás en Docker/Linux, NSS contiene el certificado (`certutil -L`).

## 9. Errores típicos y causa probable

1. `failed to load client certificate`:
   formato/cifrado del PFX no compatible en runtime actual; usar fallback NSS/import.
2. Sigue saliendo popup:
   policy no aplicada, patrón URL incorrecto o CN no coincide.
3. Funciona en local y falla en contenedor:
   falta import NSS o perfil distinto al esperado.
4. Timeout tras clicar “Acceder con certificado”:
   handshake bloqueado por selección manual pendiente o cert no válido para esa sede.

## 10. Recomendación de arquitectura para proyecto nuevo

1. Centraliza todo en una función `build_client_certificates()`.
2. Usa `launchPersistentContext` (no contexto efímero) para estabilidad.
3. Parametriza por env vars (`CERT_PATH`, `CERT_PASSWORD`, `ORIGINS`, `CN`).
4. Añade un script de bootstrap:
   en Windows, aplica `AutoSelectCertificateForUrls`;
   en Linux/Docker, importa PFX en NSS antes de lanzar workers.
5. Loguea en arranque:
   path cert, origins activos, policy activa, y resultado de `certutil -L`.

---

Si quieres, el siguiente paso puede ser que te deje un `bootstrap-cert.ps1` (Windows) y un `bootstrap-cert.sh` (Linux/Docker) listos para usar en cualquier repo nuevo.
