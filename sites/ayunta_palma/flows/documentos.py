"""
Subida de documentos en el flujo de Ayunta Palma.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from core.client_documentation import client_identity_from_payload, get_ruta_cliente_documentacion
from sites.ayunta_palma.config import AyuntaPalmaConfig
from sites.ayunta_palma.flows.autofirma_monitor import monitor_autofirma_windows

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
  if ($t.Contains("intentant obrir")) { return $true }
  if ($t.Contains("intentando abrir")) { return $true }
  if ($t.Contains("trying to open")) { return $true }
  if ($t.Contains("wants to open")) { return $true }
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
      if ($chkName -like "*Permet sempre*" -or $chkName -like "*Permitir siempre*" -or $chkName -like "*Always allow*") {
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
      if ($btnName -eq "Obre" -or $btnName -eq "Abrir" -or $btnName -eq "Open" -or $btnName -like "*Obre*" -or $btnName -like "*Abrir*" -or $btnName -like "*Open*") {
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


def _get_folder_name_from_fase(fase_raw: str | None) -> str:
    motivo_to_folder = {
        "identificacion": "IDENTIFICACIONES",
        "denuncia": "ALEGACIONES",
        "propuesta de resolucion": "ALEGACIONES",
        "extraordinario de revision": "EXTRAORDINARIOS DE REVISIÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œN",
        "subsanacion": "SUBSANACIONES",
        "reclamaciones": "RECLAMACIONES",
        "requerimiento embargo": "EMBARGOS",
        "sancion": "SANCIONES",
        "apremio": "APREMIOS",
        "embargo": "EMBARGOS",
    }
    fase_norm = _normalize_text(fase_raw or "")
    for motivo_key, folder_name in motivo_to_folder.items():
        if motivo_key in fase_norm:
            return folder_name
    return ""


def _construir_ruta_recursos_telematicos(payload: dict | None) -> Path:
    payload = payload or {}
    client = client_identity_from_payload(payload)
    base_path = r"\\SERVER-DOC\clientes"
    ruta_cliente_base = get_ruta_cliente_documentacion(client, base_path=base_path)
    ruta_recursos = _find_or_create_subfolder(ruta_cliente_base, "RECURSOS TELEMATICOS")

    fase = payload.get("fase_procedimiento")
    folder_name = _get_folder_name_from_fase(fase)
    if folder_name:
        return _find_or_create_subfolder(ruta_recursos, folder_name)
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
    Espera el texto de exito de firma.
    Si en 2 minutos no aparece, refresca la pagina (caso pantalla gris) y reintenta.
    """
    success_js = """() => {
        const t = (document.body?.innerText || "")
            .normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
        return t.includes("instancia firmada correctamente");
    }"""

    try:
        logger.info("[AP-DIAG] Esperando texto de exito de firma (intento 1, 120s)...")
        await page.wait_for_function(success_js, timeout=120000)
        logger.info("[AP-DIAG] Texto de exito detectado en intento 1.")
        return
    except Exception:
        logger.warning("[AP-DIAG] No se detecto exito en 120s. Probable pantalla gris; refrescando.")

    try:
        await page.reload(wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(config.delay_ms)
        await _esperar_velo_oculto(page, config)
        logger.info("[AP-DIAG] Reload completado. Reintentando espera de exito (intento 2, 120s)...")
    except Exception:
        logger.warning("[AP-DIAG] Error durante reload previo a reintento de exito.")

    await page.wait_for_function(success_js, timeout=120000)
    logger.info("[AP-DIAG] Texto de exito detectado en intento 2.")


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
    tmp_path = tmp_dir / filename
    tmp_path.write_bytes(pdf_bytes)

    destino_dir = _construir_ruta_recursos_telematicos(payload)
    destino_dir.mkdir(parents=True, exist_ok=True)
    final_path = destino_dir / filename
    if final_path.exists():
        final_path.unlink()
    shutil.copy2(tmp_path, final_path)
    tmp_path.unlink(missing_ok=True)
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
        await page.wait_for_timeout(1200)

    logger.warning("[AP-DIAG] Pre-firma: agotados reintentos; continuamos con flujo y watchers.")


async def _click_signar_tots_documents(page: Page, config: AyuntaPalmaConfig) -> None:
    async def _get_ventana_modal_frame():
        try:
            iframe = page.locator("#ventanaModal").first
            if await iframe.count() == 0:
                return None
            handle = await iframe.element_handle()
            if handle is None:
                return None
            return await handle.content_frame()
        except Exception:
            return None

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
                    await locator.scroll_into_view_if_needed()
                    await locator.click(timeout=4000)
                    return True
            except Exception:
                try:
                    await locator.click(force=True, timeout=4000)
                    return True
                except Exception:
                    continue
        try:
            return bool(
                await frame.evaluate(
                    """() => {
                        const byClass = document.querySelector('button.btnFirmar');
                        if (byClass) { byClass.click(); return true; }
                        const buttons = Array.from(document.querySelectorAll('button'));
                        const target = buttons.find((b) => {
                            const t = (b.textContent || '').toLowerCase();
                            return t.includes('signar tots els documents') || t.includes('firmar todos los documentos');
                        });
                        if (target) { target.click(); return true; }
                        return false;
                    }"""
                )
            )
        except Exception:
            return False
        return False

    deadline_ms = config.timeouts.general
    waited = 0
    step = 1000
    while waited < deadline_ms:
        modal_frame = await _get_ventana_modal_frame()
        if modal_frame is not None and await _try_click_in_frame(modal_frame):
            await page.wait_for_timeout(config.delay_ms)
            await _esperar_velo_oculto(page, config)
            return
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
        raise PlaywrightTimeoutError("No se localizÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³ el botÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n 'Signar tots els documents' en la pÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡gina/frames.")
    await page.wait_for_timeout(config.delay_ms)
    await _esperar_velo_oculto(page, config)


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

    if ("pendiente de firma" in estado) or ("no registrado" in estado_fecha):
        raise PlaywrightTimeoutError(
            "Firma no confirmada: la pagina sigue indicando estado pendiente/no registrado."
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
    boton_anadir = page.locator(selectors.btn_anadir_documento)
    await boton_anadir.wait_for(state="visible")
    await boton_anadir.click()
    await page.wait_for_timeout(config.delay_ms)
    logger.info("[AP-DIAG] Dialogo de anadir documento abierto.")

    ruta = [str(p) for p in archivos]
    await page.set_input_files(selectors.archivo_input, ruta)
    await _esperar_subida_completa(page, config)
    logger.info("[AP-DIAG] Upload de archivos completado.")

    confirmar = page.locator(selectors.btn_confirmar_archivo)
    await confirmar.wait_for(state="visible", timeout=config.timeouts.general)
    await confirmar.click(timeout=config.timeouts.subida_archivo)
    await page.wait_for_timeout(config.delay_ms)
    logger.info("[AP-DIAG] Confirmacion de archivo subida pulsada.")

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
    logger.info("[AP-DIAG] Navegacion previa a firma completada.")

    # 4) Ir a firma y lanzar firma de todos los documentos.
    await page.wait_for_timeout(config.delay_ms)
    await page.wait_for_timeout(2000)
    logger.info("[AP-DIAG] Pre-firma: click/reintentos en boton Firmar.")
    await _click_firmar_con_reintentos(page, config, max_intentos=3)
    logger.info("[AP-DIAG] Arrancando monitor unificado AutoFirma/Edge/Certificado.")
    autofirma_monitor_task = asyncio.create_task(monitor_autofirma_windows(timeout_s=70))
    await page.wait_for_timeout(2000)
    logger.info("[AP-DIAG] Firma modal: click en 'Signar tots els documents'.")
    await _click_signar_tots_documents(page, config)

    logger.info("[AP-DIAG] Esperando resultado del monitor unificado.")
    try:
        monitor_result = await asyncio.wait_for(autofirma_monitor_task, timeout=80)
        logger.info(
            "[AP-DIAG] Monitor AutoFirma: edge_clicked=%s cert_clicked=%s autofirma_seen=%s autofirma_clicks=%s timed_out=%s",
            monitor_result.edge_clicked,
            monitor_result.cert_clicked,
            monitor_result.autofirma_windows_seen,
            monitor_result.autofirma_clicks,
            monitor_result.timed_out,
        )
    except Exception as e:
        logger.warning("[AP-DIAG] Monitor unificado devolvio error/timeout: %s", e)
    logger.info("[AP-DIAG] Validando firma real.")
    await _verificar_firma_realizada(page, config)
    logger.info("[AP-DIAG] Firma validada; iniciando descarga de justificante.")
    justificante_path = await _descargar_justificante_instancia(page, payload)
    logger.info("ayunta_palma: Justificante guardado en: %s", justificante_path)
    return page
