"""
Subida de documentos en el flujo de Ayunta Palma.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from sites.ayunta_palma.config import AyuntaPalmaConfig


async def _esperar_subida_completa(page: Page, config: AyuntaPalmaConfig) -> None:
    # Espera fija solicitada: dar margen a la subida antes de confirmar.
    await page.wait_for_timeout(6000)


async def _launch_autofirma_cert_acceptor() -> None:
    """
    Lanza en paralelo un watcher de UIAutomation que intenta:
    1) aceptar el dialogo del navegador para abrir AutoFirma (Obre/Abrir/Open),
    2) aceptar el dialogo nativo de certificados (Aceptar/Acceptar/OK).
    """
    if not sys.platform.startswith("win"):
        return

    ps_script = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement

$buttonNames = @("Obre", "Abrir", "Open", "Aceptar", "Acceptar", "OK")
$checkboxHints = @("Permet sempre", "Permitir siempre", "Always allow")

for ($i=0; $i -lt 120; $i++) {
  try {
    # Intentar activar el checkbox de "permitir siempre" si aparece.
    $condCheck = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::CheckBox
    )
    $checks = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condCheck)
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

    # Buscar botones compatibles con abrir AutoFirma/aceptar certificado.
    $condBtn = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Button
    )
    $buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condBtn)
    foreach ($btn in $buttons) {
      $btnName = [string]$btn.Current.Name
      foreach ($target in $buttonNames) {
        if ($btnName -eq $target -or $btnName -like "*$target*") {
          try {
            $invoke = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
            $invoke.Invoke()
            return
          } catch {}
        }
      }
    }
  } catch {}
  Start-Sleep -Milliseconds 500
}
"""
    try:
        await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception:
        # No bloquear el flujo web si falla el watcher.
        pass


async def _aceptar_certificado_windows() -> None:
    """
    Fallback para el dialogo nativo de seleccion de certificado en Windows.
    Busca una ventana con titulo de certificado/seleccion, la enfoca y envia Enter.
    """
    if not sys.platform.startswith("win"):
        return

    ps_script = r"""
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class User32 {
  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

$wshell = New-Object -ComObject WScript.Shell

for ($i=0; $i -lt 25; $i++) {
  $wins = Get-Process | Where-Object {
    $_.MainWindowHandle -ne 0 -and (
      $_.MainWindowTitle -like "*Certificado*" -or
      $_.MainWindowTitle -like "*Certificat*" -or
      $_.MainWindowTitle -like "*Seleccione*" -or
      $_.MainWindowTitle -like "*Selecciona*" -or
      $_.MainWindowTitle -like "*Security*"
    )
  }

  foreach ($w in $wins) {
    try {
      [User32]::SetForegroundWindow($w.MainWindowHandle) | Out-Null
      Start-Sleep -Milliseconds 250
      $wshell.SendKeys('{ENTER}')
      return
    } catch {}
  }
  Start-Sleep -Milliseconds 500
}
"""
    try:
        await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception:
        pass


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
    btn = page.locator(selectors.btn_siguiente).first
    if await btn.count() > 0 and await btn.is_visible():
        await btn.click()
    else:
        hidden_input = page.locator(selectors.input_siguiente).first
        if await hidden_input.count() > 0:
            if await hidden_input.is_visible():
                await hidden_input.click()
            else:
                await page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    selectors.input_siguiente,
                )
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _click_confirmar(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    btn_confirmar = page.locator(selectors.btn_confirmar).first
    if await btn_confirmar.count() > 0 and await btn_confirmar.is_visible():
        await btn_confirmar.click()
    else:
        # En esta pantalla "Confirmar" puede reutilizar el input hidden de btnSiguiente.
        hidden_input = page.locator(selectors.input_siguiente).first
        if await hidden_input.count() > 0:
            if await hidden_input.is_visible():
                await hidden_input.click()
            else:
                await page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    selectors.input_siguiente,
                )
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _click_modal_aceptar(page: Page, config: AyuntaPalmaConfig) -> None:
    btn_modal_aceptar = page.locator(config.selectors.btn_modal_aceptar).first
    await btn_modal_aceptar.wait_for(state="visible", timeout=config.timeouts.general)
    await btn_modal_aceptar.click()
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _marcar_proteccion_datos(page: Page, config: AyuntaPalmaConfig) -> None:
    chk = page.locator(config.selectors.chk_proteccion_datos).first
    await chk.wait_for(state="visible", timeout=config.timeouts.general)
    if not await chk.is_checked():
        try:
            await chk.check()
        except Exception:
            await chk.check(force=True)
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def _click_firmar(page: Page, config: AyuntaPalmaConfig) -> None:
    selectors = config.selectors
    btn_firmar = page.locator(selectors.btn_firmar).first
    if await btn_firmar.count() > 0 and await btn_firmar.is_visible():
        await btn_firmar.click()
    else:
        hidden_input = page.locator(selectors.input_firmar).first
        if await hidden_input.count() > 0:
            if await hidden_input.is_visible():
                await hidden_input.click()
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


