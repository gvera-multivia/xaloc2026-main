# setup_worker_env.ps1
# Ejecutar como Administrador
#
# Configura Edge para autoseleccionar certificado SOLO en las URLs del proyecto,
# evitando el popup nativo de Windows que bloquea el modo Worker.

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
  $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
  Write-Host "Este script debe ejecutarse como Administrador." -ForegroundColor Red
  exit 1
}

$registryPath = "HKLM:\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls"
if (!(Test-Path $registryPath)) { New-Item -Path $registryPath -Force | Out-Null }

# Lista explícita de URLs donde Edge debe autoseleccionar certificado (sin popup)
$certUrlPatterns = @(
  # Madrid
  "https://sede.madrid.es/*",
  "https://servcla.madrid.es/*",
  "https://servpub.madrid.es/*",

  # Girona
  "https://www.xalocgirona.cat/*",
  "https://seu.xalocgirona.cat/*",

  # Tarragona (BASE On-line)
  "https://www.base.cat/*",
  "https://www.baseonline.cat/*"
)

# Limpia entradas previas (valores "1", "2", "3", ...)
try {
  $props = (Get-ItemProperty -Path $registryPath | Get-Member -MemberType NoteProperty).Name
  foreach ($p in $props) {
    if ($p -match '^\d+$') {
      Remove-ItemProperty -Path $registryPath -Name $p -ErrorAction SilentlyContinue
    }
  }
} catch { }

$i = 1
foreach ($pattern in $certUrlPatterns) {
  $policyValue = "{`"pattern`":`"$pattern`",`"filter`":{}}"
  New-ItemProperty -Path $registryPath -Name "$i" -Value $policyValue -PropertyType String -Force | Out-Null
  $i++
}

Write-Host "Configuración de Edge completada (AutoSelectCertificateForUrls)." -ForegroundColor Green
Write-Host "Cierra Edge y vuelve a abrirlo para aplicar cambios." -ForegroundColor Yellow

