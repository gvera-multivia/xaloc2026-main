# scripts/build-worker-launcher-exe.ps1
# Construye un .exe ligero (launcher) que arranca worker.py sin terminal.
#
# Este exe NO empaqueta Playwright: usa el Python del venv del repo.

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if (!(Test-Path ".\\venv\\Scripts\\python.exe")) {
  Write-Host "Creando venv..." -ForegroundColor Cyan
  python -m venv venv
}

Write-Host "Instalando PyInstaller..." -ForegroundColor Cyan
& .\\venv\\Scripts\\python.exe -m pip install -U pip
& .\\venv\\Scripts\\python.exe -m pip install -r requirements.txt
& .\\venv\\Scripts\\python.exe -m pip install pyinstaller

Write-Host "Construyendo xaloc-worker-launcher.exe..." -ForegroundColor Cyan
$logPath = ".\\build\\pyinstaller-launcher.log"
New-Item -ItemType Directory -Force .\\build | Out-Null

& .\\venv\\Scripts\\pyinstaller.exe --noconfirm --clean --onefile --noconsole --name "xaloc-worker-launcher" worker_launcher.py 2>&1 | Tee-Object -FilePath $logPath

$exe = Get-ChildItem -Path .\\dist -Recurse -Filter "xaloc-worker-launcher.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $exe) {
  Write-Host "No se ha encontrado xaloc-worker-launcher.exe. Revisa el log: $logPath" -ForegroundColor Red
  exit 1
}

Write-Host ("OK: " + $exe.FullName) -ForegroundColor Green
Write-Host "Doble click para arrancar el worker (usa el venv del repo)." -ForegroundColor Yellow
