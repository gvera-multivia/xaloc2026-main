"""
Subida de documentos en el flujo de Ayunta Palma.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from core.client_documentation import client_identity_from_payload, get_ruta_cliente_documentacion
from core.client_paths import resolve_client_docs_base_path
from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.flows.autofirma_monitor import monitor_autofirma_windows
from sites.ayunta_palma.flows.firma_programatica import firmar_programaticamente

logger = logging.getLogger(__name__)


async def _run_ps_diagnostic(step_name: str, ps_script: str, timeout_s: int = 45) -> None:
    """
    Ejecuta un script de PowerShell y vuelca stdout/stderr a logs para diagnostico.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        saw_stdout = False
        saw_stderr = False

        async def _pump_stream(stream, is_err: bool) -> bool:
            saw_any = False
            while True:
                line_b = await stream.readline()
                if not line_b:
                    break
                line = line_b.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                saw_any = True
                if is_err:
                    logger.warning("[AP-DIAG][%s][ERR] %s", step_name, line)
                else:
                    logger.info("[AP-DIAG][%s][OUT] %s", step_name, line)
            return saw_any

        stdout_task = asyncio.create_task(_pump_stream(proc.stdout, is_err=False))
        stderr_task = asyncio.create_task(_pump_stream(proc.stderr, is_err=True))
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            timed_out = True
            logger.warning("[AP-DIAG][%s] Timeout tras %ss", step_name, timeout_s)
        finally:
            saw_stdout = await stdout_task
            saw_stderr = await stderr_task

        if not saw_stdout:
            logger.info("[AP-DIAG][%s] Sin salida stdout.", step_name)
        if (not timed_out) and (not saw_stderr) and proc.returncode not in (0, None):
            logger.warning("[AP-DIAG][%s] PowerShell returncode=%s sin stderr.", step_name, proc.returncode)
    except Exception as e:
        logger.warning("[AP-DIAG][%s] Error ejecutando PowerShell: %s", step_name, e)


async def _dump_autofirma_windows_runtime_diag() -> None:
    """
    Vuelca estado de procesos/ventanas para diagnosticar bloqueos de AutoFirma en Windows.
    """
    if not sys.platform.startswith("win"):
        return

    ps_script = r"""
$ErrorActionPreference = "SilentlyContinue"
Write-Output "diag=autofirma_runtime begin=1"
$targets = Get-Process | Where-Object {
  $_.ProcessName -match 'AutoFirma|java|javaw'
}
if (-not $targets) {
  Write-Output "diag=autofirma_runtime procs=none"
} else {
  foreach ($p in $targets) {
    $title = [string]$p.MainWindowTitle
    if ($null -eq $title) { $title = "" }
    Write-Output ("proc name=" + $p.ProcessName + " pid=" + $p.Id + " title=" + ($title -replace "`r|`n", " ").Trim())
  }
}
try {
  $wins = Get-Process | Where-Object { $_.MainWindowTitle -match 'AutoFirma|Portafirm|Firma|Certificat|Certificado' }
  foreach ($w in $wins) {
    Write-Output ("window pid=" + $w.Id + " name=" + $w.ProcessName + " title=" + ([string]$w.MainWindowTitle -replace "`r|`n", " ").Trim())
  }
} catch {}
Write-Output "diag=autofirma_runtime end=1"
"""
    await _run_ps_diagnostic("autofirma_runtime", ps_script, timeout_s=20)


async def _dump_browser_signature_diag(page: Page, label: str) -> None:
    """
    Snapshot corto del estado del navegador cuando la firma parece bloqueada.
    """
    try:
        diag = await page.evaluate(
            """() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const cs = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const overlays = {
                    progress: isVisible(document.querySelector('#divProgressBar')),
                    modalwait: isVisible(document.querySelector('.modalwait')),
                    widget_overlay: isVisible(document.querySelector('.ui-widget-overlay')),
                };
                const estadoEl =
                    document.getElementById('ctl00_ctl00_cphM_cph_txtDescripcionEstado')
                    || document.querySelector("span[id*='txtDescripcionEstado']");
                const estadoFechaEl =
                    document.getElementById('ctl00_ctl00_cphM_cph_txtDescripcionEstadoFecha')
                    || document.querySelector("span[id*='txtDescripcionEstadoFecha']");
                const body = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim();
                const iframeUrls = Array.from(document.querySelectorAll('iframe'))
                    .map((f) => f.getAttribute('src') || '')
                    .filter(Boolean)
                    .slice(0, 8);
                return {
                    url: location.href,
                    ready_state: document.readyState || '',
                    estado: (estadoEl?.textContent || '').trim(),
                    estado_fecha: (estadoFechaEl?.textContent || '').trim(),
                    overlays,
                    iframe_urls: iframeUrls,
                    text_sample: body.slice(0, 260),
                };
            }"""
        )
        logger.warning("[AP-DIAG][%s] Browser snapshot: %s", label, diag)
    except Exception as e:
        logger.warning("[AP-DIAG][%s] No se pudo tomar browser snapshot: %s", label, e)


