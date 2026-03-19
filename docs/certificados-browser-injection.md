# Inyección de Certificados y Políticas en el Navegador

Investigación basada en el proyecto xaloc2026. Explica por qué este proyecto no necesita
credenciales de administrador para usar certificados digitales en el navegador automatizado,
y cómo replicarlo en otros proyectos (con PFX en disco o con certificado en `certmgr.msc`).

---

## 1. Los cuatro mecanismos del proyecto

### 1.1 NSS Database a nivel de usuario — nunca requiere admin

Chromium y Firefox mantienen su propio almacén de certificados en ficheros SQLite (`cert9.db`,
`key4.db`) dentro del directorio de perfil del usuario. Las herramientas `certutil` y `pk12util`
(del paquete `libnss3-tools` en Linux) operan directamente sobre esos ficheros.

```bash
# Crear base NSS vacía (sin contraseña)
certutil -N --empty-password -d "sql:$HOME/.pki/nssdb"

# Importar certificado PKCS#12 / PFX
pk12util -i /ruta/certificado.pfx \
         -d "sql:$HOME/.pki/nssdb" \
         -w /tmp/pfx_password.txt \   # fichero con la contraseña del PFX
         -k /tmp/db_password.txt       # fichero con salto de línea (DB sin contraseña)
```

Chromium arranca leyendo `~/.pki/nssdb` automáticamente. No hay interacción con el sistema
operativo más allá de ficheros del usuario.

**Implementación en este proyecto:** `infra/docker/playwright-runner-entrypoint.sh:237-276`

---

### 1.2 Playwright `client_certificates` API — nunca requiere admin

Playwright ≥ 1.46 gestiona el TLS mutuo completamente dentro de la librería, sin pasar por
ningún almacén del sistema operativo. El certificado se lee directamente del fichero PFX.

```python
context = await browser.launch_persistent_context(
    user_data_dir="profiles/worker",
    client_certificates=[
        {
            "origin": "https://sede.ejemplo.es",
            "pfxPath": "/ruta/certificado.pfx",
            "passphrase": "contraseña_del_pfx",
        }
    ],
)
```

Se puede pasar tantos `origin` como sedes distintas requieran autenticación mutua. Chrome
selecciona automáticamente el certificado correcto en el handshake TLS para cada origen.

**Implementación en este proyecto:** `core/base_automation.py:242-290`
**Variable de control:** `PLAYWRIGHT_USE_CLIENT_CERTIFICATES=1` (activo por defecto)

---

### 1.3 Argumento CLI `--auto-select-certificate-for-urls` — nunca requiere admin

Equivalente a la política `AutoSelectCertificateForUrls` pero pasado directamente al proceso
de Chromium como argumento de línea de comandos. No toca el registro ni ficheros del sistema.

```python
policy = json.dumps([
    {"pattern": "https://sede.ejemplo.es/*", "filter": {}},
    {"pattern": "https://cas.ejemplo.es/*",  "filter": {"SUBJECT": {"CN": "MI CN EXACTO"}}},
])
args.append(f"--auto-select-certificate-for-urls={policy}")
```

El filtro vacío `{}` acepta cualquier certificado disponible. El filtro `{"SUBJECT": {"CN": "..."}}` restringe a un CN concreto (útil si hay varios certificados instalados).

**Implementación en este proyecto:** `core/base_automation.py:151,174`
**Variable de control:** `XALOC_CERT_AUTOSELECT_CLI_FALLBACK=1`

---

### 1.4 Políticas Chrome/Edge en `/etc/` — requiere root, pero Docker lo oculta

Chromium lee políticas JSON de `/etc/chromium/policies/managed/` y rutas equivalentes
(`/etc/opt/chrome/policies/managed/`, etc.). En Linux bare-metal esto requiere `sudo`.

Dentro de un contenedor Docker el proceso corre como `root` en su propio namespace, por lo
que puede escribir en `/etc/` sin que el usuario del host introduzca ninguna contraseña.

