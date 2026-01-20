# setup_worker_env.ps1
# Ejecutar como Administrador

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
  $policyValue = "{`"pattern`":`"$pattern`",`"filter`":{}}"
  New-ItemProperty -Path $registryPath -Name "$i" -Value $policyValue -PropertyType String -Force | Out-Null
  $i++
}

Write-Host "Configuración de Edge completada. El popup ya no aparecerá." -ForegroundColor Green