async def _aceptar_dialogo_xdg_open_linux(timeout_s: int = 95) -> None:
    """
    Fallback Linux: intenta aceptar el popup de Chromium
    "Open xdg-open?" para que no bloquee el flujo de firma.
    """
    if sys.platform.startswith("win"):
        return

    bash_script = rf"""
set -e
if ! command -v xdotool >/dev/null 2>&1; then
  echo "xdg-open-watcher-skip: xdotool-no-disponible"
  exit 0
fi
end_ts=$((SECONDS+{timeout_s}))
while [ $SECONDS -lt $end_ts ]; do
  ids="$(xdotool search --name "Open xdg-open\?|wants to open this application|xdg-open" 2>/dev/null || true)"
  for id in $ids; do
    xdotool windowactivate --sync "$id" 2>/dev/null || true
    # Intento primario: atajo del boton "Open xdg-open"
    xdotool key --window "$id" Alt+o 2>/dev/null || true
    sleep 0.12
    # Fallback: navegar al siguiente boton y confirmar
    xdotool key --window "$id" Tab Return 2>/dev/null || true
    echo "xdg-open-accepted window=$id"
    exit 0
  done
  sleep 0.2
done
echo "xdg-open-timeout"
"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash",
            "-lc",
            bash_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s + 5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("[AP-DIAG][xdg_open_dialog] Timeout tras %ss", timeout_s)
            return

        out = (out_b or b"").decode("utf-8", errors="ignore").strip()
        err = (err_b or b"").decode("utf-8", errors="ignore").strip()
        if out:
            logger.info("[AP-DIAG][xdg_open_dialog][OUT] %s", out)
        if err:
            logger.warning("[AP-DIAG][xdg_open_dialog][ERR] %s", err)
    except Exception as e:
        logger.warning("[AP-DIAG][xdg_open_dialog] Error ejecutando watcher Linux: %s", e)


async def _esperar_subida_completa(page: Page, config: AyuntaPalmaConfig) -> None:
    # Espera fija solicitada: dar margen a la subida antes de confirmar.
    await page.wait_for_timeout(6000)


async def _launch_autofirma_cert_acceptor() -> None:
    """
    Lanza en paralelo un watcher de UIAutomation que intenta:
    1) aceptar el dialogo del navegador para abrir AutoFirma (Obre/Abrir/Open),
    2) aceptar dialogos nativos encadenados (certificado/seguridad de Windows).
    """
    if not sys.platform.startswith("win"):
        return

    ps_script = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement

$buttonNames = @(
  "Obre", "Abrir", "Open"
)
$checkboxHints = @(
  "Permet sempre",
  "Permitir siempre",
  "Always allow",
  "siempre permitir",
  "always open"
)
$windowHints = @(
  "afirma", "autofirma", "portafirm",
  "protocol", "protocolo",
  "intentant obrir", "intentando abrir", "trying to open"
)

$clicks = 0
for ($i=0; $i -lt 180; $i++) {
  try {
    $condWindow = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Window
    )
    $wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condWindow)

    foreach ($win in $wins) {
      $wName = [string]$win.Current.Name
      if ([string]::IsNullOrWhiteSpace($wName)) { continue }

      $looksRelevant = $false
      $wLower = $wName.ToLowerInvariant()
      foreach ($hint in $windowHints) {
        if ($wLower.Contains($hint)) { $looksRelevant = $true; break }
      }
      if (-not $looksRelevant) { continue }

      # Activar "Permitir siempre" si existe.
      $condCheck = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::CheckBox
      )
      $checks = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condCheck)
      foreach ($chk in $checks) {
        $chkName = [string]$chk.Current.Name
        foreach ($hint in $checkboxHints) {
          if ($chkName -like "*$hint*") {
            try {
              $toggle = $chk.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
              if ($chk.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off) {
                $toggle.Toggle()
              }
            } catch {}
          }
        }
      }

      # Buscar botones de abrir/aceptar.
      $condBtn = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button
      )
      $buttons = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condBtn)
      foreach ($btn in $buttons) {
        $btnName = [string]$btn.Current.Name
        foreach ($target in $buttonNames) {
          if ($btnName -eq $target -or $btnName -like "*$target*") {
            try {
              $invoke = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
              $invoke.Invoke()
              Write-Output ("auto-open-click name=" + $btnName + " window=" + $wName)
              $clicks += 1
              Start-Sleep -Milliseconds 300
              if ($clicks -ge 2) { return }
            } catch {}
          }
        }
      }
    }
  } catch {}
  Start-Sleep -Milliseconds 500
}
"""
    # No bloquear el flujo principal esperando este watcher.
    logger.info("[AP-DIAG] Lanzando watcher autofirma_auto_open en background.")
    asyncio.create_task(_run_ps_diagnostic("autofirma_auto_open", ps_script, timeout_s=35))


async def _aceptar_certificado_windows() -> None:
    """
    Acepta el dialogo nativo de certificado de Windows.
    Estrategia: detectar ventana, llevar foco y pulsar Aceptar por UIAutomation
    (con fallback por teclado), sin spam de detecciones.
    """
    if not sys.platform.startswith("win"):
        return

    ps_script = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$wshell = New-Object -ComObject WScript.Shell
$logged = @{}

function Is-CertWindowTitle([string]$title) {
  if ([string]::IsNullOrWhiteSpace($title)) { return $false }
  $t = $title.ToLowerInvariant()
  if ($t.Contains("certificat")) { return $true }
  if ($t.Contains("certific")) { return $true }
  if ($t.Contains("security")) { return $true }
  if ($t.Contains("seguridad")) { return $true }
  if ($t.Contains("almacen windows")) { return $true }
  if ($t.Contains("almac")) { return $true }
  return $false
}

for ($i=0; $i -lt 420; $i++) {
  try {
    $condWindow = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Window
    )
    $wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condWindow)

    foreach ($w in $wins) {
      $title = [string]$w.Current.Name
      if (-not (Is-CertWindowTitle $title)) { continue }

      if (-not $logged.ContainsKey($title)) {
        Write-Output ("cert-window-detected title=" + $title)
        $logged[$title] = $true
      }

      try {
        try { $w.SetFocus() } catch {}
        try { $wshell.AppActivate($title) | Out-Null } catch {}
        Start-Sleep -Milliseconds 120

        $condBtn = New-Object System.Windows.Automation.PropertyCondition(
          [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
          [System.Windows.Automation.ControlType]::Button
        )
        $buttons = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condBtn)
        $clicked = $false
        foreach ($btn in $buttons) {
          $btnName = [string]$btn.Current.Name
          if ($btnName -eq "Aceptar" -or $btnName -eq "Accept" -or $btnName -eq "OK" -or $btnName -like "*Aceptar*") {
            try {
              $invoke = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
              $invoke.Invoke()
              Write-Output ("cert-accept-click name=" + $btnName + " title=" + $title)
              $clicked = $true
              break
            } catch {}
          }
        }

        if (-not $clicked) {
          $wshell.SendKeys('%a')
          Start-Sleep -Milliseconds 120
          $wshell.SendKeys('{ENTER}')
          Write-Output ("cert-accept-fallback-keys title=" + $title)
        }
        return
      } catch {
        Write-Output ("cert-accept-failed title=" + $title)
      }
    }
  } catch {}
  Start-Sleep -Milliseconds 500
}
Write-Output "cert-window-timeout"
"""
    await _run_ps_diagnostic("windows_cert_dialog", ps_script, timeout_s=220)

async def _aceptar_dialogo_edge_abrir_autofirma() -> None:
    """
    Fallback especifico para el dialogo de Edge:
    "Aquest lloc esta intentant obrir AutoFirma".
    Intenta clicar "Obre/Open" via UIAutomation cuando detecta ese texto.
    Si no puede, usa atajos de teclado como fallback.
    """
    if not sys.platform.startswith("win"):
        return

    ps_script = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$wshell = New-Object -ComObject WScript.Shell
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker

function Is-EdgePromptText([string]$txt) {
  if ([string]::IsNullOrWhiteSpace($txt)) { return $false }
  $t = $txt.ToLowerInvariant()
  if ($t.Contains("autofirma")) { return $true }
  if ($t.Contains("xaloc afirma handler")) { return $true }
  if ($t.Contains("open xaloc afirma")) { return $true }
  if ($t.Contains("abre xaloc afirma")) { return $true }
  if ($t.Contains("obre xaloc afirma")) { return $true }
  if ($t.Contains("intentant obrir")) { return $true }
  if ($t.Contains("intentando abrir")) { return $true }
  if ($t.Contains("trying to open")) { return $true }
  if ($t.Contains("wants to open")) { return $true }
  if ($t.Contains("open this application")) { return $true }
  return $false
}

function Get-ParentWindow($el) {
  $cur = $el
  for ($k=0; $k -lt 12; $k++) {
    if ($null -eq $cur) { return $null }
    try {
      if ($cur.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window) {
        return $cur
      }
    } catch {}
    $cur = $walker.GetParent($cur)
  }
  return $null
}

for ($i=0; $i -lt 360; $i++) {
  try {
    $targetWindow = $null
    $condText = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Text
    )
    $texts = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condText)
    foreach ($t in $texts) {
      $name = [string]$t.Current.Name
      if (-not (Is-EdgePromptText $name)) { continue }
      $targetWindow = Get-ParentWindow $t
      if ($null -ne $targetWindow) {
        Write-Output ("edge-open-dialog-detected title=" + [string]$targetWindow.Current.Name)
        break
      }
    }

    if ($null -eq $targetWindow) {
      Start-Sleep -Milliseconds 250
      continue
    }

    try { $targetWindow.SetFocus() } catch {}
    try { $wshell.AppActivate([string]$targetWindow.Current.Name) | Out-Null } catch {}
    Start-Sleep -Milliseconds 120

    $condCheck = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::CheckBox
    )
    $checks = $targetWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condCheck)
    foreach ($chk in $checks) {
      $chkName = [string]$chk.Current.Name
      if (
        $chkName -like "*Permet sempre*"
        -or $chkName -like "*Permitir siempre*"
        -or $chkName -like "*Always allow*"
        -or $chkName -like "*Always open*"
      ) {
        try {
          $toggle = $chk.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
          if ($chk.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off) {
            $toggle.Toggle()
            Write-Output ("edge-open-checkbox-checked name=" + $chkName)
          }
        } catch {}
      }
    }

    $condBtn = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Button
    )
    $buttons = $targetWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condBtn)
    foreach ($btn in $buttons) {
      $btnName = [string]$btn.Current.Name
      if (
        $btnName -eq "Obre"
        -or $btnName -eq "Abrir"
        -or $btnName -eq "Open"
        -or $btnName -like "*Obre*"
        -or $btnName -like "*Abrir*"
        -or $btnName -like "*Open*"
        -or $btnName -like "*Xaloc Afirma Handler*"
      ) {
        try {
          $invoke = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
          $invoke.Invoke()
          Write-Output ("edge-open-click name=" + $btnName)
          return
        } catch {}
      }
    }

    try {
      $wshell.SendKeys("%o")
      Start-Sleep -Milliseconds 100
      $wshell.SendKeys("{ENTER}")
      Write-Output "edge-open-fallback-keys"
      return
    } catch {}
  } catch {}
  Start-Sleep -Milliseconds 250
}
Write-Output "edge-open-timeout"
"""
    await _run_ps_diagnostic("edge_open_dialog", ps_script, timeout_s=95)

