from __future__ import annotations

import asyncio
import logging
import re
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AutofirmaMonitorResult:
    edge_clicked: int = 0
    cert_clicked: int = 0
    autofirma_windows_seen: int = 0
    autofirma_clicks: int = 0
    timed_out: bool = False


def _parse_summary_line(line: str) -> AutofirmaMonitorResult:
    kv = dict(re.findall(r"([a-z_]+)=([0-9]+)", line or ""))
    return AutofirmaMonitorResult(
        edge_clicked=int(kv.get("edge_clicked", "0")),
        cert_clicked=int(kv.get("cert_clicked", "0")),
        autofirma_windows_seen=int(kv.get("autofirma_seen", "0")),
        autofirma_clicks=int(kv.get("autofirma_clicks", "0")),
        timed_out="timed_out=1" in (line or ""),
    )


async def monitor_autofirma_windows(timeout_s: int = 70) -> AutofirmaMonitorResult:
    """
    Monitor unico de UIAutomation optimizado para BACKGROUND/MINIMIZADO.
    Usa patrones (Invoke/LegacyIAccessible) en lugar de clicks fisicos o SendKeys.
    """
    if not sys.platform.startswith("win"):
        return AutofirmaMonitorResult()

    loops = max(40, int(timeout_s * 4))

    # Script PowerShell modificado para no requerir foco visual
    ps_script = rf"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$seen = @{{}}
$acted = @{{}}
$edgeClicked = 0
$certClicked = 0
$afSeen = 0
$afClicks = 0

function Norm([string]$s) {{
  if ([string]::IsNullOrWhiteSpace($s)) {{ return "" }}
  return $s.ToLowerInvariant()
}}

function Get-Texts($win) {{
  $condText = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Text
  )
  $arr = @()
  try {{
    # TreeScope Descendants permite ver dentro aunque no este renderizado
    $texts = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condText)
    foreach ($t in $texts) {{
      $name = [string]$t.Current.Name
      if (-not [string]::IsNullOrWhiteSpace($name)) {{
        $arr += $name.Trim()
        if ($arr.Count -ge 8) {{ break }}
      }}
    }}
  }} catch {{}}
  return $arr
}}

function Get-Buttons($win) {{
  $condBtn = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button
  )
  $arr = @()
  try {{
    $buttons = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condBtn)
    foreach ($b in $buttons) {{
      $n = [string]$b.Current.Name
      if (-not [string]::IsNullOrWhiteSpace($n)) {{
        $arr += $n.Trim()
        if ($arr.Count -ge 12) {{ break }}
      }}
    }}
  }} catch {{}}
  return $arr
}}

function Kind-Window([string]$title, $texts) {{
  $all = ((Norm $title) + " " + (Norm (($texts -join " "))))
  if ($all.Contains("intentant obrir autofirma") -or $all.Contains("intentando abrir autofirma") -or $all.Contains("trying to open autofirma") -or $all.Contains("wants to open")) {{ return "edge_open" }}
  if ($all.Contains("dialogo de seguridad") -or $all.Contains("security dialog") -or $all.Contains("certificat") -or $all.Contains("certific") -or $all.Contains("almacen windows")) {{ return "windows_cert" }}
  if ($all.Contains("autofirma") -or $all.Contains("portafirm")) {{ return "autofirma" }}
  return ""
}}

# Funcion CLAVE: Intenta pulsar sin mover el raton y sin foco
function Try-Click-Pattern($element) {{
    # 1. Invoke Pattern (Estandar moderno)
    try {{
        $inv = $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $inv.Invoke()
        return "invoke"
    }} catch {{}}

    # 2. LegacyIAccessible (CRITICO PARA JAVA / AUTOFIRMA / MINIMIZADO)
    try {{
        $leg = $element.GetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern)
        $leg.DoDefaultAction()
        return "legacy"
    }} catch {{}}

    # 3. Toggle Pattern (A veces los botones son toggles)
    try {{
        $tog = $element.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
        $tog.Toggle()
        return "toggle"
    }} catch {{}}

    return ""
}}

function Set-EdgeCheckbox($win) {{
  $condCheck = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::CheckBox
  )
  try {{
    $checks = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condCheck)
    foreach ($chk in $checks) {{
      $chkName = Norm ([string]$chk.Current.Name)
      if ($chkName.Contains("permet sempre") -or $chkName.Contains("permitir siempre") -or $chkName.Contains("always allow")) {{
        # Intentamos marcarlo sin foco
        try {{
             $toggle = $chk.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
             if ($chk.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off) {{
                $toggle.Toggle()
                Write-Output "edge_open checkbox=checked_toggle"
             }}
        }} catch {{
             # Fallback Legacy para Checkbox
             try {{
                $leg = $chk.GetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern)
                $leg.DoDefaultAction()
                Write-Output "edge_open checkbox=checked_legacy"
             }} catch {{}}
        }}
      }}
    }}
  }} catch {{}}
}}

