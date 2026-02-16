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

logger = logging.getLogger(__name__)


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
    Busca ventanas de certificado/seguridad y pulsa "Aceptar/OK" por UIAutomation.
    """
    if not sys.platform.startswith("win"):
        return

    ps_script = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class User32 {
  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

$root = [System.Windows.Automation.AutomationElement]::RootElement
$wshell = New-Object -ComObject WScript.Shell
$windowHints = @(
  "Diálogo de seguridad del almacén Windows",
  "Seleccione un certificado",
  "Certificado", "Certificat", "Certificate",
  "Seguridad", "Security", "Windows"
)
$buttonNames = @("Aceptar", "Acceptar", "OK", "Si", "Yes")
$sentEnterFallback = $false

for ($i=0; $i -lt 240; $i++) {
  try {
    $condWindow = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Window
    )
    $wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condWindow)

    foreach ($win in $wins) {
      $wName = [string]$win.Current.Name
      if ([string]::IsNullOrWhiteSpace($wName)) { continue }

      $match = $false
      foreach ($hint in $windowHints) {
        if ($wName -like "*$hint*") { $match = $true; break }
      }
      if (-not $match) { continue }

      try {
        $hWnd = [IntPtr]$win.Current.NativeWindowHandle
        if ($hWnd -ne [IntPtr]::Zero) {
          [User32]::SetForegroundWindow($hWnd) | Out-Null
        }
      } catch {}

      $clicked = $false
      try {
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
                $clicked = $true
                break
              } catch {}
            }
          }
          if ($clicked) { break }
        }
      } catch {}

      if (-not $clicked -and -not $sentEnterFallback) {
        try {
          # Unico fallback de teclado para no "spammear" el dialogo.
          Start-Sleep -Milliseconds 150
          $wshell.SendKeys('{ENTER}')
          $sentEnterFallback = $true
        } catch {}
      }

      if ($clicked) { return }
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
        pass


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

$hints = @(
  "intentant obrir autofirma",
  "intentando abrir autofirma",
  "trying to open autofirma",
  "wants to open this application",
  "vol obrir aquesta aplicacio",
  "vol obrir aquesta aplicació"
)

for ($i=0; $i -lt 80; $i++) {
  try {
    $condText = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Text
    )
    $texts = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condText)
    $found = $false
    foreach ($t in $texts) {
      $name = [string]$t.Current.Name
      if ([string]::IsNullOrWhiteSpace($name)) { continue }
      $low = $name.ToLowerInvariant()
      foreach ($hint in $hints) {
        if ($low.Contains($hint)) {
          $found = $true
          break
        }
      }
      if ($found) { break }
    }

    if ($found) {
      $clicked = $false
      try {
        # Primer intento: click directo de botones del propio dialogo.
        $condBtn = New-Object System.Windows.Automation.PropertyCondition(
          [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
          [System.Windows.Automation.ControlType]::Button
        )
        $buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condBtn)
        foreach ($btn in $buttons) {
          $btnName = [string]$btn.Current.Name
          if ($btnName -eq "Obre" -or $btnName -eq "Abrir" -or $btnName -eq "Open" -or $btnName -like "*Obre*" -or $btnName -like "*Abrir*" -or $btnName -like "*Open*") {
            try {
              $invoke = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
              $invoke.Invoke()
              $clicked = $true
              break
            } catch {}
          }
        }
      } catch {}

      if (-not $clicked) {
        try {
          # Fallback 1: atajo directo.
          $wshell.SendKeys('%o')
          Start-Sleep -Milliseconds 180
          # Fallback 2: navegar foco y confirmar.
          $wshell.SendKeys('+{TAB}{ENTER}')
        } catch {}
      }
      return
    }
  } catch {}
  Start-Sleep -Milliseconds 250
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
        "extraordinario de revision": "EXTRAORDINARIOS DE REVISIÓN",
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
        await page.wait_for_function(success_js, timeout=120000)
        return
    except Exception:
        pass

    try:
        await page.reload(wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(config.delay_ms)
        await _esperar_velo_oculto(page, config)
    except Exception:
        pass

    await page.wait_for_function(success_js, timeout=120000)


async def _descargar_justificante_instancia(page: Page, payload: dict | None) -> Path:
    """
    Descarga el justificante de la fila "Instancia/Instància ..." y lo guarda
    en RECURSOS TELEMATICOS del cliente.
    """
    rows = page.locator("table.tabla-ficheros tbody tr")
    row_count = await rows.count()
    target_row = None
    for i in range(row_count):
        row = rows.nth(i)
        desc_input = row.locator("input.descripcion.documento-pdf").first
        if await desc_input.count() == 0:
            continue
        value = (await desc_input.get_attribute("value")) or ""
        value_norm = _normalize_text(value)
        if "instancia" in value_norm:
            target_row = row
            break

    if target_row is None:
        raise RuntimeError("No se encontro la fila del justificante 'Instancia/Instància'.")

    download_input = target_row.locator("input[id$='_btnDescargar']").first
    if await download_input.count() == 0:
        raise RuntimeError("No se encontro el boton de descarga del justificante en la fila de Instancia.")

    download_url = (await download_input.get_attribute("data-clickable-url")) or ""
    if not download_url:
        raise RuntimeError("No se pudo extraer 'data-clickable-url' del justificante.")

    response = await page.context.request.get(download_url, timeout=90000)
    if not response.ok:
        raise RuntimeError(f"Error descargando justificante (HTTP {response.status}).")
    pdf_bytes = await response.body()
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
    await page.wait_for_timeout(2000)
    await _click_firmar(page, config)
    await _aceptar_dialogo_edge_abrir_autofirma()
    await _launch_autofirma_cert_acceptor()
    await _aceptar_dialogo_edge_abrir_autofirma()
    await page.wait_for_timeout(2000)
    await _click_signar_tots_documents(page, config)
    await _aceptar_dialogo_edge_abrir_autofirma()
    await _aceptar_certificado_windows()
    await _verificar_firma_realizada(page, config)
    justificante_path = await _descargar_justificante_instancia(page, payload)
    logger.info("ayunta_palma: Justificante guardado en: %s", justificante_path)
    return page