def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _build_unique_path(destino_dir: Path, filename: str) -> Path:
    base = Path(filename).stem
    ext = Path(filename).suffix or ".pdf"
    candidate = destino_dir / f"{base}{ext}"
    if not candidate.exists():
        return candidate

    ts = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
    candidate = destino_dir / f"{base} ({ts}){ext}"
    seq = 1
    while candidate.exists():
        seq += 1
        candidate = destino_dir / f"{base} ({ts})_{seq}{ext}"
    return candidate


def _folder_matches(folder_name: str, target_name: str) -> bool:
    folder_norm = _normalize_text(folder_name)
    target_norm = _normalize_text(target_name)
    if folder_norm == target_norm:
        return True
    target_words = set(target_norm.split())
    folder_words = set(folder_norm.split())
    if target_words.issubset(folder_words):
        return True
    target_singular = {w.rstrip("s") for w in target_words}
    folder_singular = {w.rstrip("s") for w in folder_words}
    return target_singular == folder_singular


def _find_or_create_subfolder(base_path: Path, folder_name: str) -> Path:
    if not folder_name:
        return base_path
    if base_path.exists():
        for item in base_path.iterdir():
            if item.is_dir() and _folder_matches(item.name, folder_name):
                return item
    new_folder = base_path / folder_name
    new_folder.mkdir(parents=True, exist_ok=True)
    return new_folder


_MOTIVO_TO_FOLDER = {
    "identificacion": "IDENTIFICACIONES",
    "denuncia": "ALEGACIONES",
    "propuesta de resolucion": "ALEGACIONES",
    "extraordinario de revision": "EXTRAORDINARIOS DE REVISIÃ“N",
    "subsanacion": "SUBSANACIONES",
    "reclamaciones": "RECLAMACIONES",
    "requerimiento embargo": "EMBARGOS",
    "sancion": "SANCIONES",
    "apremio": "APREMIOS",
    "embargo": "EMBARGOS",
}

_MOTIVO_ALIASES = {
    "identificacion": [
        "identificacion",
        "identificacio",
        "identificar conductor",
    ],
    "denuncia": [
        "denuncia",
        "alegacion",
        "alegaciones",
        "al legacio",
        "al legacions",
        "allegacio",
        "allegacions",
        "allegacions recursos multes",
    ],
    "propuesta de resolucion": [
        "propuesta de resolucion",
        "proposta de resolucio",
        "alegaciones propuesta resolucion",
    ],
    "extraordinario de revision": [
        "extraordinario de revision",
        "extraordinari de revisio",
        "revision extraordinaria",
    ],
    "subsanacion": [
        "subsanacion",
        "esmena",
        "subsanacio",
    ],
    "reclamaciones": [
        "reclamaciones",
        "reclamacion economico administrativa",
        "reclamacio economico administrativa",
    ],
    "requerimiento embargo": [
        "requerimiento embargo",
        "requerimiento de pago",
        "requeriment embargament",
    ],
    "sancion": [
        "sancion",
        "sancio",
        "resolucion sancionadora",
        "resolucio sancionadora",
    ],
    "apremio": [
        "apremio",
        "providencia de apremio",
        "providencia d apremi",
    ],
    "embargo": [
        "embargo",
        "embargament",
        "diligencia de embargo",
    ],
}