```bash
# entrypoint del contenedor — se ejecuta como root dentro del contenedor
mkdir -p /etc/chromium/policies/managed
cat > /etc/chromium/policies/managed/xaloc-cert-policy.json <<'JSON'
{
  "AutoSelectCertificateForUrls": [
    "{\"pattern\":\"https://sede.ejemplo.es/*\",\"filter\":{}}"
  ]
}
JSON
```

**Implementación en este proyecto:** `infra/docker/playwright-runner-entrypoint.sh:26-133`

---

## 2. Por qué otros proyectos piden credenciales de admin

En entornos no-Docker (Windows o Linux de escritorio), los proyectos piden admin cuando
intentan escribir en rutas de sistema:

| Operación | Requiere admin |
|---|---|
| `/etc/opt/chrome/policies/managed/` (Linux) | Sí (root/sudo) |
| `HKLM\SOFTWARE\Policies\Google\Chrome` (Windows) | Sí (UAC) |
| `HKLM\SOFTWARE\Policies\Microsoft\Edge` (Windows) | Sí (UAC) |
| Importar al Windows Certificate Store — Machine store | Sí (UAC) |

---

## 3. Soluciones sin admin en Windows (con PFX en disco)

### 3.1 HKCU en lugar de HKLM — y por qué el .bat puede pedir admin aunque no debería

Chrome y Edge leen `AutoSelectCertificateForUrls` tanto de `HKLM` como de `HKCU`. Escribir
en `HKCU` **no requiere UAC por diseño**. Sin embargo, hay dos causas frecuentes por las que
un `.bat` con `reg add HKCU\...` puede acabar pidiendo elevación:

**Causa 1 — Heurísticas de UAC por nombre de fichero.**
Windows auto-eleva `.bat` / `.exe` cuyos nombres contengan palabras como `setup`, `install`,
`update`, `fix`, `patch`, `admin`, `config`. Es una heurística de compatibilidad heredada.
**Solución: renombrar el fichero** a algo neutro (`aplicar-politica-cert.bat`).

**Causa 2 — El `.bat` se lanza desde un proceso ya elevado.**
Si el script es llamado desde un instalador u otro proceso admin, hereda la elevación.

> **Problema crítico al ejecutar como admin:** cuando el proceso corre bajo la cuenta
> Administrador (no solo elevado), `HKCU` apunta al hive del Administrador, no al del
> usuario real. La política se escribe en el lugar equivocado y los certificados visibles
> son los del perfil admin, no los del usuario con el certificado de firma.

#### Solución recomendada: usar PowerShell con `HKCU:` (nunca pide elevación con nombre neutro)

```powershell
# Guardar como: aplicar-politica-cert.ps1  ← nombre neutro, sin palabras reservadas
# Ejecutar como el USUARIO NORMAL (sin "Run as admin"):
#   powershell -ExecutionPolicy Bypass -NoProfile -File aplicar-politica-cert.ps1

param(
    [string]$CN = "TU CN EXACTO"
)

$reglas = @(
    '{"pattern":"https://sede1.ejemplo/*","filter":{"SUBJECT":{"CN":"' + $CN + '"}}}'
    '{"pattern":"https://sede2.ejemplo/*","filter":{"SUBJECT":{"CN":"' + $CN + '"}}}'
)

$rutas = @(
    "HKCU:\SOFTWARE\Policies\Google\Chrome\AutoSelectCertificateForUrls"
    "HKCU:\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls"
)

foreach ($ruta in $rutas) {
    Remove-Item -Path $ruta -Force -ErrorAction SilentlyContinue
    New-Item  -Path $ruta -Force | Out-Null
    for ($i = 0; $i -lt $reglas.Count; $i++) {
        New-ItemProperty -Path $ruta -Name ($i + 1).ToString() `
                         -PropertyType String -Value $reglas[$i] -Force | Out-Null
    }
}

