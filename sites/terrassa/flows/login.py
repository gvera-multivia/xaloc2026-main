from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ._page_eval import evaluate_with_nav_retry

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page
    from ..config import TerrassaConfig
    from ..data_models import TerrassaTarget

logger = logging.getLogger("xaloc_automation.terrassa")


async def _watch_windows_cert_dialog_select_hint(cert_hint: str, timeout_s: int) -> bool:
    """
    Fallback Windows-only: selecciona un certificado por texto (CN parcial)
    en el dialogo nativo y pulsa Aceptar.
    """
    if not sys.platform.startswith("win"):
        return False
    hint = (cert_hint or "").strip()
    if not hint:
        return False

    loops = max(40, int(timeout_s * 4))
    hint_json = json.dumps(hint.lower())
    ps_script = rf"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$hint = {hint_json}
$picked = 0
$accepted = 0

function Norm([string]$s) {{
  if ([string]::IsNullOrWhiteSpace($s)) {{ return "" }}
  return $s.ToLowerInvariant()
}}

function Find-CertWindow($rootEl) {{
  $condWindow = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Window
  )
  $wins = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Children, $condWindow)
  foreach ($w in $wins) {{
    $title = Norm ([string]$w.Current.Name)
    if ($title.Contains("certificat") -or $title.Contains("certificado") -or $title.Contains("certific") -or $title.Contains("security")) {{
      return $w
    }}
    try {{
      $condText = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Text
      )
      $texts = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condText)
      foreach ($t in $texts) {{
        $n = Norm ([string]$t.Current.Name)
        if ($n.Contains("certificat") -or $n.Contains("certificado") -or $n.Contains("almac") -or $n.Contains("security")) {{
          return $w
        }}
      }}
    }} catch {{}}
  }}
  return $null
}}

function Try-SelectByHint($win, [string]$hintText) {{
  $types = @(
    [System.Windows.Automation.ControlType]::ListItem,
    [System.Windows.Automation.ControlType]::DataItem,
    [System.Windows.Automation.ControlType]::Text
  )
  foreach ($tp in $types) {{
    $cond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $tp
    )
    try {{
      $items = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
      foreach ($it in $items) {{
        $name = Norm ([string]$it.Current.Name)
        if ([string]::IsNullOrWhiteSpace($name)) {{ continue }}
        if (-not $name.Contains($hintText)) {{ continue }}
        try {{
          $sel = $it.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
          $sel.Select()
          Write-Output ("pick item=" + [string]$it.Current.Name)
          return $true
        }} catch {{}}
        try {{
          $inv = $it.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
          $inv.Invoke()
          Write-Output ("pick item=" + [string]$it.Current.Name)
          return $true
        }} catch {{}}
        try {{
          $it.SetFocus()
          Write-Output ("pick focus_item=" + [string]$it.Current.Name)
          return $true
        }} catch {{}}
      }}
    }} catch {{}}
  }}
  return $false
}}

function Try-Accept($win) {{
  $condBtn = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button
  )
  try {{
    $buttons = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condBtn)
    foreach ($b in $buttons) {{
      $name = Norm ([string]$b.Current.Name)
      if ($name -eq "aceptar" -or $name -eq "accept" -or $name -eq "ok" -or $name.Contains("aceptar")) {{
        try {{
          $inv = $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
          $inv.Invoke()
          Write-Output ("accept button=" + [string]$b.Current.Name)
          return $true
        }} catch {{}}
      }}
    }}
  }} catch {{}}
  return $false
}}

for ($i=0; $i -lt {loops}; $i++) {{
  try {{
    $w = Find-CertWindow $root
    if ($null -ne $w) {{
      try {{ $w.SetFocus() }} catch {{}}
      if ($picked -eq 0) {{
        if (Try-SelectByHint $w $hint) {{ $picked = 1 }}
      }}
      if ($picked -eq 1 -and $accepted -eq 0) {{
        Start-Sleep -Milliseconds 100
        if (Try-Accept $w) {{
          $accepted = 1
          break
        }}
      }}
    }}
  }} catch {{}}
  Start-Sleep -Milliseconds 250
}}

Write-Output ("summary picked=" + $picked + " accepted=" + $accepted)
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
    picked = False
    accepted = False

    async def _read_stdout() -> None:
        nonlocal picked, accepted
        while True:
            line_b = await proc.stdout.readline()
            if not line_b:
                break
            line = line_b.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            logger.info("terrassa.login.cert_popup: %s", line)
            if line.startswith("summary "):
                picked = "picked=1" in line
                accepted = "accepted=1" in line

    async def _read_stderr() -> None:
        while True:
            line_b = await proc.stderr.readline()
            if not line_b:
                break
            line = line_b.decode("utf-8", errors="ignore").strip()
            if line:
                logger.warning("terrassa.login.cert_popup.err: %s", line)

    out_task = asyncio.create_task(_read_stdout())
    err_task = asyncio.create_task(_read_stderr())
    try:
        await asyncio.wait_for(proc.wait(), timeout=max(5, timeout_s + 5))
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    finally:
        await out_task
        await err_task

    return picked and accepted


async def _fallback_cert_button_by_role(page: "Page") -> "Locator":
    button = page.get_by_role("button", name=re.compile(r"certificat|certificado", re.IGNORECASE)).first
    if await button.count() <= 0:
        raise RuntimeError("terrassa.login: no se encontro boton de acceso con certificado.")
    return button


