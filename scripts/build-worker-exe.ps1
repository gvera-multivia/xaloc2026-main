# scripts/build-worker-exe.ps1
# Construye un .exe (PyInstaller) para lanzar worker.py sin terminal.

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if (!(Test-Path ".\\venv\\Scripts\\python.exe")) {
  Write-Host "Creando venv..." -ForegroundColor Cyan
  python -m venv venv
}

Write-Host "Instalando dependencias..." -ForegroundColor Cyan
& .\\venv\\Scripts\\python.exe -m pip install -U pip
& .\\venv\\Scripts\\python.exe -m pip install -r requirements.txt
& .\\venv\\Scripts\\python.exe -m pip install pyinstaller

Write-Host "Construyendo xaloc-worker.exe..." -ForegroundColor Cyan
$logPath = ".\\build\\pyinstaller-worker.log"
New-Item -ItemType Directory -Force .\\build | Out-Null

& .\\venv\\Scripts\\pyinstaller.exe --noconfirm --clean packaging\\worker.spec 2>&1 | Tee-Object -FilePath $logPath

$exe = Get-ChildItem -Path .\\dist -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $exe) {
  Write-Host "No se ha encontrado ningun .exe en dist/. Revisa el log: $logPath" -ForegroundColor Red
  exit 1
}

Write-Host ("OK: " + $exe.FullName) -ForegroundColor Green
Write-Host "Tip: puedes crear un acceso directo al .exe y ponerlo en el escritorio." -ForegroundColor Yellow