def _get_folder_name_from_fase(fase_raw: str | None) -> str:
    fase_norm = _normalize_text(fase_raw or "").replace("·", " ").strip()
    if not fase_norm:
        return ""

    # 1) Match exacto/cercano por aliases (como el resto de sites).
    for motivo_key, aliases in _MOTIVO_ALIASES.items():
        folder = _MOTIVO_TO_FOLDER.get(motivo_key, "")
        if not folder:
            continue
        for alias in aliases:
            alias_norm = _normalize_text(alias).replace("·", " ").strip()
            if not alias_norm:
                continue
            if fase_norm == alias_norm or alias_norm in fase_norm:
                return folder

    # 2) Match por key canonica de config_motivos.
    for motivo_key, folder_name in _MOTIVO_TO_FOLDER.items():
        key_norm = _normalize_text(motivo_key).replace("·", " ").strip()
        if key_norm and (fase_norm == key_norm or key_norm in fase_norm):
            return folder_name

    # 3) Fallback por keywords amplias.
    if any(k in fase_norm for k in ("allegac", "alegac", "denuncia", "proposta de resoluc", "propuesta de resoluc")):
        return "ALEGACIONES"
    if any(k in fase_norm for k in ("identific",)):
        return "IDENTIFICACIONES"
    if any(k in fase_norm for k in ("subsan", "esmena")):
        return "SUBSANACIONES"
    if any(k in fase_norm for k in ("reclam", "economico administrativa", "economico-administrativa")):
        return "RECLAMACIONES"
    if any(k in fase_norm for k in ("apremi",)):
        return "APREMIOS"
    if any(k in fase_norm for k in ("embarg",)):
        return "EMBARGOS"
    if any(k in fase_norm for k in ("sancio", "sancion")):
        return "SANCIONES"
    if any(k in fase_norm for k in ("revision",)):
        return "EXTRAORDINARIOS DE REVISIÃ“N"
    return ""


def _construir_ruta_recursos_telematicos(payload: dict | None) -> Path:
    payload = payload or {}
    client = client_identity_from_payload(payload)
    # Importante: resolver ruta base por plataforma.
    # En Linux/Docker debe usar /mnt/clientes (CLIENT_DOCS_BASE_PATH) y nunca UNC literal.
    base_path = resolve_client_docs_base_path()
    ruta_cliente_base = get_ruta_cliente_documentacion(client, base_path=base_path)
    ruta_recursos = _find_or_create_subfolder(ruta_cliente_base, "RECURSOS TELEMATICOS")
    logger.info("[AP-DIAG] Carpeta base cliente: %s", ruta_cliente_base)
    logger.info("[AP-DIAG] Carpeta recursos telematicos: %s", ruta_recursos)

    fase = payload.get("fase_procedimiento")
    folder_name = _get_folder_name_from_fase(fase)
    if folder_name:
        destino = _find_or_create_subfolder(ruta_recursos, folder_name)
        logger.info("[AP-DIAG] Carpeta destino por fase (%s): %s", fase, destino)
        return destino
    if fase:
        logger.warning("[AP-DIAG] Fase sin mapeo de carpeta especifica (%s). Se usa RECURSOS TELEMATICOS.", fase)
    return ruta_recursos


