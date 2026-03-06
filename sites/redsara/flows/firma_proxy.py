"""
sites/redsara/flows/firma_proxy.py
===================================
LÃƒÆ’Ã‚Â³gica de espera y coordinaciÃƒÆ’Ã‚Â³n con autofirma_proxy.py para el flujo
de firma de Redsara en Docker/headless.

Este mÃƒÆ’Ã‚Â³dulo REEMPLAZA la lÃƒÆ’Ã‚Â³gica de _sign_with_retry_and_download en
firma_programatica.py de Redsara. El resto del flujo (pasos 1-3, adjuntos,
checkTerms, selecciÃƒÆ’Ã‚Â³n de firma con certificado) no cambia.

Diferencia clave respecto a Palma:
  - Palma: inyecta firma vÃƒÆ’Ã‚Â­a callback JS (procesarFirma)
  - Redsara: AutoScript abre WSS a 127.0.0.1:PORT ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ necesita proxy WS real
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from playwright.async_api import Page
from core.worker_execution.utils import extract_expediente_number, sanitize_filename_component

# ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ConfiguraciÃƒÆ’Ã‚Â³n ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except Exception:
        return default


async def _download_with_retries(
    page: Page,
    download_fn,
    artifact_path: Path,
    *,
    retries: int,
    wait_ms: int,
) -> Path:
    last_exc: Exception | None = None
    total = max(1, int(retries))
    first_delay_ms = _env_int("XALOC_REDSARA_DOWNLOAD_FIRST_DELAY_MS", 900)
    if first_delay_ms > 0:
        await page.wait_for_timeout(first_delay_ms)
    for n in range(1, total + 1):
        try:
            return await download_fn(page, artifact_path)
        except Exception as exc:
            last_exc = exc
            print(f"[REDSARA] Descarga justificante fallÃƒÂ³ ({n}/{total}): {exc}")
            if n < total:
                await page.wait_for_timeout(wait_ms)
    raise RuntimeError(f"REDSARA: fallo descargando justificante tras {total} intentos: {last_exc}")


PROXY_READY_FILE = Path(os.getenv("XALOC_AFIRMA_PROXY_READY", "/tmp/xaloc_afirma_proxy.ready"))
PROXY_PID_FILE   = Path(os.getenv("XALOC_AFIRMA_PROXY_PID",   "/tmp/xaloc_afirma_proxy.pid"))
LATEST_URI_FILE  = Path(os.getenv("XALOC_AFIRMA_URI_LATEST",  "/tmp/xaloc_afirma_uri.latest"))
_AFIRMA_URI_RE   = re.compile(r"^(?:afirma|xalocafirma)://", re.IGNORECASE)

# Regex para capturar puertos del console.log de AutoScript:
#   "Tratamos de conectar con el cliente a traves de WebSockets en los puertos 51581,54484,57116"
_CONSOLE_PORTS_RE = re.compile(
    r"Tratamos de conectar.*?puertos?\s+([\d,\s]+)",
    re.IGNORECASE,
)

# Ubicaciones candidatas del proxy script (en orden de preferencia).
# La primera que exista se usa. Incluye la ruta con volumen montado.
_PROXY_SCRIPT_CANDIDATES = [
    os.getenv("XALOC_AFIRMA_PROXY_SCRIPT", ""),          # override explÃƒÆ’Ã‚Â­cito
    "/app/autofirma_proxy.py",                             # Dockerfile COPY (sin volumen)
    "/app/infra/docker/autofirma_proxy.py",                # repo montado como volumen ../../:/app
    "/opt/venv/autofirma_proxy.py",                        # fallback raro
]

# Python bins candidatos
_PYTHON_BIN_CANDIDATES = [
    os.getenv("XALOC_PYTHON_BIN", ""),
    "/opt/venv/bin/python3",
    "/usr/bin/python3",
    "python3",
]

_POLICY_PATHS = [
    "/etc/chromium/policies/managed/xaloc-afirma-policy.json",
    "/etc/opt/chrome/policies/managed/xaloc-afirma-policy.json",
    "/etc/opt/chrome_for_testing/policies/managed/xaloc-afirma-policy.json",
    "/etc/opt/edge/policies/managed/xaloc-afirma-policy.json",
]


def _justificante_filename(data: object) -> str:
    payload = dict(getattr(data, "payload", None) or {})
    expediente = sanitize_filename_component(extract_expediente_number(payload))
    if expediente == "UNKNOWN":
        expediente = sanitize_filename_component(str(payload.get("idRecurso") or "UNKNOWN"))
    return f"JUSTIFICANTE - {expediente}.pdf"


def _resolve_non_overwrite_path(path: Path) -> Path:
    if not path.exists():
        return path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = path.with_name(f"{path.stem} {ts}{path.suffix}")
    if not candidate.exists():
        return candidate
    for idx in range(1, 1000):
        alt = path.with_name(f"{path.stem} {ts}_{idx}{path.suffix}")
        if not alt.exists():
            return alt
    return path.with_name(f"{path.stem} {datetime.now().timestamp():.0f}{path.suffix}")

# JavaScript que intercepta la URI afirma:// directamente desde la pÃƒÆ’Ã‚Â¡gina.
# Captura todos los vectores: .click(), dispatchEvent, window.open,
# location.replace/assign y MutationObserver.
# El argumento es el nombre de la funciÃƒÆ’Ã‚Â³n expuesta por Playwright (expose_function).
_JS_AFIRMA_HOOK = r"""
(function(callbackName) {
    if (window.__xaloc_afirma_hooked) return;
    window.__xaloc_afirma_hooked = true;

    var isAfirma = function(s) {
        return s && /^(afirma|xalocafirma):\/\//i.test(String(s));
    };
    var capture = function(uri) {
        try { window[callbackName](String(uri)); } catch(e) {}
    };

    // 1. HTMLElement.prototype.click ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â cubre la mayorÃƒÆ’Ã‚Â­a de implementaciones AutoScript
    var origClick = HTMLElement.prototype.click;
    HTMLElement.prototype.click = function() {
        var href = this.getAttribute ? this.getAttribute('href') : null;
        if (!href && this.href) href = this.href;
        if (isAfirma(href)) capture(href);
        return origClick.apply(this, arguments);
    };

    // 2. dispatchEvent ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â cubre AutoScript que usa new MouseEvent('click')
    var origDispatch = EventTarget.prototype.dispatchEvent;
    EventTarget.prototype.dispatchEvent = function(evt) {
        if (evt && evt.type === 'click') {
            var href = this.getAttribute ? this.getAttribute('href') : null;
            if (!href && this.href) href = this.href;
            if (isAfirma(href)) capture(href);
        }
        return origDispatch.apply(this, arguments);
    };

    // 3. Captura global de clicks en el documento (useCapture=true)
    document.addEventListener('click', function(e) {
        var el = e.target;
        while (el) {
            var href = el.getAttribute ? el.getAttribute('href') : null;
            if (!href && el.href) href = el.href;
            if (isAfirma(href)) { capture(href); break; }
            el = el.parentElement;
        }
    }, true);

    // 4. window.open
    var origOpen = window.open;
    window.open = function(url) {
        if (isAfirma(url)) capture(url);
        return origOpen ? origOpen.apply(window, arguments) : null;
    };

    // 5. location.replace y location.assign
    try {
        var origReplace = location.replace.bind(location);
        location.replace = function(url) {
            if (isAfirma(url)) capture(url);
            return origReplace(url);
        };
    } catch(e) {}
    try {
        var origAssign = location.assign.bind(location);
        location.assign = function(url) {
            if (isAfirma(url)) capture(url);
            return origAssign(url);
        };
    } catch(e) {}

    // 6. location.href = "afirma://..." ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â asignaciÃƒÆ’Ã‚Â³n directa (patrÃƒÆ’Ã‚Â³n comÃƒÆ’Ã‚Âºn en AutoScript)
    try {
        var origHrefDesc = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
        if (origHrefDesc && origHrefDesc.set) {
            Object.defineProperty(Location.prototype, 'href', {
                get: function() { return origHrefDesc.get.call(this); },
                set: function(url) {
                    if (isAfirma(url)) capture(url);
                    origHrefDesc.set.call(this, url);
                },
                configurable: true,
            });
        }
    } catch(e) {}

    // 7. MutationObserver ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â detecta <a href="afirma://..."> e <iframe src="afirma://...">
    var observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
            if (!m.addedNodes) return;
            m.addedNodes.forEach(function(node) {
                if (!node.querySelectorAll) return;
                node.querySelectorAll('a[href^="afirma://"], a[href^="xalocafirma://"]')
                    .forEach(function(a) { capture(a.href); });
                node.querySelectorAll('iframe[src^="afirma://"], iframe[src^="xalocafirma://"]')
                    .forEach(function(f) { capture(f.src); });
                if (node.href && isAfirma(node.href)) capture(node.href);
                if (node.src && isAfirma(node.src)) capture(node.src);
            });
        });
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
})
"""

_JS_HOOK_FN_NAME = "__xaloc_captureAfirmaURI"

# Tap ligero para depurar WS de AutoFirma en el flujo automatico.
# Registra SOLO metadata y prefijos para no volcar payloads completos.
_JS_WS_TAP = r"""
(function() {
    if (window.__xaloc_ws_tap_installed) return;
    window.__xaloc_ws_tap_installed = true;
    var NativeWS = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        var ws = protocols ? new NativeWS(url, protocols) : new NativeWS(url);
        var wsUrl = String(url || "");
        try { console.log("[XALOC-WS-TAP] open " + wsUrl); } catch(e) {}

        var _send = ws.send.bind(ws);
        ws.send = function(data) {
            var txt = (data instanceof ArrayBuffer) ? ("[ArrayBuffer " + data.byteLength + "]") : String(data || "");
            var preview = txt.slice(0, 220).replace(/\s+/g, " ");
            try { console.log("[XALOC-WS-TAP] >> len=" + txt.length + " url=" + wsUrl + " data=" + preview); } catch(e) {}
            return _send(data);
        };

        ws.addEventListener("message", function(ev) {
            var txt = (ev.data instanceof ArrayBuffer) ? ("[ArrayBuffer " + ev.data.byteLength + "]") : String(ev.data || "");
            var preview = txt.slice(0, 220).replace(/\s+/g, " ");
            try { console.log("[XALOC-WS-TAP] << len=" + txt.length + " url=" + wsUrl + " data=" + preview); } catch(e) {}
        });
        ws.addEventListener("error", function() {
            try { console.log("[XALOC-WS-TAP] !! error url=" + wsUrl); } catch(e) {}
        });
        ws.addEventListener("close", function(ev) {
            try { console.log("[XALOC-WS-TAP] close url=" + wsUrl + " code=" + ev.code + " reason=" + (ev.reason || "")); } catch(e) {}
        });
        return ws;
    };
    window.WebSocket.prototype = NativeWS.prototype;
})();
"""


async def _setup_uri_capture(page: Page, state: dict) -> None:
    """
    Instala todos los mecanismos de captura de URI afirma://:
      1. JS hook (prototype patches) via page.evaluate
      2. Listener de console.log de AutoScript (lÃƒÆ’Ã‚Â­nea "Tratamos de conectar... puertos X,Y,Z")
      3. expose_function para callback Python desde JS hook

    state["uri"] se actualizarÃƒÆ’Ã‚Â¡ en cuanto cualquiera de los tres capture la URI.
    Seguro llamarlo varias veces (expose_function lanza si ya estÃƒÆ’Ã‚Â¡ registrada).
    """
    async def _on_uri(uri: str) -> None:
        if uri and _AFIRMA_URI_RE.match(uri):
            if not state.get("uri"):
                state["uri"] = uri
                try:
                    LATEST_URI_FILE.write_text(uri, encoding="utf-8")
                except Exception:
                    pass
                print(f"[REDSARA-URI] URI interceptada via JS hook: {uri[:90]}...")

    try:
        await page.expose_function(_JS_HOOK_FN_NAME, _on_uri)
    except Exception:
        pass  # Ya registrada en intento anterior ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â callback sigue activo

    # Inyectar/reinstalar el hook en la pÃƒÆ’Ã‚Â¡gina actual (idempotente por el guard)
    try:
        await page.evaluate(f"({_JS_AFIRMA_HOOK})('{_JS_HOOK_FN_NAME}')")
    except Exception as exc:
        print(f"[REDSARA-URI] Error inyectando JS hook: {exc}")
    try:
        await page.evaluate(_JS_WS_TAP)
    except Exception as exc:
        print(f"[REDSARA-URI] Error inyectando WS tap: {exc}")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Listener de console.log ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    # AutoScript imprime: "Tratamos de conectar con el cliente a traves de
    # WebSockets en los puertos 51581,54484,57116"
    # Capturamos esto como URI sintÃƒÆ’Ã‚Â©tica con los puertos.
    def _on_console(msg) -> None:
        try:
            txt = msg.text or ""
            if txt.startswith("[XALOC-WS-TAP]"):
                print(txt)
            if state.get("uri"):
                return  # Ya capturada
            m = _CONSOLE_PORTS_RE.search(txt)
            if not m:
                return
            ports_str = re.sub(r"\s+", "", m.group(1)).strip().rstrip(",")
            if not ports_str:
                return
            synthetic_uri = f"afirma://websocket?ports={ports_str}"
            state["uri"] = synthetic_uri
            try:
                LATEST_URI_FILE.write_text(synthetic_uri, encoding="utf-8")
            except Exception:
                pass
            print(f"[REDSARA-URI] URI extraÃƒÆ’Ã‚Â­da de console.log: {synthetic_uri}")
        except Exception as exc:
            print(f"[REDSARA-URI] Error en console listener: {exc}")

    # Registrar listener ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â si ya habÃƒÆ’Ã‚Â­a uno de intento anterior, no pasa nada
    # (duplicados simplemente se llaman dos veces, ambos comprueban state["uri"])
    page.on("console", _on_console)


# ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ DiagnÃƒÆ’Ã‚Â³stico ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

def dump_sign_diagnostics(label: str = "") -> None:
    """
    Vuelca al log todo el estado relevante del sistema de firma.
    Llamar antes y despuÃƒÆ’Ã‚Â©s de cada intento de firma para diagnÃƒÆ’Ã‚Â³stico.
    """
    sep = "=" * 64
    tag = f"[REDSARA-DIAG{' ' + label if label else ''}]"
    print(f"\n{sep}")
    print(f"{tag} DIAGNÃƒÆ’Ã¢â‚¬Å“STICO SISTEMA DE FIRMA REDSARA")
    print(sep)

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 1. Archivos crÃƒÆ’Ã‚Â­ticos ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    handler_path = Path("/usr/local/bin/afirma-handler.sh")

    found_script = _find_proxy_script()
    if found_script:
        size = Path(found_script).stat().st_size
        print(f"{tag} autofirma_proxy.py: ENCONTRADO en {found_script} ({size}B)")
    else:
        print(f"{tag} autofirma_proxy.py: *** NO ENCONTRADO en ninguna ruta candidata ***")
        for c in _PROXY_SCRIPT_CANDIDATES:
            if c:
                print(f"{tag}   buscado: {c} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ existe={Path(c).exists()}")

    if handler_path.exists():
        content = handler_path.read_text(errors="replace")
        lines = content.splitlines()
        has_proxy = "autofirma_proxy" in content
        has_nohup = "nohup" in content
        print(f"{tag} afirma-handler.sh: {len(lines)} lÃƒÆ’Ã‚Â­neas, proxy={has_proxy}, nohup={has_nohup}")
        if not has_proxy:
            print(f"{tag}   *** VERSIÃƒÆ’Ã¢â‚¬Å“N ANTIGUA del handler ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â necesita rebuild ***")
    else:
        print(f"{tag} afirma-handler.sh: NO ENCONTRADO en {handler_path}")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 2. XDG mime type ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    for scheme in ("afirma", "xalocafirma"):
        try:
            r = subprocess.run(
                ["xdg-mime", "query", "default", f"x-scheme-handler/{scheme}"],
                capture_output=True, text=True, timeout=5,
            )
            val = r.stdout.strip()
            print(f"{tag} xdg-mime x-scheme-handler/{scheme}: {val!r}")
            if not val:
                print(f"{tag}   *** NO REGISTRADO ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â handler XDG ausente ***")
        except Exception as exc:
            print(f"{tag} xdg-mime {scheme}: ERROR ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {exc}")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 3. Chromium policies ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    policy_found = False
    for p in _POLICY_PATHS:
        pf = Path(p)
        if pf.exists():
            policy_found = True
            try:
                content = pf.read_text(encoding="utf-8")
                print(f"{tag} Policy {p}:")
                for line in content.splitlines():
                    print(f"{tag}   {line}")
            except Exception as exc:
                print(f"{tag} Policy {p}: ERROR leyendo ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {exc}")
            break
    if not policy_found:
        print(f"{tag} AutoLaunchProtocolsFromOrigins policy: *** NO ENCONTRADA ***")
        print(f"{tag}   ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Chromium mostrarÃƒÆ’Ã‚Â¡ diÃƒÆ’Ã‚Â¡logo de confirmaciÃƒÆ’Ã‚Â³n para afirma://")
        print(f"{tag}   ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ El handler NO se invocarÃƒÆ’Ã‚Â¡ automÃƒÆ’Ã‚Â¡ticamente")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 4. Certificado PFX ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    cert_path = os.getenv("PLAYWRIGHT_CERT_PATH", "/data/certificates/certificate.pfx")
    cert_pass = "***" if os.getenv("PLAYWRIGHT_CERT_PASSWORD") else "(vacÃƒÆ’Ã‚Â­o)"
    pf = Path(cert_path)
    print(f"{tag} PLAYWRIGHT_CERT_PATH: {cert_path} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ existe={pf.exists()}" + (f" ({pf.stat().st_size}B)" if pf.exists() else ""))
    print(f"{tag} PLAYWRIGHT_CERT_PASSWORD: {cert_pass}")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 5. websockets ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    try:
        import websockets
        print(f"{tag} websockets: {websockets.__version__} ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“")
    except ImportError:
        print(f"{tag} websockets: *** NO INSTALADO *** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â pip install websockets")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 6. autofirma CLI ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    try:
        r = subprocess.run(["autofirma", "version"], capture_output=True, text=True, timeout=10)
        ver = (r.stdout + r.stderr).strip().splitlines()
        print(f"{tag} autofirma CLI: {ver[0] if ver else '(sin salida)'}")
    except FileNotFoundError:
        print(f"{tag} autofirma CLI: *** NO ENCONTRADO en PATH ***")
    except Exception as exc:
        print(f"{tag} autofirma CLI: ERROR ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {exc}")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 7. Estado de archivos /tmp ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    print(f"{tag} --- archivos /tmp ---")
    for label_f, path in [
        ("uri.latest", LATEST_URI_FILE),
        ("proxy.ready", PROXY_READY_FILE),
        ("proxy.pid",   PROXY_PID_FILE),
    ]:
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8").strip()
                print(f"{tag} {label_f}: {content[:120]!r}")
            except Exception as exc:
                print(f"{tag} {label_f}: EXISTS pero error al leer ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {exc}")
        else:
            print(f"{tag} {label_f}: no existe")

    proxy_log = Path("/tmp/xaloc_afirma_proxy.log")
    if proxy_log.exists():
        try:
            lines = proxy_log.read_text(encoding="utf-8", errors="replace").splitlines()
            print(f"{tag} proxy.log ({len(lines)} lÃƒÆ’Ã‚Â­neas, ÃƒÆ’Ã‚Âºltimas 20):")
            for ln in lines[-20:]:
                print(f"{tag}   {ln}")
        except Exception as exc:
            print(f"{tag} proxy.log: error ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {exc}")
    else:
        print(f"{tag} proxy.log: no existe (proxy nunca arrancÃƒÆ’Ã‚Â³)")

    uri_log = Path("/tmp/xaloc_afirma_uri.log")
    if uri_log.exists():
        try:
            lines = uri_log.read_text(encoding="utf-8", errors="replace").splitlines()
            print(f"{tag} uri.log ({len(lines)} entradas, ÃƒÆ’Ã‚Âºltimas 5):")
            for ln in lines[-5:]:
                print(f"{tag}   {ln}")
        except Exception as exc:
            print(f"{tag} uri.log: error ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {exc}")
    else:
        print(f"{tag} uri.log: no existe (handler nunca invocado)")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 8. Variables de entorno relevantes ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    print(f"{tag} --- env vars ---")
    for var in [
        "XALOC_AFIRMA_PROXY_SCRIPT",
        "XALOC_AFIRMA_URI_LATEST",
        "XALOC_AFIRMA_PROXY_READY",
        "XALOC_AFIRMA_PROXY_PID",
        "XALOC_AUTOFIRMA_ALLOWED_ORIGINS",
        "XALOC_AUTOFIRMA_PROTOCOLS",
        "XALOC_PYTHON_BIN",
        "DISPLAY",
        "HOME",
    ]:
        val = os.getenv(var)
        print(f"{tag}   {var}={val!r}")

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 9. Python bin ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    python_bin = os.getenv("XALOC_PYTHON_BIN", "/opt/venv/bin/python3")
    pf = Path(python_bin)
    print(f"{tag} python bin: {python_bin} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ existe={pf.exists()}")

    print(sep + "\n")


# ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Esperar proxy listo ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

async def wait_for_proxy_ready(
    timeout_ms: int = 20000,
    uri_state: dict | None = None,
) -> list[int]:
    """
    Espera a que autofirma_proxy.py escriba el archivo .ready con los puertos.
    Devuelve la lista de puertos en los que el proxy estÃƒÆ’Ã‚Â¡ escuchando.

    Si uri_state se proporciona, tambiÃƒÆ’Ã‚Â©n lanza el proxy desde Python si
    la URI aparece durante la espera (captura tardÃƒÆ’Ã‚Â­a del XDG handler o console).
    """
    deadline = time.monotonic() + timeout_ms / 1000
    start_ts = time.monotonic()
    last_log = time.monotonic()
    poll_n = 0
    proxy_launched_here = False
    launch_grace_s = max(0.0, _env_int("XALOC_AFIRMA_PROXY_LAUNCH_GRACE_MS", 1200) / 1000.0)

    while time.monotonic() < deadline:
        poll_n += 1
        try:
            if PROXY_READY_FILE.exists():
                content = PROXY_READY_FILE.read_text(encoding="utf-8").strip()
                ports = [int(p) for p in content.split(",") if p.strip().isdigit()]
                if ports:
                    print(f"[REDSARA-PROXY] Proxy listo en puertos {ports} (poll #{poll_n})")
                    return ports
        except Exception:
            pass

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Captura tardÃƒÆ’Ã‚Â­a: URI apareciÃƒÆ’Ã‚Â³ durante la espera ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        # (XDG handler escribiÃƒÆ’Ã‚Â³ LATEST_URI_FILE, o console listener lo capturÃƒÆ’Ã‚Â³)
        if (
            not proxy_launched_here
            and not _proxy_already_running()
            and (time.monotonic() - start_ts) >= launch_grace_s
        ):
            late_uri: str | None = None
            # Primero: uri_state (console listener o JS hook)
            if uri_state and uri_state.get("uri"):
                late_uri = uri_state["uri"]
            # Segundo: fichero escrito por XDG handler
            if not late_uri:
                try:
                    if LATEST_URI_FILE.exists():
                        candidate = LATEST_URI_FILE.read_text(encoding="utf-8").strip()
                        if candidate and _AFIRMA_URI_RE.match(candidate):
                            late_uri = candidate
                except Exception:
                    pass
            if late_uri:
                print(f"[REDSARA-PROXY] URI capturada tardÃƒÆ’Ã‚Â­amente durante espera: {late_uri[:80]}...")
                launched = _launch_proxy_from_python(late_uri)
                proxy_launched_here = launched

        now = time.monotonic()
        if now - last_log >= 3.0:
            elapsed = int(now - (deadline - timeout_ms / 1000))
            ready_exists = PROXY_READY_FILE.exists()
            pid_exists = PROXY_PID_FILE.exists()
            pid_val = ""
            if pid_exists:
                try:
                    pid_val = PROXY_PID_FILE.read_text().strip()
                except Exception:
                    pid_val = "?"
            print(
                f"[REDSARA-PROXY] Esperando proxy... {elapsed}s/{timeout_ms//1000}s"
                f" ready={ready_exists} pid={pid_val or 'no-pid'}"
            )
            # Si el proxy arrancÃƒÆ’Ã‚Â³ pero no estÃƒÆ’Ã‚Â¡ listo, mostrar el log
            proxy_log = Path("/tmp/xaloc_afirma_proxy.log")
            if proxy_log.exists():
                try:
                    lines = proxy_log.read_text(errors="replace").splitlines()
                    if lines:
                        print(f"[REDSARA-PROXY] proxy.log ÃƒÆ’Ã‚Âºltimas lÃƒÆ’Ã‚Â­neas:")
                        for ln in lines[-5:]:
                            print(f"[REDSARA-PROXY]   {ln}")
                except Exception:
                    pass
            last_log = now

        await asyncio.sleep(0.2)

    # Timeout ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â dump diagnÃƒÆ’Ã‚Â³stico
    print("[REDSARA-PROXY] TIMEOUT esperando proxy. Volcando diagnÃƒÆ’Ã‚Â³stico:")
    dump_sign_diagnostics("PROXY-TIMEOUT")
    raise RuntimeError(
        f"autofirma_proxy no se iniciÃƒÆ’Ã‚Â³ en {timeout_ms}ms. "
        f"Verifica que afirma-handler.sh lanza autofirma_proxy.py y que "
        f"'websockets' estÃƒÆ’Ã‚Â¡ instalado en {os.getenv('XALOC_PYTHON_BIN', '/opt/venv/bin/python3')}."
    )


async def wait_for_uri_captured(timeout_ms: int = 15000) -> str | None:
    """
    Espera a que el handler capture la URI afirma:// en .latest.
    Devuelve la URI o None si no aparece en tiempo.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    last_log = time.monotonic()
    poll_n = 0

    while time.monotonic() < deadline:
        poll_n += 1
        try:
            if LATEST_URI_FILE.exists():
                uri = LATEST_URI_FILE.read_text(encoding="utf-8").strip()
                if uri and _AFIRMA_URI_RE.match(uri):
                    print(f"[REDSARA-URI] URI capturada en poll #{poll_n}: {uri[:80]}...")
                    return uri
        except Exception:
            pass

        now = time.monotonic()
        if now - last_log >= 2.0:
            elapsed = int(now - (deadline - timeout_ms / 1000))
            file_exists = LATEST_URI_FILE.exists()
            file_content = ""
            if file_exists:
                try:
                    file_content = LATEST_URI_FILE.read_text().strip()[:80]
                except Exception:
                    file_content = "ERROR-LEYENDO"
            print(
                f"[REDSARA-URI] Esperando URI afirma:// {elapsed}s/{timeout_ms//1000}s"
                f" file={file_exists} contenido={file_content!r}"
            )
            last_log = now

        await asyncio.sleep(0.25)

    # Timeout ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â log detallado
    file_exists = LATEST_URI_FILE.exists()
    file_content = ""
    if file_exists:
        try:
            file_content = LATEST_URI_FILE.read_text().strip()
        except Exception:
            pass
    print(
        f"[REDSARA-URI] TIMEOUT: URI afirma:// no apareciÃƒÆ’Ã‚Â³ en {timeout_ms}ms. "
        f"file={file_exists} contenido={file_content[:100]!r}"
    )
    print("[REDSARA-URI] POSIBLES CAUSAS:")
    print("[REDSARA-URI]   1. AutoLaunchProtocolsFromOrigins no incluye el origen de Redsara")
    print("[REDSARA-URI]   2. afirma-handler.sh es versiÃƒÆ’Ã‚Â³n antigua (sin proxy) o no estÃƒÆ’Ã‚Â¡ registrado")
    print("[REDSARA-URI]   3. DISPLAY no configurado ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ xdg-open falla silenciosamente")

    uri_log = Path("/tmp/xaloc_afirma_uri.log")
    if uri_log.exists():
        try:
            lines = uri_log.read_text(errors="replace").splitlines()
            print(f"[REDSARA-URI] uri.log ({len(lines)} entradas):")
            for ln in lines[-5:]:
                print(f"[REDSARA-URI]   {ln}")
        except Exception:
            pass
    else:
        print("[REDSARA-URI] uri.log no existe ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ handler NUNCA fue invocado")

    return None


