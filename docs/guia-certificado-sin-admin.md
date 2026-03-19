# Inyectar certificado de certmgr.msc en Playwright sin admin

Guia para replicar en cualquier proyecto la auto-seleccion de certificados
digitales en Windows, sin necesitar administrador ni fichero PFX en disco.

---

## Contexto

En Windows, cuando el certificado esta instalado en `certmgr.msc` (almacen
`CurrentUser\My`) y **no** se dispone del `.pfx`, el navegador muestra un popup
de seleccion cada vez que una sede pide autenticacion TLS mutua.

Esta guia elimina ese popup usando un CLI arg de Chromium que le dice al
navegador que certificado usar automaticamente.

---

## Requisitos previos

- Windows 10/11
- Microsoft Edge instalado (viene con Windows)
- Certificado digital instalado en `certmgr.msc > Personal > Certificates`
- Python 3.10+ con Playwright instalado (`pip install playwright`)
- **NO se necesita**: fichero PFX, permisos de administrador, ni GPO

---

## Arquitectura minima

```
mi-proyecto/
  scripts/
    url-cert-config.ps1    # (opcional) politica HKCU si GPO no bloquea
    smoke_cert.py           # wrapper que configura env vars y lanza tu script
  mi_script_principal.py    # tu script de Playwright
```

---

## Paso 1: Obtener el CN del certificado

```powershell
Get-ChildItem Cert:\CurrentUser\My | Select-Object Subject, Thumbprint, NotAfter
```

Busca la linea con tu certificado. El CN es la parte `CN=...` del Subject.
Ejemplo: `CN=35059210B MARIA TERESA MORENTE (R: B62798210)`

---

## Paso 2: Configurar el browser launch en tu proyecto

Tu script de Playwright debe aceptar tres cosas via variables de entorno:

### 2.1 CLI arg `--auto-select-certificate-for-urls`

Construye un JSON con los patrones de URL donde se necesita el certificado
y pasalo como argumento al browser:

```python
import json
import os
from playwright.async_api import async_playwright

CN = os.getenv("CERTIFICADO_CN", "TU CN AQUI")
PATTERNS = [
    "https://sede.ejemplo.es/*",
    "https://login.ejemplo.es/*",
    "https://[*.]ejemplo.es/*",     # comodin: cualquier subdominio
]

cert_filter = {"SUBJECT": {"CN": CN}} if CN else {}
policy = json.dumps(
    [{"pattern": p, "filter": cert_filter} for p in PATTERNS],
    ensure_ascii=False,
    separators=(",", ":"),
)

args = [
    "--start-maximized",
    f"--auto-select-certificate-for-urls={policy}",
]

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="profiles/worker",
            channel="msedge",        # Edge lee certmgr.msc
            headless=False,           # headed para acceso al cert store
            args=args,
            ignore_https_errors=True,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://sede.ejemplo.es")
        # ... tu flujo
        await context.close()
```

### 2.2 Variables de entorno clave

| Variable | Valor | Efecto |
|---|---|---|
| `CERTIFICADO_CN` | `"TU CN EXACTO"` | CN del certificado en certmgr.msc |
| `XALOC_BROWSER_CHANNEL` | `"msedge"` | Usar Edge (lee Windows cert store) |
| `XALOC_EPHEMERAL_PROFILE` | `"1"` | Perfil temporal por ejecucion |

---

## Paso 3: Wrapper de ejecucion (smoke_cert.py)

Este wrapper configura las env vars necesarias y lanza tu script:

```python
"""
smoke_cert.py — Lanza tu script con auto-seleccion de certificado.
No requiere admin. Usa certificado de certmgr.msc via Edge + CLI arg.

Uso:
    python scripts/smoke_cert.py --cn "TU CN" -- python mi_script.py --arg1 val
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

DEFAULT_CN = "TU CN POR DEFECTO AQUI"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lanza script con auto-seleccion de certificado sin admin."
    )
    parser.add_argument(
        "--cn", default=DEFAULT_CN,
        help="CN exacto del certificado en certmgr.msc"
    )
    args, remaining = parser.parse_known_args()

    if not remaining:
        parser.error("Falta el comando a ejecutar. Uso: smoke_cert.py --cn '...' -- python mi_script.py")

    env = os.environ.copy()

    # 1. CN del certificado
    env["CERTIFICADO_CN"] = args.cn

    # 2. Forzar CLI arg (no depender de politicas de registro)
    env["XALOC_CERT_AUTOSELECT_VIA_POLICY"] = "0"

    # 3. Edge para acceder a certmgr.msc
    env["XALOC_BROWSER_CHANNEL"] = "msedge"

    # 4. Perfil efimero: evita crash por corrupcion del perfil
    env["XALOC_EPHEMERAL_PROFILE"] = "1"

    print(f"[smoke_cert] CN={args.cn!r}")
    print(f"[smoke_cert] Ejecutando: {' '.join(remaining)}")
    sys.exit(subprocess.run(remaining, env=env).returncode)


if __name__ == "__main__":
    main()
```