def _sanitize_filename_component(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r'[<>:"|?*\x00-\x1F]', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(". ")
    return text or "UNKNOWN"


def _extraer_n_expediente(payload: dict | None) -> str:
    payload = payload or {}
    keys = (
        "expediente",
        "expediente_num",
        "denuncia_num",
        "Expedient",
        "nExp",
        "numero_expediente",
        "idRecurso",
    )
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "UNKNOWN"


async def _esperar_exito_firma_o_refrescar(page: Page, config: AyuntaPalmaConfig) -> None:
    """
    Espera evidencia de exito de firma.
    Si en 2 minutos no aparece, refresca la pagina (caso pantalla gris) y reintenta.
    """
    success_diag_js = """() => {
        const t = (document.body?.innerText || "")
            .normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
        const estadoEl =
            document.getElementById("ctl00_ctl00_cphM_cph_txtDescripcionEstado")
            || document.querySelector("span[id*='txtDescripcionEstado']");
        const estado = ((estadoEl?.textContent || ""))
            .normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase().trim();

        const okByBanner =
            t.includes("instancia firmada correctamente")
            || t.includes("instancia signada correctament")
            || t.includes("signatura realitzada");
        const okByEstado =
            estado.includes("completada")
            || estado.includes("completat")
            || estado.includes("registrada")
            || estado.includes("registrat");
        const hasInstanciaRow = !!Array.from(document.querySelectorAll("input.descripcion.documento-pdf"))
            .find((el) => String(el?.value || "").toLowerCase().includes("instancia"));
        const isVisible = (el) => {
            if (!el) return false;
            const cs = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return cs.display !== "none" && cs.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
        };
        const loadingOverlay =
            isVisible(document.querySelector("#divProgressBar"))
            || isVisible(document.querySelector(".modalwait"))
            || isVisible(document.querySelector(".ui-widget-overlay"))
            || t.includes("cargando");
        return {
            ok: okByBanner || okByEstado || hasInstanciaRow,
            by_banner: okByBanner,
            by_estado: okByEstado,
            by_instancia_row: hasInstanciaRow,
            loading: loadingOverlay,
            estado,
            text_sample: t.slice(0, 220),
        };
    }"""

    async def _wait_success_with_diag(timeout_ms: int, attempt_label: str) -> None:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + (timeout_ms / 1000)
        last_diag: dict | None = None
        loading_seconds = 0
        while loop.time() < deadline:
            diag: dict | None = None
            try:
                diag = await page.evaluate(success_diag_js)
                if isinstance(diag, dict):
                    last_diag = diag
                    if bool(diag.get("ok")):
                        logger.info(
                            "[AP-DIAG] Exito de firma detectado (%s): by_banner=%s by_estado=%s by_instancia=%s estado=%s",
                            attempt_label,
                            bool(diag.get("by_banner")),
                            bool(diag.get("by_estado")),
                            bool(diag.get("by_instancia_row")),
                            diag.get("estado", ""),
                        )
                        return
                    if bool(diag.get("loading")):
                        loading_seconds += 1
                    else:
                        loading_seconds = 0
                    if loading_seconds >= 40:
                        await _dump_browser_signature_diag(page, f"{attempt_label}-loading>=40s")
                        await _dump_autofirma_windows_runtime_diag()
                        raise PlaywrightTimeoutError(
                            f"[AP-DIAG] Loading bloqueado ({attempt_label}) >=40s. last_diag={last_diag}"
                        )
            except PlaywrightTimeoutError:
                raise
            except Exception as e:
                logger.info("[AP-DIAG] Poll firma (%s) error no bloqueante: %s", attempt_label, e)
            await page.wait_for_timeout(1000)
        raise PlaywrightTimeoutError(f"[AP-DIAG] Timeout exito firma ({attempt_label}). last_diag={last_diag}")

    try:
        logger.info("[AP-DIAG] Esperando evidencia de exito de firma (intento 1, 90s)...")
        await _wait_success_with_diag(timeout_ms=90000, attempt_label="intento-1")
        return
    except Exception as e:
        await _dump_browser_signature_diag(page, "intento-1-timeout-or-stuck")
        await _dump_autofirma_windows_runtime_diag()
        logger.warning("[AP-DIAG] No se detecto exito en 90s. Probable pantalla gris; refrescando. detalle=%s", e)

    try:
        await page.reload(wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(config.delay_ms)
        await _esperar_velo_oculto(page, config)
        logger.info("[AP-DIAG] Reload completado. Reintentando espera de exito (intento 2, 90s)...")
    except Exception:
        logger.warning("[AP-DIAG] Error durante reload previo a reintento de exito.")

    await _wait_success_with_diag(timeout_ms=90000, attempt_label="intento-2")


async def _descargar_justificante_instancia(page: Page, payload: dict | None) -> Path:
    """
    Descarga el justificante de la fila "Instancia/InstÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ncia ..." y lo guarda
    en RECURSOS TELEMATICOS del cliente.
    """
    logger.info("[AP-DIAG] Buscando fila de justificante 'Instancia/InstÃƒÆ’Ã‚Â ncia'...")
    rows = page.locator("table.tabla-ficheros tbody tr")
    row_count = await rows.count()
    logger.info("[AP-DIAG] Filas de tabla de ficheros detectadas: %s", row_count)
    target_row = None
    for i in range(row_count):
        row = rows.nth(i)
        desc_input = row.locator("input.descripcion.documento-pdf").first
        if await desc_input.count() == 0:
            continue
        value = (await desc_input.get_attribute("value")) or ""
        value_norm = _normalize_text(value)
        logger.info("[AP-DIAG] Fila %s descripcion=%s", i, value)
        if "instancia" in value_norm:
            target_row = row
            break

    if target_row is None:
        raise RuntimeError("No se encontro la fila del justificante 'Instancia/InstÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ncia'.")

    download_input = target_row.locator("input[id$='_btnDescargar']").first
    if await download_input.count() == 0:
        raise RuntimeError("No se encontro el boton de descarga del justificante en la fila de Instancia.")

    download_url = (await download_input.get_attribute("data-clickable-url")) or ""
    logger.info("[AP-DIAG] URL de descarga justificante: %s", download_url)
    if not download_url:
        raise RuntimeError("No se pudo extraer 'data-clickable-url' del justificante.")

    response = await page.context.request.get(download_url, timeout=90000)
    if not response.ok:
        raise RuntimeError(f"Error descargando justificante (HTTP {response.status}).")
    pdf_bytes = await response.body()
    logger.info("[AP-DIAG] Descarga HTTP OK, bytes=%s", len(pdf_bytes))
    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError("El justificante descargado no parece PDF (%PDF ausente).")
    if len(pdf_bytes) < 2000:
        raise RuntimeError(f"Justificante PDF sospechosamente pequeno ({len(pdf_bytes)} bytes).")

    payload = payload or {}
    expediente = _sanitize_filename_component(_extraer_n_expediente(payload))
    filename = f"JUSTIFICANTE - {expediente}.pdf"
    tmp_dir = Path("tmp") / "ayunta_palma" / "justificantes" / str(payload.get("idRecurso") or "unknown")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = _build_unique_path(tmp_dir, filename)
    tmp_path.write_bytes(pdf_bytes)

    destino_dir = _construir_ruta_recursos_telematicos(payload)
    destino_dir.mkdir(parents=True, exist_ok=True)
    final_path = _build_unique_path(destino_dir, filename)
    shutil.copy2(tmp_path, final_path)
    tmp_path.unlink(missing_ok=True)
    logger.info("[AP-DIAG] Justificante guardado en carpeta cliente: %s", final_path)
    try:
        base_docs = Path(resolve_client_docs_base_path())
        if os.name != "nt" and not str(final_path).startswith(str(base_docs)):
            logger.warning(
                "[AP-DIAG] El justificante no quedo bajo CLIENT_DOCS_BASE_PATH. base=%s final=%s",
                base_docs,
                final_path,
            )
    except Exception:
        pass
    return final_path


async def _esperar_velo_oculto(page: Page, config: AyuntaPalmaConfig) -> None:
    try:
        await page.wait_for_selector(
            config.selectors.velo,
            state="hidden",
            timeout=config.timeouts.general,
        )
    except Exception:
        pass


async def _click_siguiente(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    
    clicked = False
    try:
        clicked = await page.evaluate(
            f"""() => {{
                const el = document.querySelector("{selectors.input_siguiente}");
                if (el) {{
                    el.click();
                    return true;
                }}
                return false;
            }}"""
        )
    except Exception as e:
        logger.info("[AP-DIAG] Excepcion al clickar Siguiente (probablemente recarga/ajax exitosa): %s", e)
        clicked = True

    if not clicked:
        btn = page.locator(selectors.btn_siguiente).first
        if await btn.count() > 0:
            try:
                await btn.click(force=True)
            except Exception as e:
                logger.info("[AP-DIAG] Excepcion fallback al clickar Siguiente: %s", e)
            
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _click_confirmar(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    
    clicked = False
    try:
        clicked = await page.evaluate(
            f"""() => {{
                const el = document.querySelector("{selectors.input_siguiente}");
                if (el) {{
                    el.click();
                    return true;
                }}
                return false;
            }}"""
        )
    except Exception as e:
        logger.info("[AP-DIAG] Excepcion al clickar Confirmar (probablemente recarga/ajax exitosa): %s", e)
        clicked = True

    if not clicked:
        btn_confirmar = page.locator(selectors.btn_confirmar).first
        if await btn_confirmar.count() > 0:
            try:
                await btn_confirmar.click(force=True)
            except Exception as e:
                logger.info("[AP-DIAG] Excepcion fallback al clickar Confirmar: %s", e)

    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _click_modal_aceptar(page: Page, config: AyuntaPalmaConfig) -> None:
    btn_modal_aceptar = page.locator(config.selectors.btn_modal_aceptar).first
    await btn_modal_aceptar.wait_for(state="visible", timeout=config.timeouts.general)
    await btn_modal_aceptar.click()
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _marcar_proteccion_datos(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    chk = page.locator(selectors.chk_proteccion_datos).first

    async def _try_check_locator(locator: Locator, *, allow_hidden_force: bool = False) -> bool:
        if await locator.count() <= 0:
            return False
        try:
            await locator.wait_for(state="visible", timeout=2500)
        except Exception:
            if not allow_hidden_force:
                return False
        try:
            if await locator.is_checked():
                return True
        except Exception:
            pass
        try:
            await locator.check(timeout=2500)
            return True
        except Exception:
            pass
        try:
            await locator.check(force=True, timeout=2500)
            return True
        except Exception:
            pass
        try:
            await locator.click(force=True, timeout=2500)
            return True
        except Exception:
            return False

    if await _try_check_locator(chk, allow_hidden_force=True):
        await page.wait_for_timeout(config.delay_ms)
        await _esperar_velo_oculto(page, config)
        logger.info("[AP-DIAG] Checkbox de proteccion/interoperabilidad marcado via selector exacto.")
        return

    # Fallback robusto: algunas versiones de Sedipualba cambian el ID exacto o
    # muestran el consentimiento con otro texto visible.
    fallback_result = await page.evaluate(
        """() => {
            const normalize = (txt) => String(txt || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();
            const keywords = [
                "proteccion de datos",
                "proteccio de dades",
                "interoperabilidad entre administraciones",
                "interoperabilitat entre administracions",
                "acepta la interoperabilidad",
                "accepta la interoperabilitat",
                "rgpd",
                "lopd"
            ];
            const textMatches = (txt) => {
                const norm = normalize(txt);
                return keywords.some((kw) => norm.includes(kw));
            };
            const clickCheckbox = (el, reason) => {
                if (!el) return null;
                try { el.scrollIntoView({ block: "center", inline: "center" }); } catch (e) {}
                try { el.click(); } catch (e) {}
                try {
                    if (typeof el.checked === "boolean") {
                        el.checked = true;
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                    }
                } catch (e) {}
                return {
                    ok: !!el.checked || el.getAttribute("aria-checked") === "true",
                    reason,
                    id: el.id || "",
                    name: el.name || ""
                };
            };

            const byId = document.querySelector("#ctl00_ctl00_cphM_cph_chkProteccionDatos");
            if (byId) {
                const res = clickCheckbox(byId, "exact-dom");
                if (res && res.ok) return res;
            }

            const checkboxes = Array.from(document.querySelectorAll("input[type='checkbox']"));
            for (const cb of checkboxes) {
                const idText = [cb.id, cb.name, cb.value].map(normalize).join(" ");
                if (idText.includes("proteccion") || idText.includes("interoper")) {
                    const res = clickCheckbox(cb, "checkbox-id-name-match");
                    if (res && res.ok) return res;
                }
            }

            const labels = Array.from(document.querySelectorAll("label"));
            for (const label of labels) {
                if (!textMatches(label.textContent || "")) continue;
                const forId = label.getAttribute("for");
                const linked = forId ? document.getElementById(forId) : label.querySelector("input[type='checkbox']");
                const res = clickCheckbox(linked, "label-text-match");
                if (res && res.ok) return res;
            }

            const containers = Array.from(document.querySelectorAll("div, td, span, li, p"));
            for (const node of containers) {
                if (!textMatches(node.textContent || "")) continue;
                const cb = node.querySelector("input[type='checkbox']") || node.closest("tr, div, li, td")?.querySelector("input[type='checkbox']");
                const res = clickCheckbox(cb, "container-text-match");
                if (res && res.ok) return res;
            }

            const sample = checkboxes.slice(0, 12).map((cb) => ({
                id: cb.id || "",
                name: cb.name || "",
                checked: !!cb.checked,
                text: normalize(cb.closest("tr, div, li, td, fieldset")?.textContent || "").slice(0, 180)
            }));
            return { ok: false, reason: "not-found", sample };
        }"""
    )

    if isinstance(fallback_result, dict) and fallback_result.get("ok"):
        await page.wait_for_timeout(config.delay_ms)
        await _esperar_velo_oculto(page, config)
        logger.info(
            "[AP-DIAG] Checkbox de proteccion/interoperabilidad marcado via fallback reason=%s id=%s name=%s",
            fallback_result.get("reason"),
            fallback_result.get("id"),
            fallback_result.get("name"),
        )
        return

    raise PlaywrightTimeoutError(
        "Ayunta Palma: no se encontro el checkbox de proteccion/interoperabilidad. "
        f"Diagnostico={fallback_result!r}"
    )


async def _click_firmar(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    btn_firmar = page.locator(selectors.btn_firmar).first
    if await btn_firmar.count() > 0 and await btn_firmar.is_visible():
        try:
            await btn_firmar.click()
        except Exception:
            try:
                await btn_firmar.click(force=True)
            except Exception:
                await page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    selectors.btn_firmar,
                )
    else:
        hidden_input = page.locator(selectors.input_firmar).first
        if await hidden_input.count() > 0:
            if await hidden_input.is_visible():
                try:
                    await hidden_input.click()
                except Exception:
                    await hidden_input.click(force=True)
            else:
                await page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    selectors.input_firmar,
                )
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _modal_firma_lista(page: Page, config: AyuntaPalmaConfig) -> bool:
    """
    Detecta si ya estamos en el punto donde se puede pulsar
    'Signar tots els documents' (modal/iframe de firma listo).
    """
    try:
        locator = page.locator("button.btnFirmar, button:has-text('Signar tots els documents')").first
        if await locator.count() > 0 and await locator.is_visible():
            return True
    except Exception:
        pass
    for fr in page.frames:
        try:
            locator = fr.locator("button.btnFirmar, button:has-text('Signar tots els documents')").first
            if await locator.count() > 0 and await locator.is_visible():
                return True
        except Exception:
            continue
    return False


async def _click_firmar_con_reintentos(page: Page, config: AyuntaPalmaConfig, max_intentos: int = 3) -> None:
    """
    Algunos intentos de click en pre-firma no hacen efecto.
    Reintenta si el boton "Firmar" sigue visible tras unos segundos.
    """
    if await _modal_firma_lista(page, config):
        logger.info("[AP-DIAG] Pre-firma: modal de firma ya lista, se omite click en 'Firmar'.")
        return

    edge_hint_task: asyncio.Task | None = None
    for intento in range(1, max_intentos + 1):
        logger.info("[AP-DIAG] Pre-firma intento %s/%s: click en Firmar.", intento, max_intentos)
        await _click_firmar(page, config)
        await page.wait_for_timeout(1800)

        if await _modal_firma_lista(page, config):
            logger.info("[AP-DIAG] Pre-firma: modal de firma lista tras intento %s.", intento)
            return

        try:
            btn_firmar = page.locator(config.selectors.btn_firmar).first
            sigue_visible = await btn_firmar.count() > 0 and await btn_firmar.is_visible()
        except Exception:
            sigue_visible = False

        if not sigue_visible:
            logger.info("[AP-DIAG] Pre-firma: boton Firmar ya no visible tras intento %s.", intento)
            return

        logger.warning("[AP-DIAG] Pre-firma: boton Firmar sigue visible tras intento %s.", intento)
        if edge_hint_task is None or edge_hint_task.done():
            logger.info("[AP-DIAG] Pre-firma: lanzando watcher Edge en background (no bloqueante).")
            edge_hint_task = asyncio.create_task(_aceptar_dialogo_edge_abrir_autofirma())
        await page.wait_for_timeout(1200)

    logger.warning("[AP-DIAG] Pre-firma: agotados reintentos; continuamos con flujo y watchers.")


async def _click_signar_tots_documents(page: Page, config: AyuntaPalmaConfig) -> None:
    deadline_ms = config.timeouts.general
    waited = 0
    step = 500
    while waited < deadline_ms:
        # Camino principal: click directo dentro del iframe de Portafirmas.
        clicked_modal = await page.evaluate(
            """() => {
                const iframe =
                    document.querySelector("div.ui-dialog iframe#ventanaModal")
                    || document.querySelector("iframe#ventanaModal")
                    || document.querySelector("iframe[src*='/firma/firmar.aspx']");
                if (!iframe) return false;
                const w = iframe.contentWindow;
                const d = iframe.contentDocument || (w && w.document);
                if (!d) return false;
                const norm = (s) => String(s || "").toLowerCase().replace(/\\s+/g, " ").trim();
                const all = Array.from(d.querySelectorAll("button, input[type='submit'], input[type='button']"));
                const btn = all.find((el) => {
                    const txt = norm(el.textContent || el.value || el.getAttribute("title") || "");
                    const idn = norm(el.id || "");
                    const cls = norm(el.className || "");
                    if (txt.includes("signar tots els documents")) return true;
                    if (txt.includes("firmar todos los documentos")) return true;
                    if (txt.includes("firmar tots els documents")) return true;
                    if (idn.includes("btnfirmar")) return true;
                    if (cls.includes("btnfirmar")) return true;
                    return false;
                });
                if (!btn) return false;
                try { btn.click(); } catch (e) {}
                return true;
            }"""
        )
        if clicked_modal:
            logger.info("[AP-DIAG] Click directo en boton 'Signar tots els documents' dentro de ventanaModal.")
            await page.wait_for_timeout(config.delay_ms)
            await _esperar_velo_oculto(page, config)
            return

        # Fallback: localizar en frames detectados por Playwright.
        for fr in page.frames:
            try:
                locator = fr.locator(
                    "button.btn.btnFirmar, button.btnFirmar, input[type='submit'][id*='btnFirmar'], input[type='submit'][name*='btnFirmar'], input[type='submit'][value*='Signar'], input[type='submit'][value*='Firmar']"
                ).first
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.click(force=True, timeout=2000)
                    logger.info("[AP-DIAG] Click fallback Playwright en boton btnFirmar (frame=%s).", fr.url)
                    await page.wait_for_timeout(config.delay_ms)
                    await _esperar_velo_oculto(page, config)
                    return
            except Exception:
                continue

        await page.wait_for_timeout(step)
        waited += step

    raise PlaywrightTimeoutError("No se pudo clickar 'Signar tots els documents' en ventanaModal.")


async def _verificar_firma_realizada(page: Page, config: AyuntaPalmaConfig) -> None:
    """
    Verifica que aparezca la confirmacion de firma.
    Como fallback, valida que no siga en estado pendiente/no registrado.
    """
    await _esperar_exito_firma_o_refrescar(page, config)

    estado_selector = "#ctl00_ctl00_cphM_cph_txtDescripcionEstado"
    estado_fecha_selector = "#ctl00_ctl00_cphM_cph_txtDescripcionEstadoFecha"
    try:
        estado = _normalize_text(await page.locator(estado_selector).first.inner_text())
    except Exception:
        estado = ""
    try:
        estado_fecha = _normalize_text(await page.locator(estado_fecha_selector).first.inner_text())
    except Exception:
        estado_fecha = ""
    logger.info("[AP-DIAG] Estado post-firma: estado='%s' estado_fecha='%s'", estado, estado_fecha)

    pending_estado = (
        ("pendiente de firma" in estado)
        or ("pendent de signatura" in estado)
    )
    pending_fecha = (
        ("no registrado" in estado_fecha)
        or ("no registrat" in estado_fecha)
    )
    if pending_estado or pending_fecha:
        raise PlaywrightTimeoutError(
            "Firma no confirmada: la pagina sigue indicando estado pendiente/no registrado."
        )


async def _subir_via_selector_ficheros(
    page: Page,
    config: AyuntaPalmaConfig,
    archivos: list[Path],
) -> None:
    """
    Usa el selector nativo Playwright expect_file_chooser() para dar los archivos
    al widget JS nuevo de "SelectorFicheros".
    """
    logger.info("[AP-DIAG] Lanzando file_chooser para SelectorFicheros")

    # Hacer click en el boton "Enviar fitxer" o "Enviar fichero" para abrir el dialog
    # El boton tiene la clase .btn-icono y contiene un span o texto descriptivo.
    btn_enviar = page.locator(
        "button:has-text('Enviar fitxer'), button:has-text('Enviar fichero'), button[data-icono='list.svg']"
    ).first

    async with page.expect_file_chooser() as fc_info:
        await btn_enviar.click()
    
    file_chooser = await fc_info.value
    rutas = [str(p.resolve()) for p in archivos]
    logger.info(f"[AP-DIAG] Subiendo en file_chooser: {rutas}")
    await file_chooser.set_files(rutas)

    # Esperar a que el widget complete su subida AJAX. 
    # Cuando acaba, el hidden input hfNuevoFichero pasa a tener la clave "files" con datos.
    hf_selector = config.selectors.hf_nuevo_fichero
    deadline = 30
    import json as _json
    for _ in range(deadline):
        hf_check = await page.locator(hf_selector).first.get_attribute("value") or ""
        try:
            hf_check_data = _json.loads(hf_check)
            if hf_check_data.get("files"):
                logger.info("[AP-DIAG] Upload via SelectorFicheros completado. files=%s", hf_check_data["files"])
                # Dar un pequenyo buffer para evitar condiciones de carrera de UI
                await page.wait_for_timeout(1000)
                return
        except Exception:
            pass
        await page.wait_for_timeout(1000)

    logger.warning(
        "[AP-DIAG] Timeout esperando confirmacion en hfNuevoFichero tras upload. Continuando."
    )


async def subir_documentos(
    page: Page,
    config: AyuntaPalmaConfig,
    archivos: list[Path] | None,
    payload: dict | None = None,
) -> Page:
    logger.info("[AP-DIAG] Inicio subir_documentos. archivos=%s", 0 if not archivos else len(archivos))
    if not archivos:
        logger.info("[AP-DIAG] Sin archivos; se omite fase documentos.")
        return page

    selectors = config.selectors
    
    await page.wait_for_timeout(3000)
    
    clicked_anadir = False
    try:
        clicked_anadir = await page.evaluate("""() => {
            const els = document.querySelectorAll("input[id$='_btnDocumentoAPresentarNuevoFichero']");
            if (els.length > 0) {
                els[els.length - 1].click();
                return true;
            }
            return false;
        }""")
    except Exception as e:
        logger.info("[AP-DIAG] Excepcion al clickar Anadir: %s", e)
        clicked_anadir = True
        
    if not clicked_anadir:
        boton_anadir = page.locator(selectors.btn_anadir_documento).first
        if await boton_anadir.count() > 0:
            try:
                await boton_anadir.click(force=True)
            except Exception as e:
                logger.info("[AP-DIAG] Excepcion fallback al clickar Anadir: %s", e)

    await page.wait_for_timeout(config.delay_ms)
    logger.info("[AP-DIAG] Dialogo de anadir documento abierto.")

    # Esperar explícitamente a que el panel del nuevo fichero sea visible
    modal_fichero = page.locator("#ctl00_ctl00_cphM_cph_pnlNuevoFichero").first
    await modal_fichero.wait_for(state="visible", timeout=15000)

    await _subir_via_selector_ficheros(page, config, archivos)
    logger.info("[AP-DIAG] Upload de archivos completado.")

    logger.info("[AP-DIAG] Esperando 5 segundos antes de aceptar documento...")
    await page.wait_for_timeout(5000)

    clicked_aceptar = False
    try:
        clicked_aceptar = await page.evaluate("""() => {
            // Buscamos el boton visual "Aceptar" en lugar del hidden input
            // Tiene data-icono="aceptar.svg" o clase "btn-bl2" y dice "Aceptar"
            const btns = Array.from(document.querySelectorAll("button"));
            const btn = btns.find(b => b.textContent && b.textContent.includes("Aceptar") && b.closest(".btn-bar"));
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        }""")
    except Exception as e:
        logger.info("[AP-DIAG] Excepcion al clickar Aceptar fichero: %s", e)
        clicked_aceptar = True

    if not clicked_aceptar:
        confirmar = page.locator(selectors.btn_confirmar_archivo).first
        if await confirmar.count() > 0:
            try:
                await confirmar.click(force=True)
            except Exception as e:
                logger.info("[AP-DIAG] Excepcion fallback al clickar Aceptar fichero: %s", e)
            
    # CRITICO: Esperar a que el modal se cierre (la carga/ajax termino)
    try:
        await modal_fichero.wait_for(state="hidden", timeout=30000)
    except Exception as e:
        logger.info("[AP-DIAG] Modal no se oculto tras aceptar fichero: %s", e)
            
    await page.wait_for_timeout(config.delay_ms)
    logger.info("[AP-DIAG] Confirmacion de archivo subida pulsada.")

    # 1) Avanzar tras aceptar el documento subido.
    await _click_siguiente(page, config)

    # 2) Marcar protecciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n de datos y avanzar.
    await page.wait_for_timeout(config.delay_ms)
    await _marcar_proteccion_datos(page, config)
    await _click_siguiente(page, config)

    # 3) Aceptar modal intermedio y confirmar.
    await page.wait_for_timeout(config.delay_ms)
    await _click_modal_aceptar(page, config)
    await _click_confirmar(page, config)
    logger.info("[AP-DIAG] Navegacion previa a firma completada.")

    # 4) Firma — cross-platform
    #
    # En Linux/Docker: intercept the afirma:// URL via JS, call AutoFirmaCommandLine,
    # inject the signature back into the page.
    #
    # En Windows: fallback a los watchers de UIAutomation existentes.
    logger.info("[AP-DIAG] Pre-firma: click en boton Firmar.")
    await _click_firmar_con_reintentos(page, config, max_intentos=3)

    if sys.platform.startswith("win"):
        # ── Windows path (original UIAutomation approach) ──────────────────
        logger.info("[AP-DIAG] Plataforma Windows: usando watchers UIAutomation.")
        logger.info("[AP-DIAG] Lanzando watcher edge_open_dialog en background.")
        edge_task = asyncio.create_task(_aceptar_dialogo_edge_abrir_autofirma())
        auto_monitor_task = asyncio.create_task(monitor_autofirma_windows(timeout_s=120))
        await _launch_autofirma_cert_acceptor()
        logger.info("[AP-DIAG] Arrancando watcher de certificado Windows en paralelo.")
        cert_task = asyncio.create_task(_aceptar_certificado_windows())
        await page.wait_for_timeout(2000)
        logger.info("[AP-DIAG] Firma modal: click en 'Signar tots els documents'.")
        await _click_signar_tots_documents(page, config)
        if not edge_task.done():
            logger.info("[AP-DIAG] edge_open_dialog sigue activo en background.")
        logger.info("[AP-DIAG] Esperando resultado del watcher de certificado Windows.")
        try:
            await cert_task
        except Exception as e:
            logger.warning("[AP-DIAG] Watcher certificado devolvio error: %s", e)
        try:
            monitor_res = await auto_monitor_task
            logger.info(
                "[AP-DIAG] AutoFirma monitor: edge_clicked=%s cert_clicked=%s autofirma_seen=%s autofirma_clicks=%s timed_out=%s",
                monitor_res.edge_clicked,
                monitor_res.cert_clicked,
                monitor_res.autofirma_windows_seen,
                monitor_res.autofirma_clicks,
                monitor_res.timed_out,
            )
        except Exception as e:
            logger.warning("[AP-DIAG] AutoFirma monitor devolvio error: %s", e)
        if not edge_task.done():
            logger.info("[AP-DIAG] edge_open_dialog no ha terminado; esperamos 3s finales.")
            try:
                await asyncio.wait_for(edge_task, timeout=3)
            except Exception:
                logger.warning("[AP-DIAG] edge_open_dialog sigue pendiente tras 3s; continuamos.")
    else:
        # ── Linux/Docker path (programmatic signing) ────────────────────────
        logger.info("[AP-DIAG] Plataforma Linux/Docker: usando firma programatica.")
        logger.info("[AP-DIAG] Lanzando watcher Linux xdg_open_dialog en background.")
        xdg_task = asyncio.create_task(_aceptar_dialogo_xdg_open_linux(timeout_s=95))
        # Click the inner iframe "Signar tots els documents" button first to
        # trigger the afirma:// URL emission, while our intercept is already armed
        # inside firmar_programaticamente().
        try:
            signed = await firmar_programaticamente(page)
            if not signed:
                # AutoFirmaCommandLine not available — try clicking the button anyway
                # and hope the environment has a different mechanism.
                logger.warning(
                    "[AP-DIAG] Firma programatica no disponible; intentando click en 'Signar tots els documents' directamente."
                )
                try:
                    await _click_signar_tots_documents(page, config)
                except Exception as click_err:
                    # Non-fatal: in some runs the signature flow has already advanced,
                    # and the button is no longer clickable/visible.
                    logger.warning(
                        "[AP-DIAG][NON_FATAL] No se pudo clickar 'Signar tots' en fallback: %s. "
                        "Se continua con verificacion de estado de firma.",
                        click_err,
                    )
            if not xdg_task.done():
                try:
                    await asyncio.wait_for(xdg_task, timeout=2)
                except Exception:
                    pass
        except Exception as e:
            logger.error("[AP-DIAG] Error en firma programatica: %s", e)
            if not xdg_task.done():
                xdg_task.cancel()
            raise
    logger.info("[AP-DIAG] Validando firma real.")
    await _verificar_firma_realizada(page, config)
    logger.info("[AP-DIAG] Firma validada; iniciando descarga de justificante.")
    justificante_path = await _descargar_justificante_instancia(page, payload)
    logger.info("ayunta_palma: Justificante guardado en: %s", justificante_path)
    return page
