# url-cert-config.ps1
# Versión HKCU del url-cert-config.bat — no requiere administrador.
# Escribe la política AutoSelectCertificateForUrls para Edge Y Chromium (Playwright).
#
# Uso:
#   powershell -ExecutionPolicy Bypass -NoProfile -File scripts\url-cert-config.ps1
#   powershell -ExecutionPolicy Bypass -NoProfile -File scripts\url-cert-config.ps1 -CN "MI CN EXACTO"
#
# Verificar resultado:  edge://policy  o  chrome://policy  (buscar AutoSelectCertificateForUrls)

param(
    [string]$CN = "00819709N JORGE PADILLA (R: B56684046)"
)

$patrones = @(
    "https://sede.madrid.es/*"
    "https://servcla.madrid.es/*"
    "https://servpub.madrid.es/*"
    "https://www.xalocgirona.cat/*"
    "https://seu.xalocgirona.cat/*"
    "https://www.base.cat/*"
    "https://www.baseonline.cat/*"
    "https://valid.aoc.cat/*"
    "https://cert.valid.aoc.cat/*"
    "https://cas.madrid.es/*"
    "https://pasarela.clave.gob.es/*"
    "https://[*.]madrid.es/*"
    "https://[*.]clave.gob.es/*"
    "https://cas.madrid.es:443/*"
    "https://pasarela.clave.gob.es:443/*"
    "https://cert.valid.aoc.cat:443/*"
    "https://palma.sedipualba.es/*"
    "https://identificacionssl.sedipualba.es/*"
    "https://aoberta.terrassa.cat/*"
    "https://sede.valencia.es/*"
    "https://autenticaciogicar5.extranet.gencat.cat/*"
    "https://atc.gencat.cat/*"
    "https://seu.atc.gencat.cat/*"
    "https://seu2.atc.gencat.cat/*"
)

# Rutas de política para cada navegador (todas HKCU, sin admin)
$rutas = @(
    "HKCU:\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls"   # Edge
    "HKCU:\SOFTWARE\Policies\Google\Chrome\AutoSelectCertificateForUrls"    # Chrome
    "HKCU:\SOFTWARE\Policies\Chromium\AutoSelectCertificateForUrls"         # Playwright Chromium
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

Write-Host "EXITOSOS"
Write-Host "Verifica en edge://policy o chrome://policy -> AutoSelectCertificateForUrls ($($patrones.Count) reglas)"