def _find_proxy_script() -> str | None:
    """Devuelve la primera ruta vÃƒÆ’Ã‚Â¡lida del proxy script, o None si no se encuentra."""
    for candidate in _PROXY_SCRIPT_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _find_python_bin() -> str:
    """Devuelve el primer Python bin utilizable."""
    for candidate in _PYTHON_BIN_CANDIDATES:
        if not candidate:
            continue
        if Path(candidate).exists():
            return candidate
        if candidate == "python3":
            return candidate  # confiar en PATH
    return "python3"


def _launch_proxy_from_python(uri: str) -> bool:
    """
    Lanza autofirma_proxy.py en background directamente desde Python.

    Esto permite funcionar incluso con el handler XDG antiguo (que captura
    la URI pero no lanza el proxy). El orchestrador Python toma el relevo.

    Devuelve True si se lanzÃƒÆ’Ã‚Â³, False si el script no existe.
    """
    proxy_script = _find_proxy_script()
    if not proxy_script:
        candidates_str = ", ".join(c for c in _PROXY_SCRIPT_CANDIDATES if c)
        print(
            f"[REDSARA-PROXY] No se encontrÃƒÆ’Ã‚Â³ autofirma_proxy.py en ninguna ruta. "
            f"Buscado en: {candidates_str}"
        )
        return False

    python_bin = _find_python_bin()
    proxy_log = Path("/tmp/xaloc_afirma_proxy.log")

    print(f"[REDSARA-PROXY] Lanzando proxy directamente: {python_bin} {proxy_script}")
    print(f"[REDSARA-PROXY] URI: {uri[:100]}...")

    try:
        with open(proxy_log, "a") as log_fh:
            proc = subprocess.Popen(
                [python_bin, proxy_script, uri],
                stdout=log_fh,
                stderr=log_fh,
                close_fds=True,
            )
        print(f"[REDSARA-PROXY] Proxy lanzado (PID={proc.pid}). Log: {proxy_log}")
        return True
    except Exception as exc:
        print(f"[REDSARA-PROXY] ERROR lanzando proxy: {exc}")
        return False


