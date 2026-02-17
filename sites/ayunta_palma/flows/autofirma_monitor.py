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
    Monitor unico de UIAutomation para:
    - dialogo Edge de abrir AutoFirma,
    - dialogo de certificado Windows,
    - ventana de AutoFirma (con log de contenido y botones visibles).
    """
    if not sys.platform.startswith("win"):
        return AutofirmaMonitorResult()

    loops = max(40, int(timeout_s * 4))
    ps_script = rf"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$wshell = New-Object -ComObject WScript.Shell
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$seen = @{{}}
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
  if ($all.Contains("intentant obrir autofirma") -or $all.Contains("intentando abrir autofirma") -or $all.Contains("trying to open autofirma")) {{ return "edge_open" }}
  if ($all.Contains("dialogo de seguridad del almacen windows") -or $all.Contains("diálogo de seguridad del almacén windows") -or $all.Contains("security dialog") -or $all.Contains("certificat") -or $all.Contains("certific")) {{ return "windows_cert" }}
  if ($all.Contains("autofirma") -or $all.Contains("portafirm")) {{ return "autofirma" }}
  return ""
}}

function Dump-Window($kind, $title, $texts, $buttons) {{
  $safeTitle = ($title -replace "`r|`n", " ").Trim()
  $safeTexts = (($texts -join " | ") -replace "`r|`n", " ").Trim()
  $safeButtons = (($buttons -join " | ") -replace "`r|`n", " ").Trim()
  Write-Output ("window kind=" + $kind + " title=" + $safeTitle)
  if ($safeTexts) {{ Write-Output ("window_text kind=" + $kind + " text=" + $safeTexts) }}
  if ($safeButtons) {{ Write-Output ("window_buttons kind=" + $kind + " buttons=" + $safeButtons) }}
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
        try {{
          $invoke = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
          $invoke.Invoke()
          Write-Output ("click kind=" + $kind + " button=" + $btnName)
          return $true
        }} catch {{}}
      }}
    }}
  }}
  return $false
}}

for ($i=0; $i -lt {loops}; $i++) {{
  try {{
    $condWindow = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Window
    )
    $wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condWindow)
    foreach ($w in $wins) {{
      $title = [string]$w.Current.Name
      if ([string]::IsNullOrWhiteSpace($title)) {{ continue }}
      $texts = Get-Texts $w
      $buttons = Get-Buttons $w
      $kind = Kind-Window $title $texts
      if (-not $kind) {{ continue }}

      $key = $kind + "|" + $title
      if (-not $seen.ContainsKey($key)) {{
        $seen[$key] = $true
        Dump-Window $kind $title $texts $buttons
      }}

      try {{ $w.SetFocus() }} catch {{}}
      try {{ $wshell.AppActivate($title) | Out-Null }} catch {{}}

      if ($kind -eq "edge_open") {{
        $clicked = Click-ButtonByHints $w @("obre","abrir","open") "edge_open"
        if (-not $clicked) {{
          try {{
            $wshell.SendKeys("%o")
            Start-Sleep -Milliseconds 120
            $wshell.SendKeys("{{ENTER}}")
            Write-Output "click kind=edge_open button=keyboard_fallback"
            $clicked = $true
          }} catch {{}}
        }}
        if ($clicked) {{ $edgeClicked += 1 }}
      }} elseif ($kind -eq "windows_cert") {{
        $clicked = Click-ButtonByHints $w @("aceptar","accept","ok") "windows_cert"
        if (-not $clicked) {{
          try {{
            $wshell.SendKeys("%a")
            Start-Sleep -Milliseconds 120
            $wshell.SendKeys("{{ENTER}}")
            Write-Output "click kind=windows_cert button=keyboard_fallback"
            $clicked = $true
          }} catch {{}}
        }}
        if ($clicked) {{ $certClicked += 1 }}
      }} elseif ($kind -eq "autofirma") {{
        $afSeen += 1
        $clicked = Click-ButtonByHints $w @("firmar","signar","acceptar","acceptar i firmar","aceptar y firmar") "autofirma"
        if ($clicked) {{ $afClicks += 1 }}
      }}
    }}
  }} catch {{}}
  Start-Sleep -Milliseconds 250
}}

$timedOut = 1
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