Write-Host "Hecho. Verifica en chrome://policy o edge://policy"
```

PowerShell con `HKCU:` nunca necesita elevación y siempre opera sobre el hive del usuario
que ejecuta el proceso, sea cual sea su nombre de fichero.

#### Caso excepcional: el script DEBE correr elevado pero escribir en el HKCU del usuario real

Si por alguna razón el contexto es inevitablemente admin, obtener el SID del usuario de sesión
y escribir directamente en `HKU\{SID}\...`:

```powershell
# Obtener SID del usuario de sesión activa (no del proceso elevado)
$sessionUser = (Get-CimInstance Win32_ComputerSystem).UserName
$sid = (New-Object System.Security.Principal.NTAccount($sessionUser)).Translate(
    [System.Security.Principal.SecurityIdentifier]).Value

if (-not (Get-PSDrive HKU -ErrorAction SilentlyContinue)) {
    New-PSDrive -Name HKU -PSProvider Registry -Root HKEY_USERS | Out-Null
}

$ruta = "HKU:\$sid\SOFTWARE\Policies\Google\Chrome\AutoSelectCertificateForUrls"
Remove-Item -Path $ruta -Force -ErrorAction SilentlyContinue
New-Item  -Path $ruta -Force | Out-Null
New-ItemProperty -Path $ruta -Name "1" -PropertyType String -Force `
    -Value '{"pattern":"https://sede1.ejemplo/*","filter":{}}' | Out-Null
```

**Limitación:** en equipos gestionados por GPO corporativo, el departamento IT puede bloquear
las políticas de usuario (HKCU). En ese caso es inevitable pedir admin al equipo de IT.

### 3.2 CLI arg (sin registro, sin admin)

```python
args.append('--auto-select-certificate-for-urls=[{"pattern":"https://sede.ejemplo.es/*","filter":{}}]')
```

### 3.3 Playwright `client_certificates` con PFX (sin registro, sin admin)

```python
context = await browser.launch_persistent_context(
    user_data_dir="profiles/worker",
    client_certificates=[{"origin": "https://sede.ejemplo.es", "pfxPath": "cert.pfx", "passphrase": "xxx"}],
)
```

---

## 4. Caso especial: certificado en `certmgr.msc`, sin PFX en disco

En algunos proyectos el certificado ya está instalado en el almacén de Windows
(`certmgr.msc → Personal → Certificates`) y no se dispone del fichero `.pfx`. En ese caso
**no se puede usar** la API `client_certificates` de Playwright ni NSS porque ambas requieren
el fichero PFX. Las únicas opciones son:

### 4.1 Política de auto-selección (HKCU, sin admin)

El navegador toma el certificado directamente del almacén del sistema. La política elimina
el popup de selección. No se necesita el PFX para nada.

```bat
@echo off
chcp 65001 >nul

:: Obtener el CN del certificado desde PowerShell:
:: Get-ChildItem Cert:\CurrentUser\My | Select-Object Subject, Thumbprint, NotAfter

set "CN=TU CN EXACTO"

:: Chrome — HKCU (sin admin)
reg delete "HKCU\SOFTWARE\Policies\Google\Chrome\AutoSelectCertificateForUrls" /f >nul 2>&1
reg add    "HKCU\SOFTWARE\Policies\Google\Chrome\AutoSelectCertificateForUrls" /f >nul
reg add    "HKCU\SOFTWARE\Policies\Google\Chrome\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://sede1.ejemplo/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul

:: Edge — HKCU (sin admin)
reg delete "HKCU\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f >nul 2>&1
reg add    "HKCU\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /f >nul
reg add    "HKCU\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://sede1.ejemplo/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f >nul

echo Hecho. Reinicia el navegador y verifica en chrome://policy o edge://policy
```

Playwright en Python — **sin** `client_certificates`, solo política + perfil persistente:

```python
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="profiles/worker",
            headless=False,               # headed para que el almacén de sistema sea accesible
            channel="msedge",             # o "chrome" — debe coincidir con la política escrita
            ignore_https_errors=True,
            args=["--start-maximized"],
            # SIN client_certificates — el navegador usa certmgr.msc directamente
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://sede1.ejemplo")
        await context.close()
```