def _proxy_already_running() -> bool:
    """Devuelve True si hay un proxy vivo (pid file + proceso existe)."""
    try:
        if PROXY_PID_FILE.exists():
            pid = int(PROXY_PID_FILE.read_text().strip())
            os.kill(pid, 0)  # comprueba si el proceso existe
            return True
    except (ProcessLookupError, ValueError, OSError):
        pass
    return False


def reset_proxy_state() -> None:
    """Limpia archivos de estado del proxy antes de un nuevo intento."""
    for f in [PROXY_READY_FILE, LATEST_URI_FILE]:
        try:
            if f.exists():
                print(f"[REDSARA-PROXY] Limpiando {f}")
            f.unlink(missing_ok=True)
        except Exception:
            pass
    # Matar proxy anterior si sigue vivo
    try:
        if PROXY_PID_FILE.exists():
            pid = int(PROXY_PID_FILE.read_text().strip())
            try:
                os.kill(pid, 15)  # SIGTERM
                print(f"[REDSARA-PROXY] Proxy anterior (PID={pid}) terminado.")
            except ProcessLookupError:
                pass
            PROXY_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def stop_proxy() -> None:
    """Para el proxy si estÃƒÆ’Ã‚Â¡ corriendo."""
    try:
        if PROXY_PID_FILE.exists():
            pid = int(PROXY_PID_FILE.read_text().strip())
            os.kill(pid, 15)
            print(f"[REDSARA-PROXY] Proxy (PID={pid}) detenido.")
            PROXY_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Resultado de firma ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

