from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Page

AFIRMA_URI_RE = re.compile(r"^(?:afirma|xalocafirma)://", re.IGNORECASE)
AUTOFIRMA_ALWAYS_ON = os.getenv("XALOC_AUTOFIRMA_ALWAYS_ON", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

AFIRMA_INTERCEPT_INIT_SCRIPT = """() => {
    if (window.__xaloc_afirma_interceptor_installed) return;
    window.__xaloc_afirma_interceptor_installed = true;

    window.__afirma_url = window.__afirma_url || null;
    window.__afirma_source = window.__afirma_source || null;

    const captureAfirma = (url, source) => {
        if (typeof url !== 'string') return false;
        if (!/^(afirma|xalocafirma):\\/\\//i.test(url)) return false;
        window.__afirma_url = url;
        window.__afirma_source = source || 'unknown';
        console.debug('[xaloc] afirma:// capturado via', window.__afirma_source, url.substring(0, 120));
        return true;
    };

    const _origOpen = window.open.bind(window);
    window.open = function(url, ...rest) {
        if (captureAfirma(url, 'window.open')) return null;
        return _origOpen(url, ...rest);
    };

    document.addEventListener('click', function(ev) {
        const el = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
        if (!el) return;
        const href = el.href || el.getAttribute('href') || '';
        if (!captureAfirma(href, 'anchor-click-capture')) return;
        ev.preventDefault();
        ev.stopPropagation();
    }, true);
}"""


def _extract_afirma_uri(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r"((?:afirma|xalocafirma)://[^'\"\\s]+)", text, re.IGNORECASE)
    return match.group(1) if match else None


async def prepare_autofirma_context(context: BrowserContext, logger: Optional[logging.Logger] = None) -> None:
    """
    Prepara captura de URI afirma:// en todo el contexto.
    Se debe llamar al inicio del tramite (antes del login).
    """
    log = logger or logging.getLogger("xaloc_automation.autofirma")
    if getattr(context, "_xaloc_afirma_capture_prepared", False):
        return

    await context.add_init_script(AFIRMA_INTERCEPT_INIT_SCRIPT)

    def _attach_console_probe(page: Page) -> None:
        if getattr(page, "_xaloc_afirma_console_probe", False):
            return
        setattr(page, "_xaloc_afirma_console_probe", True)

        def _on_console(msg) -> None:
            try:
                txt = msg.text if isinstance(msg.text, str) else msg.text()
            except Exception:
                txt = ""
            uri = _extract_afirma_uri(str(txt or ""))
            if uri:
                log.info("[AUTOFIRMA] URI detectada en consola (page=%s): %s", (page.url or "")[:120], uri[:140])

        try:
            page.on("console", _on_console)
        except Exception:
            pass

    for page in context.pages:
        _attach_console_probe(page)
    context.on("page", _attach_console_probe)

    setattr(context, "_xaloc_afirma_capture_prepared", True)
    log.info("[AUTOFIRMA] Contexto preparado (init script + listeners de consola).")


def prewarm_autofirma_process(logger: Optional[logging.Logger] = None) -> subprocess.Popen | None:
    """
    Abre AutoFirma en background de forma temprana para evitar timeout de arranque.
    """
    log = logger or logging.getLogger("xaloc_automation.autofirma")
    if AUTOFIRMA_ALWAYS_ON:
        log.info("[AUTOFIRMA] Always-on activo: se omite prewarm por tramite.")
        return None

    if os.name == "nt":
        path = os.getenv("XALOC_AUTOFIRMA_PATH") or r"C:\Program Files\AutoFirma\AutoFirma.exe"
        if not Path(path).exists():
            log.info("[AUTOFIRMA] No existe binario en %s (skip prewarm).", path)
            return None
        try:
            proc = subprocess.Popen(  # noqa: S603
                [path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
            log.info("[AUTOFIRMA] Prewarm lanzado en Windows.")
            return proc
        except Exception as exc:
            log.warning("[AUTOFIRMA] No se pudo lanzar prewarm en Windows: %s", exc)
            return None

    binary = shutil.which("autofirma")
    if not binary:
        log.info("[AUTOFIRMA] Binario 'autofirma' no encontrado (skip prewarm).")
        return None
    try:
        proc = subprocess.Popen(  # noqa: S603
            [binary],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        log.info("[AUTOFIRMA] Prewarm lanzado en Linux.")
        return proc
    except Exception as exc:
        log.warning("[AUTOFIRMA] No se pudo lanzar prewarm en Linux: %s", exc)
        return None


async def wait_autofirma_prewarm_ready(
    proc: subprocess.Popen | None, *, timeout_ms: int = 5000, logger: Optional[logging.Logger] = None
) -> None:
    if AUTOFIRMA_ALWAYS_ON:
        return
    if not proc:
        return
    log = logger or logging.getLogger("xaloc_automation.autofirma")
    waited = 0
    while waited < timeout_ms:
        if proc.poll() is None:
            return
        await asyncio.sleep(0.25)
        waited += 250
    log.info("[AUTOFIRMA] Prewarm no estable en %sms (continuamos).", timeout_ms)


def stop_autofirma_prewarm(proc: subprocess.Popen | None, logger: Optional[logging.Logger] = None) -> None:
    if AUTOFIRMA_ALWAYS_ON:
        return
    if not proc:
        return
    log = logger or logging.getLogger("xaloc_automation.autofirma")
    try:
        proc.terminate()
        log.info("[AUTOFIRMA] Proceso prewarm finalizado.")
    except Exception:
        pass


def reset_afirma_uri_capture_file() -> None:
    latest = Path(os.getenv("XALOC_AFIRMA_URI_LATEST") or "/tmp/xaloc_afirma_uri.latest")
    try:
        if latest.exists():
            latest.unlink()
    except Exception:
        pass


async def wait_for_afirma_uri_trigger(timeout_ms: int = 15000) -> str | None:
    """
    Espera URI capturada por handler XDG (Docker/Linux).
    """
    latest = Path(os.getenv("XALOC_AFIRMA_URI_LATEST") or "/tmp/xaloc_afirma_uri.latest")
    waited = 0
    while waited < timeout_ms:
        try:
            if latest.exists():
                uri = latest.read_text(encoding="utf-8", errors="ignore").strip()
                if uri and AFIRMA_URI_RE.match(uri):
                    return uri
        except Exception:
            pass
        await asyncio.sleep(0.25)
        waited += 250
    return None