async def _resolve_cert_button(page: "Page", selector: str, timeout_ms: int) -> "Locator":
    locator = page.locator(selector)
    deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0
    last_count = 0

    while time.monotonic() < deadline:
        try:
            await locator.first.wait_for(state="attached", timeout=800)
        except Exception:
            await page.wait_for_timeout(150)
            continue

        try:
            last_count = await locator.count()
        except Exception:
            last_count = 0
        if last_count <= 0:
            await page.wait_for_timeout(150)
            continue

        for idx in range(last_count):
            candidate = locator.nth(idx)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue
        await page.wait_for_timeout(150)

    if last_count > 0:
        return locator.first
    return await _fallback_cert_button_by_role(page)


async def _click_cert_button_robusto(page: "Page", selector: str, timeout_ms: int) -> None:
    cert_btn = await _resolve_cert_button(page, selector, timeout_ms)
    try:
        await cert_btn.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass

    for kwargs in ({"no_wait_after": True}, {"no_wait_after": True, "force": True}):
        try:
            await cert_btn.click(timeout=5000, **kwargs)
            logger.info("terrassa.login: click en boton certificado lanzado kwargs=%s", kwargs)
            return
        except Exception as exc:
            logger.warning("terrassa.login: click boton certificado fallo kwargs=%s error=%s", kwargs, exc)
            continue

    try:
        await cert_btn.dispatch_event("click")
        logger.info("terrassa.login: dispatch_event('click') lanzado sobre boton certificado")
        return
    except Exception as exc:
        logger.warning("terrassa.login: dispatch_event('click') fallo: %s", exc)

    clicked = await evaluate_with_nav_retry(
        page,
        """(selector) => {
            const isVisible = (el) => {
                if (!el) return false;
                const st = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return !!st && st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
            };
            const nodes = Array.from(document.querySelectorAll(selector));
            if (!nodes.length) return false;
            const target = nodes.find((el) => isVisible(el)) || nodes[0];
            for (const [name, Ctor] of [
                ["pointerdown", PointerEvent],
                ["mousedown", MouseEvent],
                ["pointerup", PointerEvent],
                ["mouseup", MouseEvent],
                ["click", MouseEvent],
            ]) {
                try {
                    target.dispatchEvent(new Ctor(name, { bubbles: true, cancelable: true }));
                } catch (_err) {}
            }
            try { target.click(); } catch (_err) {}
            return true;
        }""",
        selector,
    )
    if not clicked:
        raise RuntimeError(f"terrassa.login: no se pudo clicar el boton de certificado selector={selector!r}")
    logger.info("terrassa.login: fallback JS click lanzado sobre boton certificado")


async def _goto_tramit_with_retry(page: "Page", *, url: str, base_timeout_ms: int) -> None:
    attempts: tuple[tuple[str, int], ...] = (
        ("domcontentloaded", max(60000, int(base_timeout_ms))),
        ("load", max(90000, int(base_timeout_ms) + 30000)),
    )
    last_exc: Exception | None = None
    for idx, (wait_until, timeout_ms) in enumerate(attempts, start=1):
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return
        except PlaywrightTimeoutError as exc:
            last_exc = exc
            logger.warning(
                "terrassa.login: timeout en goto intento=%s/%s wait_until=%s timeout_ms=%s url=%s",
                idx,
                len(attempts),
                wait_until,
                timeout_ms,
                url,
            )
            await page.wait_for_timeout(2000)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"terrassa.login: fallo inesperado navegando a {url}")


async def run_login(page: "Page", config: "TerrassaConfig", datos: "TerrassaTarget") -> "Page":
    _ = datos
    await _goto_tramit_with_retry(page, url=config.url_tramit, base_timeout_ms=max(config.timeouts.general, 60000))
    await page.wait_for_load_state("domcontentloaded")

    start_link = page.locator(f"a[href='{config.href_omplir_form}']").first
    await start_link.wait_for(state="visible", timeout=config.timeouts.transicion)
    await start_link.click()
    await page.wait_for_load_state("domcontentloaded")

    # Puede entrar directo al formulario (sesion activa) o pedir identificacion.
    if await page.locator(f"a[href='{config.href_identificar}']").count() > 0:
        await page.locator(f"a[href='{config.href_identificar}']").first.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_url("**valid.aoc.cat/**", timeout=config.timeouts.login)

        cert_hint = (
            os.getenv("XALOC_WINDOWS_CERT_HINT")
            or os.getenv("CERTIFICADO_CN")
            or ""
        ).strip()
        cert_popup_task: asyncio.Task[bool] | None = None
        if cert_hint and sys.platform.startswith("win"):
            timeout_s = max(20, int(config.auth_timeout_ms / 1000))
            cert_popup_task = asyncio.create_task(
                _watch_windows_cert_dialog_select_hint(cert_hint, timeout_s=timeout_s)
            )

        try:
            await _click_cert_button_robusto(page, config.cert_button_selector, config.timeouts.login)
        except (PlaywrightTimeoutError, RuntimeError) as exc:
            logger.warning("terrassa.login: click CSS fallo (%s); reintentando por rol/nombre", exc)
            cert_btn = await _fallback_cert_button_by_role(page)
            try:
                await cert_btn.scroll_into_view_if_needed()
            except Exception:
                pass
            await cert_btn.click(timeout=5000, no_wait_after=True, force=True)

        # El selector de certificado del SO es manual.
        await page.wait_for_url("**/tramits/ferTramit.jsp**", timeout=config.auth_timeout_ms)
        await page.wait_for_load_state("domcontentloaded")
        if cert_popup_task:
            try:
                if cert_popup_task.done():
                    selected = cert_popup_task.result()
                    logger.info("terrassa.login.cert_popup: watcher finalizado selected=%s", selected)
                else:
                    cert_popup_task.cancel()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("terrassa.login.cert_popup: watcher error=%s", exc)

    await page.locator(f"a[href='{config.href_actuar_representant}']").first.wait_for(
        state="visible",
        timeout=config.timeouts.transicion,
    )
    return page