Uso:
```bash
python scripts/smoke_cert.py --cn "MI CN" -- python mi_script.py --argumento valor
```

---

## Paso 4 (opcional): Politica HKCU via registro

Si tu equipo **no** tiene GPO que bloquee `HKCU\SOFTWARE\Policies\`, puedes
escribir la politica directamente en el registro. Esto hace que Edge/Chrome la
lean automaticamente sin necesidad del CLI arg.

### url-cert-config.ps1

```powershell
# Ejecutar como usuario NORMAL (sin admin):
#   powershell -ExecutionPolicy Bypass -NoProfile -File scripts\url-cert-config.ps1
#   powershell -ExecutionPolicy Bypass -NoProfile -File scripts\url-cert-config.ps1 -CN "MI CN"

param(
    [string]$CN = "TU CN POR DEFECTO"
)

$patrones = @(
    "https://sede.ejemplo.es/*"
    "https://login.ejemplo.es/*"
    "https://[*.]ejemplo.es/*"
)

$rutas = @(
    "HKCU:\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls"
    "HKCU:\SOFTWARE\Policies\Google\Chrome\AutoSelectCertificateForUrls"
    "HKCU:\SOFTWARE\Policies\Chromium\AutoSelectCertificateForUrls"
)

foreach ($ruta in $rutas) {
    Remove-Item -Path $ruta -Force -ErrorAction SilentlyContinue
    New-Item    -Path $ruta -Force | Out-Null
    for ($i = 0; $i -lt $patrones.Count; $i++) {
        $valor = '{"pattern":"' + $patrones[$i] + '","filter":{"SUBJECT":{"CN":"' + $CN + '"}}}'
        New-ItemProperty -Path $ruta -Name ($i + 1).ToString() `
                         -PropertyType String -Value $valor -Force | Out-Null
    }
}

Write-Host "OK — Verifica en edge://policy o chrome://policy"
```

> **Si falla con "Se denego el acceso"**: tu equipo tiene GPO corporativa.
> Usa el metodo del CLI arg (paso 2-3) que no toca el registro.

Verificar: abre `edge://policy` o `chrome://policy` y busca
`AutoSelectCertificateForUrls`.

---

## Diagnostico

### El popup de certificado sigue apareciendo

1. **Verifica el CN** — debe coincidir EXACTAMENTE con `certmgr.msc`:
   ```powershell
   Get-ChildItem Cert:\CurrentUser\My | Select-Object Subject, Thumbprint
   ```

2. **Verifica los patrones** — la URL de la sede debe estar cubierta.
   Si el popup dice `cert.valid.aoc.cat:443`, necesitas:
   ```
   "https://cert.valid.aoc.cat/*"
   "https://cert.valid.aoc.cat:443/*"
   ```

3. **Verifica que Edge esta en headed mode** — `headless=False`.
   En headless, Edge no siempre accede a certmgr.msc.

4. **Verifica que el perfil no esta corrupto** — usa `XALOC_EPHEMERAL_PROFILE=1`
   o borra `profiles/worker` manualmente.

### El browser crashea al arrancar

- Perfil corrupto: activa `XALOC_EPHEMERAL_PROFILE=1`
- Si el crash-retry interno elimina el CLI arg, el popup aparece.
  El perfil efimero evita el crash y preserva el arg.

### GPO bloquea HKCU

- El CLI arg (`--auto-select-certificate-for-urls`) es la unica via.
- NO funciona con Chromium bundled (no lee certmgr.msc).
- DEBE usarse con Edge o Chrome instalado (`channel="msedge"` o `"chrome"`).

---

## Resumen de mecanismos

| Mecanismo | Necesita admin | Necesita PFX | Lee certmgr.msc | Notas |
|---|---|---|---|---|
| CLI arg + Edge | No | No | Si | **Recomendado** |
| HKCU policy + Edge | No* | No | Si | *Falla si GPO bloquea |
| HKLM policy | Si | No | Si | Requiere UAC |
| Playwright `client_certificates` | No | Si | No | Solo con PFX en disco |
| NSS database | No | Si | No | Solo Linux/Docker |

---

## Checklist rapido para tu proyecto

- [ ] Obtener CN exacto del certificado (`Get-ChildItem Cert:\CurrentUser\My`)
- [ ] Listar las URLs/sedes que piden certificado
- [ ] En tu Playwright launch: `channel="msedge"`, `headless=False`
- [ ] Construir el JSON de `--auto-select-certificate-for-urls` con patrones + CN
- [ ] Pasar el JSON como arg al browser
- [ ] Usar perfil efimero o limpiar perfil antes de cada ejecucion
- [ ] Probar: la sede debe cargar sin popup de certificado