function Click-ButtonByHints($win, $hints, [string]$kind) {{
  $condBtn = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button
  )
  $buttons = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condBtn)

  foreach ($btn in $buttons) {{
    $btnName = [string]$btn.Current.Name
    $n = Norm $btnName
    foreach ($hint in $hints) {{
      if ($n -eq $hint -or $n.Contains($hint)) {{
        $method = Try-Click-Pattern $btn
        if ($method) {{
            Write-Output ("click kind=" + $kind + " button=" + $btnName + " method=" + $method)
            return $btnName
        }} else {{
            Write-Output ("click_failed_patterns kind=" + $kind + " button=" + $btnName)
        }}
      }}
    }}
  }}
  return ""
}}

for ($i=0; $i -lt {loops}; $i++) {{
  try {{
    $condWindow = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Window
    )
    # Buscamos ventanas (FindAll funciona mejor que iterar children manualmente si esta minimizado)
    $wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condWindow)

    foreach ($w in $wins) {{
      $title = [string]$w.Current.Name
      if ([string]::IsNullOrWhiteSpace($title)) {{ continue }}

      # Obtenemos textos para identificar el tipo
      $texts = Get-Texts $w
      $buttons = Get-Buttons $w # Solo para logging
      $kind = Kind-Window $title $texts

      if (-not $kind) {{ continue }}

      $key = $kind + "|" + $title
      if (-not $seen.ContainsKey($key)) {{
        $seen[$key] = $true
        # Dump simplificado para log
        Write-Output ("window_found kind=" + $kind + " title=" + $title)
      }}

      if ($acted.ContainsKey($key)) {{ continue }}

      # --- AQUI ESTA EL CAMBIO IMPORTANTE ---
      # Eliminados: SetFocus, AppActivate, SendKeys.
      # Ahora confiamos puramente en UI Automation Patterns.

      if ($kind -eq "edge_open") {{
        Set-EdgeCheckbox $w
        $btnClicked = Click-ButtonByHints $w @("obre","abrir","open") "edge_open"
        if (-not [string]::IsNullOrWhiteSpace($btnClicked)) {{
          $edgeClicked += 1
          $acted[$key] = $true
        }}
      }} elseif ($kind -eq "windows_cert") {{
        $btnClicked = Click-ButtonByHints $w @("aceptar","accept","ok") "windows_cert"
        if (-not [string]::IsNullOrWhiteSpace($btnClicked)) {{
          $certClicked += 1
          $acted[$key] = $true
        }}
      }} elseif ($kind -eq "autofirma") {{
        $afSeen += 1
        # Anadidos mas hints por si acaso
        $btnClicked = Click-ButtonByHints $w @("firmar","signar","aceptar","acceptar","yes","si") "autofirma"
        if (-not [string]::IsNullOrWhiteSpace($btnClicked)) {{
          $afClicks += 1
          $acted[$key] = $true
        }}
      }}
    }}
  }} catch {{}}
  Start-Sleep -Milliseconds 250
}}

$timedOut = 1
if ($edgeClicked -gt 0 -or $certClicked -gt 0 -or $afClicks -gt 0) {{
  $timedOut = 0
}}
Write-Output ("summary edge_clicked=" + $edgeClicked + " cert_clicked=" + $certClicked + " autofirma_seen=" + $afSeen + " autofirma_clicks=" + $afClicks + " timed_out=" + $timedOut)
"""

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

    summary = AutofirmaMonitorResult()

    async def _read_stdout() -> None:
        nonlocal summary
        while True:
            line_b = await proc.stdout.readline()
            if not line_b:
                break
            line = line_b.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            logger.info("[AP-AUTOFIRMA] %s", line)
            if line.startswith("summary "):
                summary = _parse_summary_line(line)

    async def _read_stderr() -> None:
        while True:
            line_b = await proc.stderr.readline()
            if not line_b:
                break
            line = line_b.decode("utf-8", errors="ignore").strip()
            if line:
                logger.warning("[AP-AUTOFIRMA][ERR] %s", line)

    out_task = asyncio.create_task(_read_stdout())
    err_task = asyncio.create_task(_read_stderr())

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s + 5)
    except asyncio.TimeoutError:
        summary.timed_out = True
        proc.kill()
        await proc.wait()
    finally:
        await out_task
        await err_task

    return summary