async def wait_sign_result_proxy(page: Page, timeout_ms: int) -> str:
    """
    Espera el resultado de la firma en la pÃƒÆ’Ã‚Â¡gina de Redsara.

    Estados posibles:
      'success'              ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â firma OK, navegÃƒÆ’Ã‚Â³ a pÃƒÆ’Ã‚Â¡gina de detalle
      'unmarshalling_timeout'ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â servidor REG timeout (reintentar)
      'autofirma_not_found'  ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â proxy no arrancÃƒÆ’Ã‚Â³ / WebSocket rechazado
      'other_error'          ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â otro error en modal
    """
    result_handle = await page.wait_for_function(
        """() => {
            const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase()
            const step4 = !!document.querySelector('app-create-registry-step4')
            const detail = !!document.querySelector('app-detail-registry-view')
                        || norm(location.href).includes('/detalle-registro/')

            if (detail || !step4) return 'success'

            const modal = Array.from(document.querySelectorAll('dnt-modal'))
                .find(m => {
                    const vis = m.getAttribute('visible')
                    return vis !== null && vis !== 'false'
                })
            if (!modal) return null

            const txt = norm(modal.textContent || '')
            if (txt.includes('unmarshalling') || txt.includes('read timed out') || txt.includes('timed out'))
                return 'unmarshalling_timeout'
            if (txt.includes('applicationnotfoundexception') || txt.includes('no se ha podido conectar'))
                return 'autofirma_not_found'
            // Devolver el texto del modal para diagnostico
            return 'other_error:' + (modal.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 300)
        }""",
        timeout=timeout_ms,
    )
    try:
        result = await result_handle.json_value()
    finally:
        try:
            await result_handle.dispose()
        except Exception:
            pass

    if not isinstance(result, str):
        raise RuntimeError(f"REDSARA: resultado de firma invalido: {result!r}")
    if result.startswith("other_error:"):
        modal_text = result[len("other_error:"):]
        print(f"[REDSARA] Modal error texto: {modal_text!r}")
        return result
    return result