async def _click_signar_tots_documents(page: Page, config: AyuntaPalmaConfig) -> None:
    async def _try_click_in_frame(frame) -> bool:
        candidates = [
            frame.locator("button.btnFirmar").first,
            frame.locator("button", has_text="Signar tots els documents").first,
            frame.locator("button", has_text="Firmar todos los documentos").first,
            frame.locator(config.selectors.btn_signar_tots_documents).first,
        ]
        for locator in candidates:
            try:
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.click()
                    return True
            except Exception:
                try:
                    await locator.click(force=True)
                    return True
                except Exception:
                    continue
        return False

    deadline_ms = config.timeouts.general
    waited = 0
    step = 1000
    while waited < deadline_ms:
        if await _try_click_in_frame(page):
            await page.wait_for_timeout(config.delay_ms)
            await _esperar_velo_oculto(page, config)
            return
        for fr in page.frames:
            if fr is page.main_frame:
                continue
            if await _try_click_in_frame(fr):
                await page.wait_for_timeout(config.delay_ms)
                await _esperar_velo_oculto(page, config)
                return
        await page.wait_for_timeout(step)
        waited += step

    # Fallback final por JS en main frame.
    clicked = await page.evaluate(
        """() => {
            const byClass = document.querySelector('button.btnFirmar');
            if (byClass) { byClass.click(); return true; }
            const buttons = Array.from(document.querySelectorAll('button'));
            const target = buttons.find(b => {
                const t = (b.textContent || '').toLowerCase();
                return t.includes('signar tots els documents') || t.includes('firmar todos los documentos');
            });
            if (target) { target.click(); return true; }
            return false;
        }"""
    )
    if not clicked:
        raise PlaywrightTimeoutError("No se localizó el botón 'Signar tots els documents' en la página/frames.")
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


async def subir_documentos(
    page: Page,
    config: AyuntaPalmaConfig,
    archivos: list[Path] | None,
) -> Page:
    if not archivos:
        return page

    selectors = config.selectors
    boton_anadir = page.locator(selectors.btn_anadir_documento)
    await boton_anadir.wait_for(state="visible")
    await boton_anadir.click()
    await page.wait_for_timeout(config.delay_ms)

    ruta = [str(p) for p in archivos]
    await page.set_input_files(selectors.archivo_input, ruta)
    await _esperar_subida_completa(page, config)

    confirmar = page.locator(selectors.btn_confirmar_archivo)
    await confirmar.wait_for(state="visible", timeout=config.timeouts.general)
    await confirmar.click(timeout=config.timeouts.subida_archivo)
    await page.wait_for_timeout(config.delay_ms)

    # 1) Avanzar tras aceptar el documento subido.
    await _click_siguiente(page, config)

    # 2) Marcar protección de datos y avanzar.
    await page.wait_for_timeout(config.delay_ms)
    await _marcar_proteccion_datos(page, config)
    await _click_siguiente(page, config)

    # 3) Aceptar modal intermedio y confirmar.
    await page.wait_for_timeout(config.delay_ms)
    await _click_modal_aceptar(page, config)
    await _click_confirmar(page, config)

    # 4) Ir a firma y lanzar firma de todos los documentos.
    await page.wait_for_timeout(config.delay_ms)
    await _launch_autofirma_cert_acceptor()
    await _click_firmar(page, config)
    await _launch_autofirma_cert_acceptor()
    await _aceptar_certificado_windows()
    await _click_signar_tots_documents(page, config)
    await _aceptar_certificado_windows()
    return page