> **Importante:** en este enfoque el navegador accede al almacén del sistema (`certmgr.msc`),
> que es la store `CurrentUser\My`. Chromium/Edge en Windows tienen acceso nativo a esa store
> sin ningún permiso especial. El popup de selección desaparece gracias a la política HKCU.

### 4.2 Exportar el certificado a PFX una sola vez (con la clave privada marcada como exportable)

Si la clave privada del certificado está marcada como exportable en `certmgr.msc`, se puede
exportar a PFX una única vez y a partir de ahí usar todos los mecanismos del punto 3.

```powershell
# Exportar a PFX desde PowerShell (sin admin si la clave es exportable para el usuario)
$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -like "*CN EXACTO*" }
$pwd  = ConvertTo-SecureString "contraseña_nueva" -AsPlainText -Force
Export-PfxCertificate -Cert $cert -FilePath "C:\ruta\certificado.pfx" -Password $pwd
```

Si la exportación falla (`The PFX export operation was not successful`) la clave privada NO
es exportable y esta vía está bloqueada. En ese caso la única opción es la política (4.1).

### 4.3 CLI arg con almacén del sistema (headless limitado)

En headless puro, Chromium en Windows puede NO leer `certmgr.msc` correctamente porque el
almacén del sistema requiere el contexto de sesión de Windows. En **headed** o en modo
`headless: false` funciona. Con `headless: true` (modo headless nuevo de Chromium) también
puede funcionar, pero es menos fiable con certificados del sistema.

```python
args = [
    "--auto-select-certificate-for-urls=[{\"pattern\":\"https://sede.ejemplo.es/*\",\"filter\":{}}]",
]
# Usar channel="chrome" o channel="msedge" para acceder al almacén del sistema Windows
context = await p.chromium.launch_persistent_context(
    user_data_dir="profiles/worker",
    headless=False,
    channel="msedge",
    args=args,
)
```

---

## 5. Resumen por entorno y caso

| Entorno | Tiene PFX | Mecanismo | Admin |
|---|---|---|---|
| Docker Linux | Sí | NSS DB + políticas `/etc/` + Playwright API | No (container es root) |
| Linux bare-metal | Sí | NSS user DB (`~/.pki/nssdb`) + CLI arg | No |
| Linux bare-metal | Sí | Playwright `client_certificates` API | No |
| Windows | Sí | Playwright `client_certificates` API | No |
| Windows | Sí | CLI `--auto-select-certificate-for-urls` | No |
| Windows | Sí | Política `HKCU` registry | No |
| Windows | Sí | Política `HKLM` registry | Sí (UAC) |
| Windows | No (certmgr) | Política `HKCU` + perfil persistente + `channel=` | No |
| Windows | No (certmgr) | Exportar PFX → cualquier mecanismo de arriba | No (si exportable) |
| Windows GPO corp | Cualquiera | Alternativas sin admin bloqueadas por IT | No viable sin IT |

---

## 6. Diagnóstico rápido

**Sigue apareciendo el selector de certificado:**
- La política no está cargada: verifica en `chrome://policy` o `edge://policy`.
- El patrón de URL no coincide: añade la URL exacta del dominio que falla.
- El navegador estaba abierto cuando se aplicó la política: ciérralo y reabre.

**Selecciona el certificado incorrecto:**
- Usa el filtro `{"SUBJECT": {"CN": "CN EXACTO"}}` en la política o en el argumento CLI.
- Obtén el CN exacto con:
  ```powershell
  Get-ChildItem Cert:\CurrentUser\My | Select-Object Subject, Thumbprint, NotAfter
  ```

**Con Playwright `client_certificates` funciona en una sede y en otra no:**
- El `origin` debe coincidir exactamente con el host del handshake TLS (sin path, sin barra final).
- Si la sede redirige a un subdominio distinto en el handshake, añade ese subdominio como origin adicional.

**En headless no funciona con certmgr.msc:**
- Usa `headless: false` o `channel="msedge"` / `channel="chrome"` con perfil persistente.
- Considera exportar el certificado a PFX si la clave es exportable.
