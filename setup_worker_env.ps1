# setup_worker_env.ps1
# Ejecutar como Administrador

param(
  # CN del Subject del certificado a autoseleccionar (opcional).

  [string]$CertSubjectCN = ""
)

# Permite configurar el CN sin tocar el script (por variable de entorno).
# Se aceptan ambas por compatibilidad: CERTIFICADO_CN (recomendado) y certificado_cn (ya usada en Python).
if ([string]::IsNullOrWhiteSpace($CertSubjectCN)) {
  if (-not [string]::IsNullOrWhiteSpace($env:CERTIFICADO_CN)) {
    $CertSubjectCN = $env:CERTIFICADO_CN
  } elseif (-not [string]::IsNullOrWhiteSpace($env:certificado_cn)) {
    $CertSubjectCN = $env:certificado_cn
  }
}

$registryPath = "HKLM:\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls"
if (!(Test-Path $registryPath)) { New-Item -Path $registryPath -Force }

# Lista explícita de URLs donde Edge debe autoseleccionar certificado (sin popup)
# Nota: cada entrada crea un valor "1", "2", "3"... en el registro.
#
# Madrid
# - sites/madrid/config.py: https://sede.madrid.es/...
# - sites/madrid/flows/navegacion.py: https://servcla.madrid.es/... y enlaces a https://servpub.madrid.es/...
#
# Girona
# - sites/xaloc_girona/config.py: https://www.xalocgirona.cat/... y post-login en https://seu.xalocgirona.cat/...
#
# Tarragona (BASE On-line)
# - sites/base_online/config.py: https://www.base.cat/...
# - sites/base_online/flows/navegacion.py: https://www.baseonline.cat/...
$certUrlPatterns = @(
  "https://sede.madrid.es/*",
  "https://servcla.madrid.es/*",
  "https://servpub.madrid.es/*",
  "https://www.xalocgirona.cat/*",
  "https://seu.xalocgirona.cat/*",
  "https://www.base.cat/*",
  "https://www.baseonline.cat/*"
)

$i = 1
foreach ($pattern in $certUrlPatterns) {
  # Si se proporciona un CN, filtramos para evitar que Edge elija el certificado equivocado.
  # En caso contrario, Edge autoselecciona el certificado disponible para esa URL.
  if ([string]::IsNullOrWhiteSpace($CertSubjectCN)) {
    $policyValue = "{`"pattern`":`"$pattern`",`"filter`":{}}"
  } else {
    $policyValue = "{`"pattern`":`"$pattern`",`"filter`":{`"SUBJECT`":{`"CN`":`"$CertSubjectCN`"}}}"
  }
  New-ItemProperty -Path $registryPath -Name "$i" -Value $policyValue -PropertyType String -Force | Out-Null
  $i++
}

Write-Host "Configuración de Edge completada. El popup ya no aparecerá." -ForegroundColor Green