async def close_sign_error_modal(page: Page) -> None:
    await page.evaluate(
        """() => {
            const norm = s => String(s||'').replace(/\\s+/g,' ').trim().toLowerCase()
            const modal = Array.from(document.querySelectorAll('dnt-modal'))
                .find(m => {
                    const vis = m.getAttribute('visible')
                    return vis !== null && vis !== 'false'
                })
            if (!modal) return
            for (const host of modal.querySelectorAll('dnt-button')) {
                const txt = norm(host.textContent || host.getAttribute('title-text') || '')
                if (!['cerrar','aceptar','entendido','ok'].some(w => txt.includes(w))) continue
                const btn = host.shadowRoot?.querySelector('button')
                if (btn) { btn.click(); return }
                host.click(); return
            }
        }"""
    )


# ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Click en botÃƒÆ’Ã‚Â³n principal de firma ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

async def click_main_sign_button(page: Page) -> None:
    """Pulsa el botÃƒÆ’Ã‚Â³n principal 'Firmar con certificado electrÃƒÆ’Ã‚Â³nico' (shadow DOM)."""
    clicked = False
    for _ in range(40):  # ~8s
        clicked = await page.evaluate(
            """() => {
                const split = document.querySelector('app-create-registry-step4 dnt-split-button#btnSignature')
                if (!split?.shadowRoot) return false
                const mainHost =
                    split.shadowRoot.querySelector('dnt-button.dnt-split-button__main-button')
                    || split.shadowRoot.querySelector('dnt-button[title-text]')
                    || split.shadowRoot.querySelector('dnt-button')
                if (!mainHost) return false
                const btn =
                    mainHost.shadowRoot?.querySelector('button[data-name="DntButton"]')
                    || mainHost.shadowRoot?.querySelector('button[part="dnt-button"]')
                    || mainHost.shadowRoot?.querySelector('button')
                if (!btn) return false
                const hostState = mainHost.getAttribute('is-disabled')
                const disabled = hostState === 'true' || hostState === ''
                    || mainHost.getAttribute('aria-disabled') === 'true'
                    || btn.disabled
                    || btn.getAttribute('aria-disabled') === 'true'
                    || btn.classList.contains('is-disabled')
                if (disabled) return false
                btn.click()
                return true
            }"""
        )
        if clicked:
            break
        await page.wait_for_timeout(200)

    if not clicked:
        raise RuntimeError("REDSARA: no se pudo pulsar 'Firmar con certificado electrÃƒÆ’Ã‚Â³nico'.")
    print("[REDSARA] BotÃƒÆ’Ã‚Â³n 'Firmar con certificado electrÃƒÆ’Ã‚Â³nico' pulsado.")


# ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Flujo principal de firma con proxy ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

async def sign_with_proxy_and_download(
    page: Page,
    data,  # RedsaraTarget
    download_fn,  # callable async (page, save_path) -> Path
    resolve_path_fn,  # callable (data, file_name) -> Path | None
) -> dict:
    """
    Flujo completo de firma para Redsara usando autofirma_proxy.py.

    Sustituye a _sign_with_retry_and_download en firma_programatica.py.
    Los parÃƒÆ’Ã‚Â¡metros download_fn y resolve_path_fn son los mismos helpers
    (_download_justificante, _resolve_client_justificante_path) ya existentes.
    """
    retries    = _env_int("XALOC_REDSARA_SIGN_RETRIES",    3)
    timeout_ms = _env_int("XALOC_REDSARA_SIGN_TIMEOUT_MS", 120_000)
    proxy_wait = _env_int("XALOC_AFIRMA_PROXY_READY_WAIT_MS", 20_000)
    uri_wait   = _env_int("XALOC_REDSARA_URI_TRIGGER_WAIT_MS", 15_000)
    dl_retries = _env_int("XALOC_REDSARA_DOWNLOAD_RETRIES", 3)
    dl_wait_ms = _env_int("XALOC_REDSARA_DOWNLOAD_RETRY_WAIT_MS", 1500)

    # DiagnÃƒÆ’Ã‚Â³stico inicial antes de empezar
    dump_sign_diagnostics("PRE-SIGN")

    # Estado compartido entre intentos: el hook JS actualiza state["uri"]
    # aunque no podamos re-registrar expose_function en reintentos.
    uri_state: dict = {"uri": None}

    for attempt in range(1, retries + 1):
        print(f"[REDSARA] Firma intento {attempt}/{retries}")

        # Limpiar estado previo
        reset_proxy_state()
        uri_state["uri"] = None  # reset para este intento

        # Instalar hook JS ANTES de clickar (captura la URI directamente del browser)
        await _setup_uri_capture(page, uri_state)

        # Pulsar firmar ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ AutoScript genera afirma:// URI ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ hook JS la captura
        await click_main_sign_button(page)

        # Esperar la URI via JS hook (polling rÃƒÆ’Ã‚Â¡pido)
        uri: str | None = None
        deadline = time.monotonic() + uri_wait / 1000
        poll_logged = False
        while time.monotonic() < deadline:
            if uri_state["uri"]:
                uri = uri_state["uri"]
                break
            # Fallback: tambiÃƒÆ’Ã‚Â©n comprobar el fichero (si handler nuevo escribe)
            try:
                if LATEST_URI_FILE.exists():
                    file_uri = LATEST_URI_FILE.read_text(encoding="utf-8").strip()
                    if file_uri and _AFIRMA_URI_RE.match(file_uri):
                        uri = file_uri
                        print(f"[REDSARA-URI] URI capturada via fichero: {uri[:80]}...")
                        break
            except Exception:
                pass
            if not poll_logged:
                print(f"[REDSARA-URI] Esperando URI afirma:// (JS hook activo + fichero)...")
                poll_logged = True
            await asyncio.sleep(0.1)

        if uri:
            print(f"[REDSARA] URI afirma:// capturada en {attempt}Ãƒâ€šÃ‚Â° intento: {uri[:90]}...")
        else:
            print(f"[REDSARA] AVISO: URI no capturada en {uri_wait}ms.")
            dump_sign_diagnostics(f"NO-URI-intento{attempt}")

        # El fallback de lanzamiento directo se gestiona dentro de wait_for_proxy_ready
        # con una gracia inicial para evitar doble-launch contra el handler XDG.

        # Esperar a que el proxy estÃƒÆ’Ã‚Â© listo (puertos abiertos)
        try:
            ports = await wait_for_proxy_ready(timeout_ms=proxy_wait, uri_state=uri_state)
            print(f"[REDSARA] Proxy listo en puertos: {ports}")
        except RuntimeError as exc:
            print(f"[REDSARA] ERROR proxy no listo: {exc}")
            dump_sign_diagnostics(f"PROXY-FAIL-intento{attempt}")
            if attempt < retries:
                await close_sign_error_modal(page)
                await page.wait_for_timeout(2000)
                continue
            raise

        # Esperar resultado (AutoScript conecta al proxy, firma, pÃƒÆ’Ã‚Â¡gina avanza)
        result = await wait_sign_result_proxy(page, timeout_ms=timeout_ms)
        print(f"[REDSARA] Resultado firma: {result}")

        if result == "success":
            # Esperar pÃƒÆ’Ã‚Â¡gina de detalle y descargar justificante
            import re as _re
            await page.wait_for_selector(
                "app-detail-registry-view dnt-button[title-text='Descargar justificante']",
                state="attached",
                timeout=30_000,
            )
            match = _re.search(r"detalle-registro/([a-f0-9-]+)", page.url or "", _re.IGNORECASE)
            registry_uuid = match.group(1) if match else None

            file_name   = _justificante_filename(data)
            artifact_path = Path("tmp") / "redsara" / "justificantes" / file_name

            downloaded = await _download_with_retries(page, download_fn, artifact_path, retries=dl_retries, wait_ms=dl_wait_ms)

            client_target = resolve_path_fn(data, file_name)
            client_saved  = None
            if client_target is not None:
                client_target = _resolve_non_overwrite_path(client_target)
                client_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(downloaded, client_target)
                client_saved = client_target

            stop_proxy()
            return {
                "redsara_signed":                   True,
                "redsara_registry_uuid":             registry_uuid,
                "redsara_justificante_artifact_path": str(downloaded),
                "redsara_justificante_client_path":  str(client_saved) if client_saved else None,
                "redsara_sign_attempts":             attempt,
                "redsara_sign_error_code":           None,
            }

        # Error recuperable
        await close_sign_error_modal(page)

        if result == "unmarshalling_timeout":
            print(f"[REDSARA] Unmarshalling timeout en intento {attempt}. Reintentando...")
            await page.wait_for_timeout(2000)
            continue

        if result == "autofirma_not_found":
            dump_sign_diagnostics(f"AUTOFIRMA-NOT-FOUND-intento{attempt}")
            raise RuntimeError(
                "REDSARA: AutoFirma proxy no conectÃƒÆ’Ã‚Â³ (autofirma_not_found). "
                "Verifica que autofirma_proxy.py estÃƒÆ’Ã‚Â¡ en /app/ y que 'websockets' "
                "estÃƒÆ’Ã‚Â¡ instalado en el venv."
            )

        if isinstance(result, str) and result.startswith("other_error:"):
            modal_text = result[len("other_error:"):].strip().lower()
            if "se ha firmado correctamente" in modal_text:
                print("[REDSARA] Modal de ÃƒÂ©xito detectado dentro de other_error. Continuando como firma exitosa.")
                result = "success"
            if "illegal base64 character 3f" in modal_text:
                # En algunos casos Redsara muestra modal de error pero termina
                # navegando al detalle igualmente tras cerrar el modal.
                print("[REDSARA] Detectado Illegal base64 3f. Verificando si el detalle aparece tras cerrar modal...")
                await page.wait_for_timeout(500)
                try:
                    await page.wait_for_selector(
                        "app-detail-registry-view dnt-button[title-text='Descargar justificante']",
                        state="attached",
                        timeout=8_000,
                    )
                    print("[REDSARA] Detalle detectado tras modal. Continuando como firma exitosa.")
                    result = "success"
                except Exception:
                    pass

        if result == "success":
            import re as _re
            await page.wait_for_selector(
                "app-detail-registry-view dnt-button[title-text='Descargar justificante']",
                state="attached",
                timeout=30_000,
            )
            match = _re.search(r"detalle-registro/([a-f0-9-]+)", page.url or "", _re.IGNORECASE)
            registry_uuid = match.group(1) if match else None

            file_name   = _justificante_filename(data)
            artifact_path = Path("tmp") / "redsara" / "justificantes" / file_name

            downloaded = await _download_with_retries(page, download_fn, artifact_path, retries=dl_retries, wait_ms=dl_wait_ms)

            client_target = resolve_path_fn(data, file_name)
            client_saved  = None
            if client_target is not None:
                client_target = _resolve_non_overwrite_path(client_target)
                client_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(downloaded, client_target)
                client_saved = client_target

            stop_proxy()
            return {
                "redsara_signed":                   True,
                "redsara_registry_uuid":             registry_uuid,
                "redsara_justificante_artifact_path": str(downloaded),
                "redsara_justificante_client_path":  str(client_saved) if client_saved else None,
                "redsara_sign_attempts":             attempt,
                "redsara_sign_error_code":           None,
            }

        dump_sign_diagnostics(f"OTHER-ERROR-intento{attempt}")
        raise RuntimeError(f"REDSARA: error de firma no recuperable: {result}")

    raise RuntimeError(f"REDSARA: firma fallida tras {retries} intentos.")


