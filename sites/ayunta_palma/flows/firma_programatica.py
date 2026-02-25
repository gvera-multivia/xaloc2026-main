"""
Firma programática para Ayunta Palma en Docker/Linux.

Intercepts the afirma:// URL that Sedipualba tries to open via window.open,
calls AutoFirmaCommandLine with the .pfx certificate, and injects the
resulting signature back into the page so the web submit can proceed
without any GUI popups.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

from playwright.async_api import BrowserContext, Frame, Page

# Usar el logger del sitio para garantizar salida en logs del runner.
logger = logging.getLogger("xaloc_automation.ayunta_palma")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_SIGNING_SUPPORTED = True  # will be False if autofirma binary not found

try:
    # autofirma v1.9 does not have a 'version' subcommand; checking binary exists via -help
    result = subprocess.run(
        ["autofirma", "-help"],
        capture_output=True,
        timeout=10,
    )
    logger.info("[AP-FIRMA] autofirma CLI disponible (autofirma v1.9)")
except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as _e:
    _SIGNING_SUPPORTED = False
    logger.warning("[AP-FIRMA] autofirma no encontrado: %s. La firma programatica no estara disponible.", _e)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Intercept the afirma:// URL
# ─────────────────────────────────────────────────────────────────────────────

_INTERCEPT_SCRIPT = """() => {
    if (window.__xaloc_afirma_interceptor_installed) return;
    window.__xaloc_afirma_interceptor_installed = true;

    window.__afirma_url = window.__afirma_url || null;
    window.__afirma_source = window.__afirma_source || null;

    const captureAfirma = (url, source) => {
        if (typeof url !== 'string') return false;
        if (!url.startsWith('afirma://')) return false;
        window.__afirma_url = url;
        window.__afirma_source = source || 'unknown';
        console.debug('[xaloc] afirma:// capturado via', window.__afirma_source, url.substring(0, 120));
        return true;
    };

    // Capture window.open('afirma://...')
    const _origOpen = window.open.bind(window);
    window.open = function(url, ...rest) {
        if (captureAfirma(url, 'window.open')) {
            return null;
        }
        return _origOpen(url, ...rest);
    };

    // Capture navigation APIs that often emit afirma:// in Sedipualba.
    try {
        const _origAssign = window.location.assign.bind(window.location);
        window.location.assign = function(url) {
            if (captureAfirma(url, 'location.assign')) return;
            return _origAssign(url);
        };
    } catch(e) {
        // ignore
    }
    try {
        const _origReplace = window.location.replace.bind(window.location);
        window.location.replace = function(url) {
            if (captureAfirma(url, 'location.replace')) return;
            return _origReplace(url);
        };
    } catch(e) {
        // ignore
    }
    try {
        const hrefDesc = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
        if (hrefDesc && hrefDesc.set && hrefDesc.get) {
            Object.defineProperty(Location.prototype, 'href', {
                configurable: true,
                enumerable: hrefDesc.enumerable,
                get: function() { return hrefDesc.get.call(this); },
                set: function(url) {
                    if (captureAfirma(url, 'location.href')) return;
                    return hrefDesc.set.call(this, url);
                }
            });
        }
    } catch(e) {
        // ignore
    }

    // Capture clicks on <a href="afirma://...">.
    document.addEventListener('click', function(ev) {
        const el = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
        if (el) {
            const href = el.href || el.getAttribute('href') || '';
            if (captureAfirma(href, 'anchor-click-capture')) {
                ev.preventDefault();
                ev.stopPropagation();
            }
        }
    }, true);

    // Capture programmatic HTMLAnchorElement.click().
    try {
        const _origAnchorClick = HTMLAnchorElement.prototype.click;
        HTMLAnchorElement.prototype.click = function(...args) {
            const href = this.href || this.getAttribute('href') || '';
            if (captureAfirma(href, 'anchor-prototype-click')) return;
            return _origAnchorClick.apply(this, args);
        };
    } catch(e) {
        // ignore
    }

    // Capture direct invocation patterns that may bypass click handlers.
    try {
        const _origSetTimeout = window.setTimeout.bind(window);
        window.setTimeout = function(fn, delay, ...rest) {
            if (typeof fn === 'string' && fn.includes('afirma://')) {
                const m = fn.match(/afirma:\\/\\/[^'\"\\s)]+/);
                if (m && m[0]) {
                    captureAfirma(m[0], 'setTimeout-string');
                    return 0;
                }
            }
            return _origSetTimeout(fn, delay, ...rest);
        };
    } catch(e) {
        // ignore
    }
}"""

_WAIT_FOR_URL_SCRIPT = "() => window.__afirma_url !== null && window.__afirma_url !== undefined"


async def preparar_captura_afirma_context(context: BrowserContext) -> None:
    """
    Inicializa la captura de afirma:// al principio del flujo (antes del login):
    - instala init_script global para todos los documentos/frames futuros
    - registra listener de consola para detectar "Launched external handler for 'afirma://...'"
    """
    try:
        if getattr(context, "_xaloc_afirma_capture_prepared", False):
            return
    except Exception:
        pass

    try:
        await context.add_init_script(_INTERCEPT_SCRIPT)
        logger.info("[AP-FIRMA] init_script global preparado al inicio del contexto.")
    except Exception as e:
        logger.warning("[AP-FIRMA] No se pudo preparar init_script global al inicio: %s", e)

    def _extract_afirma_url(text: str) -> str | None:
        if not text:
            return None
        m = re.search(r"(afirma://[^'\"\\s]+)", text)
        if m:
            return m.group(1)
        return None

    def _attach_listener(p: Page) -> None:
        try:
            if getattr(p, "_xaloc_afirma_console_bootstrap", False):
                return
            setattr(p, "_xaloc_afirma_console_bootstrap", True)
        except Exception:
            pass

        def _on_console(msg) -> None:
            try:
                txt = getattr(msg, "text", "")
                if callable(txt):
                    txt = txt()
                txt = str(txt or "")
                if _extract_afirma_url(txt):
                    logger.info(
                        "[AP-FIRMA][DIAG] Consola detecta afirma:// durante bootstrap (page=%s)",
                        (p.url or "")[:120],
                    )
            except Exception:
                pass

        try:
            p.on("console", _on_console)
        except Exception:
            pass

    try:
        for p in context.pages:
            _attach_listener(p)
        context.on("page", _attach_listener)
    except Exception as e:
        logger.warning("[AP-FIRMA] No se pudo preparar listeners bootstrap de consola: %s", e)

    try:
        setattr(context, "_xaloc_afirma_capture_prepared", True)
    except Exception:
        pass


async def interceptar_y_capturar_url_afirma(
    frame: Frame,
    timeout_ms: int = 30_000,
) -> str:
    """
    Injects the window.open / location intercept into *frame*, waits for the
    afirma:// URL to be captured, and returns it as a string.

    Raises RuntimeError if the URL is not captured within timeout_ms.
    """
    logger.info("[AP-FIRMA] Inyectando interceptor de afirma://...")
    await frame.evaluate(_INTERCEPT_SCRIPT)

    logger.info("[AP-FIRMA] Esperando URL afirma:// (timeout=%sms)...", timeout_ms)
    await frame.wait_for_function(_WAIT_FOR_URL_SCRIPT, timeout=timeout_ms)

    url = await frame.evaluate("() => window.__afirma_url")
    logger.info("[AP-FIRMA] URL afirma:// capturada (%d chars)", len(url or ""))
    return url


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Parse the afirma:// URL
# ─────────────────────────────────────────────────────────────────────────────

def _parsear_afirma_url(url_raw: str) -> dict:
    """
    Decodes an afirma:// URL and returns a normalised dict with at minimum:
        content_b64: str   – base64-encoded content to sign
        format: str        – e.g. "CAdES", "XAdES", "PAdES"
        algorithm: str     – e.g. "SHA256withRSA"
        params_raw: dict   – the full decoded params dict
    """
    # The URL looks like:
    #   afirma://sign?op=sign&params=BASE64_ENCODED_JSON&...
    # or sometimes the params are directly in the path.

    url_decoded = urllib.parse.unquote(url_raw)
    logger.debug("[AP-FIRMA] URL decodificada: %s", url_decoded[:300])

    # Strip the scheme
    if "?" in url_decoded:
        query_str = url_decoded.split("?", 1)[1]
    else:
        query_str = url_decoded.split("://", 1)[-1]

    qs = urllib.parse.parse_qs(query_str, keep_blank_values=True)
    logger.debug("[AP-FIRMA] Query string keys: %s", list(qs.keys()))

    # Try to decode 'params' as a base64 JSON blob first
    params_raw: dict = {}
    if "params" in qs:
        params_b64 = qs["params"][0]
        try:
            params_raw = json.loads(base64.b64decode(params_b64 + "=="))
            logger.debug("[AP-FIRMA] params JSON keys: %s", list(params_raw.keys()))
        except Exception as e:
            logger.warning("[AP-FIRMA] No se pudo decodificar params como JSON: %s", e)
            params_raw = {"raw_b64": params_b64}

    # Extract content to sign.
    # Sedipualba suele enviar 'dat' (base64 del XML documentos_firmados),
    # no necesariamente 'content'/'data'.
    content_b64 = (
        params_raw.get("content")
        or params_raw.get("data")
        or params_raw.get("dat")
        or qs.get("content", [None])[0]
        or qs.get("data", [None])[0]
        or qs.get("dat", [None])[0]
    )

    if not content_b64:
        raise ValueError(
            "[AP-FIRMA] No se encontro 'content', 'data' ni 'dat' en la URL afirma://. "
            f"Keys disponibles: params={list(params_raw.keys())}, qs={list(qs.keys())}"
        )

    fmt = (
        params_raw.get("format")
        or qs.get("format", ["CAdES"])[0]
        or "CAdES"
    )

    algo = (
        params_raw.get("algorithm")
        or params_raw.get("Algorithm")
        or qs.get("algorithm", ["SHA256withRSA"])[0]
        or "SHA256withRSA"
    )

    return {
        "content_b64": content_b64,
        "format": fmt,
        "algorithm": algo,
        "params_raw": params_raw,
        "qs": qs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Sign with AutoFirmaCommandLine
# ─────────────────────────────────────────────────────────────────────────────

def _normalizar_formato(fmt: str) -> str:
    """Normalise signature format string to autofirma v1.9 lowercase names."""
    fmt_norm = str(fmt or "").strip().lower()
    _map = {
        "cades": "cades", "CAdES": "cades",
        "pades": "pades", "PAdES": "pades",
        "xades": "xades", "XAdES": "xades",
        # Variantes habituales de @firma/Sedipualba
        "xadestri": "xades",
        "xadestrifase": "xades",
        "cadestri": "cades",
        "padestri": "pades",
        "auto": "auto",
    }
    return _map.get(fmt_norm, "cades")  # default to cades


def _normalizar_algoritmo(algo: str) -> str:
    """Normalise algorithm string to autofirma v1.9 short names (sha256, sha512, etc.)."""
    algo_lower = algo.lower()
    if "512" in algo_lower:
        return "sha512"
    if "384" in algo_lower:
        return "sha384"
    if "1" in algo_lower and "sha1" in algo_lower:
        return "sha1"
    return "sha256"  # default


def _resolver_alias_pfx(pfx_path: str, pfx_password: str) -> str | None:
    """
    Runs `autofirma listaliases` to discover the first available alias in the PFX.
    Returns the alias string or None if discovery fails.
    """
    try:
        result = subprocess.run(
            [
                "autofirma", "listaliases",
                "-store", f"pkcs12:{pfx_path}",
                "-password", pfx_password,
            ],
            capture_output=True,
            timeout=15,
        )
        output = result.stdout.decode("utf-8", errors="ignore").strip()
        # Output has one alias per line; take the first non-blank line
        for line in output.splitlines():
            line = line.strip()
            if line and not line.startswith("INFO") and not line.startswith("Feb") and not line.startswith("WARNING"):
                logger.info("[AP-FIRMA] Alias resuelto via listaliases: %s", line)
                return line
    except Exception as e:
        logger.warning("[AP-FIRMA] No se pudo resolver alias via listaliases: %s", e)
    return None


def firmar_con_pfx(
    params: dict,
    pfx_path: str,
    pfx_password: str,
) -> str:
    """
    Signs the content described in *params* using autofirma v1.9 CLI and the
    given .pfx certificate.

    autofirma v1.9 sign syntax:
        autofirma sign -i input -o output -store pkcs12:pfxfile -password pwd
                       -alias alias -format cades|pades|xades -algorithm sha256|sha512

    Alias is resolved from SIGNING_PFX_ALIAS env var, then auto-discovered
    via `autofirma listaliases`.

    Returns the signature as a base64 string.
    """
    content_b64 = params["content_b64"]
    fmt = _normalizar_formato(params.get("format", "CAdES"))
    algo = _normalizar_algoritmo(params.get("algorithm", "SHA256withRSA"))

    # Normalizar base64 (incluye variantes URL-safe y padding faltante).
    normalized_b64 = "".join(str(content_b64).split())
    normalized_b64 = normalized_b64.replace("-", "+").replace("_", "/")
    pad = (-len(normalized_b64)) % 4
    if pad:
        normalized_b64 = normalized_b64 + ("=" * pad)
    content_bytes = base64.b64decode(normalized_b64)

    # Resolve certificate alias (required by autofirma v1.9 when PFX has >1 cert)
    cert_alias = (
        os.environ.get("SIGNING_PFX_ALIAS")
        or _resolver_alias_pfx(pfx_path, pfx_password)
    )

    with tempfile.TemporaryDirectory(prefix="xaloc_firma_") as tmpdir:
        f_input = os.path.join(tmpdir, "input.dat")
        f_output = os.path.join(tmpdir, "output.sig")

        with open(f_input, "wb") as fh:
            fh.write(content_bytes)

        # autofirma v1.9: -store pkcs12:path  -password password  -alias alias (required)
        cmd = [
            "autofirma",
            "sign",
            "-i", f_input,
            "-o", f_output,
            "-store", f"pkcs12:{pfx_path}",
            "-password", pfx_password,
            "-format", fmt,
            "-algorithm", algo,
        ]
        if cert_alias:
            cmd += ["-alias", cert_alias]
            logger.info(
                "[AP-FIRMA] Ejecutando autofirma sign format=%s algo=%s alias=%s input_size=%d",
                fmt, algo, cert_alias, len(content_bytes),
            )
        else:
            logger.warning(
                "[AP-FIRMA] Ejecutando autofirma sign sin alias (puede fallar). format=%s algo=%s input_size=%d",
                fmt, algo, len(content_bytes),
            )

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=60,
            )
            stdout = result.stdout.decode("utf-8", errors="ignore").strip()
            if stdout:
                logger.info("[AP-FIRMA] autofirma stdout: %s", stdout[:500])
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="ignore").strip() if e.stderr else ""
            raise RuntimeError(
                f"[AP-FIRMA] autofirma sign fallo (rc={e.returncode}): {stderr}"
            ) from e

        with open(f_output, "rb") as fh:
            firma_bytes = fh.read()

    firma_b64 = base64.b64encode(firma_bytes).decode("ascii")
    logger.info("[AP-FIRMA] Firma completada OK (%d bytes)", len(firma_bytes))
    return firma_b64


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Inject signature and submit
# ─────────────────────────────────────────────────────────────────────────────

_INJECT_FIRMA_SCRIPT = """(firma) => {
    window.__xaloc_firma_trace = [];
    const trace = (step, data) => {
        try {
            window.__xaloc_firma_trace.push({ step, data: data || null, ts: Date.now() });
        } catch (_e) {}
    };

    const preferredFns = [
        'setFirma', 'establecerFirma', 'recibirFirma',
        'onFirmaOK', 'onFirmaOk', 'firmaOK', 'firmaOk',
        'signatureOK', 'signatureOk', 'setSignature',
        'firmaCorrecta', 'onSignOk', 'onSignOK',
    ];

    const blockedCallbackName = (name) => {
        const n = String(name || '').toLowerCase();
        const flat = n.replace(/[^a-z0-9]/g, '');
        if (!n) return true;
        if (n === 'firmar' || n === 'firmar_click') return true;
        if (n.startsWith('firmar')) return true;
        if (n === 'firmarelectronicamente' || n === 'firmarelectronicament') return true;
        if (flat === 'firmarelectronicamente' || flat === 'firmarelectronicament') return true;
        if (n.includes('firmarelectronic')) return true;
        if (n.includes('biometric') || n.includes('biofirma') || n.includes('biofirm')) return true;
        if (n.includes('shadowbox') || n.includes('modal') || n.includes('popup')) return true;
        if (n.includes('actualizar') || n.includes('cerrarpopup')) return true;
        if (n.includes('open') && n.includes('firma')) return true;
        if (n.includes('launch') && n.includes('firma')) return true;
        // Callbacks de "comprobacion/polling" que no consumen firma, solo esperan al cliente local.
        if (n.includes('comprobar') || n.includes('check') || n.includes('verificar') || n.includes('validar')) return true;
        if (n.includes('retrieve') || n.includes('retriever') || n.includes('poll')) return true;
        if (flat.includes('comprobarfirma') || flat.includes('checksignature')) return true;
        return false;
    };

    const dynamicFns = Object.getOwnPropertyNames(window)
        .filter((k) => {
            const v = window[k];
            return (
                typeof v === 'function'
                && /(firma|sign|signature)/i.test(k)
                && !/(error|cancel|close)/i.test(k)
                && !blockedCallbackName(k)
            );
        })
        .slice(0, 40);

    const tryCall = (fn, name) => {
        if (blockedCallbackName(name)) {
            trace('callback_blocked', { name });
            return null;
        }
        trace('try_callback', { name });
        const variants = [
            () => fn(firma),
            () => fn(null, firma),
            () => fn(firma, null),
            () => fn({ signature: firma }),
        ];
        for (const run of variants) {
            try {
                run();
                trace('callback_ok', { name });
                return { ok: true, method: 'callback', callback: name };
            } catch (_e) {
                // continue
            }
        }
        trace('callback_fail', { name });
        return null;
    };

    const tryCallbacks = () => {
        for (const name of preferredFns) {
            try {
                if (typeof window[name] === 'function') {
                    if (blockedCallbackName(name)) continue;
                    const res = tryCall(window[name], name);
                    if (res) return res;
                }
            } catch (_e) {}
        }
        for (const name of dynamicFns) {
            try {
                if (typeof window[name] === 'function') {
                    const res = tryCall(window[name], name);
                    if (res) return res;
                }
            } catch (_e) {}
        }
        const candidateObjs = ['AutoScript', 'afirma', 'clienteFirma', 'Firma', 'Signer'];
        for (const objName of candidateObjs) {
            const obj = window[objName];
            if (!obj || typeof obj !== 'object') continue;
            const names = Object.getOwnPropertyNames(obj).filter(
                (k) => typeof obj[k] === 'function' && /(firma|sign|signature)/i.test(k) && !blockedCallbackName(`${objName}.${k}`)
            );
            for (const m of names) {
                try {
                    const res = tryCall(obj[m].bind(obj), `${objName}.${m}`);
                    if (res) return res;
                } catch (_e) {}
            }
        }
        return null;
    };

    // Primero intentar callback JS del portafirmas (flujo nativo con verificacion "verde").
    const callbackResEarly = tryCallbacks();
    if (callbackResEarly) {
        callbackResEarly.trace_count = (window.__xaloc_firma_trace || []).length;
        return callbackResEarly;
    }

    // Look for the hidden input that Sedipualba uses to receive the signature
    let candidates = [
        ...document.querySelectorAll('input[id*="hfFirma"]'),
        ...document.querySelectorAll('input[name*="hfFirma"]'),
    ];

    if (candidates.length === 0) {
        // Fallback amplio para variantes de Sedipualba donde no usan hfFirma literal.
        const allHidden = Array.from(document.querySelectorAll('input[type="hidden"]'));
        const filtered = allHidden.filter((el) => {
            const id = String(el.id || '').toLowerCase();
            const name = String(el.name || '').toLowerCase();
            const key = `${id} ${name}`;
            if (!key) return false;
            if (key.includes('__viewstate') || key.includes('__eventvalidation') || key.includes('__viewstategenerator')) {
                return false;
            }
            return /(firma|sign|signature|resultado|resfirma|valorfirma)/i.test(key);
        });
        candidates = filtered;
    }

    if (candidates.length === 0) {
        console.error('[xaloc] No se encontro input/callback de firma');
        return {
            ok: false,
            reason: 'no_input_found',
            tried_callbacks: preferredFns.concat(dynamicFns).slice(0, 30),
            trace_count: (window.__xaloc_firma_trace || []).length,
        };
    }

    // Take the last one (usually the most specific)
    const input = candidates[candidates.length - 1];
    input.value = firma;
    trace('hidden_set', { id: input.id || null, name: input.name || null, len: firma.length });
    console.debug('[xaloc] Firma inyectada en:', input.id || input.name, 'len=', firma.length);

    // Reintentar callback tras setear hidden (algunas paginas lo requieren en este orden).
    const callbackResLate = tryCallbacks();
    if (callbackResLate) {
        callbackResLate.trace_count = (window.__xaloc_firma_trace || []).length;
        return callbackResLate;
    }

    // Trigger ASP.NET UpdatePanel postback if available (ultimo recurso)
    if (typeof __doPostBack === 'function') {
        const submitBtns = document.querySelectorAll('input[type="submit"][id*="btnFirmar"], input[type="submit"][name*="btnFirmar"], input[type="submit"][id*="btnAceptar"]');
        if (submitBtns.length > 0) {
            const btn = submitBtns[submitBtns.length - 1];
            console.debug('[xaloc] Disparando postback via button:', btn.id);
            btn.click();
            return { ok: true, method: 'button_click', id: btn.id, trace_count: (window.__xaloc_firma_trace || []).length };
        }
        console.debug('[xaloc] Disparando __doPostBack directo');
        __doPostBack(input.id || input.name, '');
        return { ok: true, method: '__doPostBack', trace_count: (window.__xaloc_firma_trace || []).length };
    }

    // Fallback acotado a pagina de firma
    const onFirmaPage = String(location.pathname || '').toLowerCase().includes('/firma/');
    if (onFirmaPage && document.forms[0]) {
        document.forms[0].submit();
        return { ok: true, method: 'form_submit', trace_count: (window.__xaloc_firma_trace || []).length };
    }

    return { ok: false, reason: 'no_submit_mechanism_or_wrong_frame', trace_count: (window.__xaloc_firma_trace || []).length };
}"""


async def inyectar_firma_y_submit(frame: Frame, firma_b64: str) -> None:
    """
    Injects *firma_b64* into the hidden firma input inside *frame*
    and triggers the postback/submit.
    """
    # Espera corta: algunos expedientes renderizan inputs de firma tras unos ms.
    try:
        await frame.wait_for_selector(
            "input[id*='hfFirma'], input[name*='hfFirma'], input[type='hidden'][id*='Firma'], input[type='hidden'][name*='Firma']",
            timeout=2500,
        )
    except Exception:
        pass

    logger.info("[AP-FIRMA] Inyectando firma en el DOM (%d chars)...", len(firma_b64))
    result = await frame.evaluate(_INJECT_FIRMA_SCRIPT, firma_b64)
    logger.info("[AP-FIRMA] Resultado inyeccion: %s", result)
    if isinstance(result, dict) and not result.get("ok"):
        raise RuntimeError(
            f"[AP-FIRMA] No se pudo inyectar la firma: {result.get('reason')}"
        )


async def _esperar_firma_reflejada_en_padre(page: Page, timeout_ms: int = 55_000) -> bool:
    """
    Tras inyectar la firma, espera primero de forma pasiva para no cortar
    la validacion nativa del iframe/modal, y luego usa refrescos espaciados.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + (timeout_ms / 1000)
    last_diag: dict | None = None

    async def _refresh_parent() -> None:
        await page.evaluate(
            """() => {
                try {
                    if (typeof actualizar === 'function') {
                        actualizar();
                        return;
                    }
                } catch(_e) {}
                try {
                    const btn = document.getElementById('ctl00_ctl00_cphM_cph_btnActualizar')
                        || document.querySelector("input[type='submit'][id*='btnActualizar']");
                    if (btn) btn.click();
                } catch(_e) {}
            }"""
        )

    passive_seconds = float(os.getenv("XALOC_AP_FIRMA_PASSIVE_WAIT_SECONDS", "35") or "35")
    refresh_every_seconds = float(os.getenv("XALOC_AP_FIRMA_REFRESH_EVERY_SECONDS", "6") or "6")
    passive_deadline = min(deadline, loop.time() + passive_seconds)
    next_refresh_at = passive_deadline

    while loop.time() < deadline:
        try:
            diag = await page.evaluate(
                """() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetHeight > 0;
                    };
                    const noFirmadaPanel = document.getElementById('ctl00_ctl00_cphM_cph_pnlFirmaNoRealizada')
                        || document.querySelector("div[id*='pnlFirmaNoRealizada']");
                    const noFirmadaText = (noFirmadaPanel?.textContent || '').trim();
                    const estado = (document.getElementById('ctl00_ctl00_cphM_cph_txtDescripcionEstado')?.textContent || '').trim();
                    const hasVisibleSignButton = Array.from(document.querySelectorAll('button,input[type="submit"]'))
                        .some((el) => {
                            const txt = ((el.textContent || el.value || '') + '').trim().toLowerCase();
                            if (!(txt.includes('signar') || txt.includes('firmar'))) return false;
                            const s = window.getComputedStyle(el);
                            return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetHeight > 0;
                        });
                    const firmarBtnVisible = hasVisibleSignButton;
                    const pendingRegex = /(pendent de signatura|pendiente de firma|no s'ha realitzat|no se ha realizado)/i;
                    const pendingByText = pendingRegex.test(`${estado} ${noFirmadaText}`);
                    const noFirmadaVisible = isVisible(noFirmadaPanel) && pendingRegex.test(noFirmadaText || '');
                    const ok = !noFirmadaVisible && !pendingByText;
                    return {
                        ok,
                        no_firmada_visible: noFirmadaVisible,
                        estado,
                        no_firmada_text: noFirmadaText.slice(0, 220),
                        firmar_btn_visible: firmarBtnVisible,
                    };
                }"""
            )
            last_diag = diag if isinstance(diag, dict) else None
            if isinstance(diag, dict) and bool(diag.get("ok")):
                logger.info("[AP-FIRMA] Estado de firma reflejado en pagina padre: %s", diag)
                return True
        except Exception:
            pass

        now = loop.time()
        if now >= next_refresh_at:
            try:
                await _refresh_parent()
            except Exception:
                pass
            next_refresh_at = now + max(1.0, refresh_every_seconds)
        await asyncio.sleep(1.2)

    logger.warning("[AP-FIRMA] Timeout esperando reflejo de firma en pagina padre. last_diag=%s", last_diag)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Public high-level entry point
# ─────────────────────────────────────────────────────────────────────────────

async def _click_signar_tots_programatic(page: Page) -> bool:
    """
    Clicks the 'Signar tots els documents' / 'Firmar todos los documentos' button
    in any frame where it can be found.
    """
    strict_button_selectors = [
        "button:has-text('Signar tots els documents')",
        "button:has-text('Firmar todos los documentos')",
        "button:has-text('Firmar tots els documents')",
        "button.btnFirmar",
    ]
    hidden_fallback_selectors = [
        "input[type='submit'][value*='Signar']",
        "input[type='submit'][value*='Firmar']",
        "input[id*='btnFirmar']",
        "input[name*='btnFirmar']",
    ]
    pre_signar_selectors = [
        "input[id$='_btnFirmar']",
        "input[name$='$btnFirmar']",
        "input[type='submit'][value='Signar']",
        "button:has-text('Signar')",
    ]
    allow_hidden_fallback = (os.getenv("XALOC_AP_FIRMA_ALLOW_HIDDEN_CLICK") or "0").strip().lower() in {
        "1", "true", "yes", "on"
    }

    async def _try_locator_click(scope, label: str) -> bool:
        # 1) Click real de Playwright (trusted) sobre boton visible.
        for sel in strict_button_selectors:
            try:
                locator = scope.locator(sel).first
                if await locator.count() == 0:
                    continue
                if not await locator.is_visible():
                    continue
                await locator.scroll_into_view_if_needed()
                await locator.click(timeout=3000)
                logger.info("[AP-FIRMA] Boton Signar tots clickado en %s via trusted-click: %s", label, sel)
                return True
            except Exception:
                continue

        # 1b) Fallback JS si el click trusted no entra.
        for sel in strict_button_selectors:
            try:
                locator = scope.locator(sel).first
                if await locator.count() == 0:
                    continue
                if not await locator.is_visible():
                    continue
                await locator.scroll_into_view_if_needed()
                handle = await locator.element_handle()
                if handle is None:
                    continue
                clicked = await handle.evaluate(
                    """(el) => {
                        try {
                            el.click();
                            return {
                                ok: true,
                                mode: 'dom-click',
                                tag: el.tagName || null,
                                id: el.id || null,
                                text: (el.textContent || '').trim().slice(0, 80),
                            };
                        } catch (e) {
                            return { ok: false, err: String(e) };
                        }
                    }"""
                )
                if isinstance(clicked, dict) and clicked.get("ok"):
                    logger.info("[AP-FIRMA] Boton Signar tots clickado en %s via JS boton visible: %s (%s)", label, sel, clicked)
                    return True
            except Exception:
                continue

        # 2) Fallback opcional (desactivado por defecto): submit oculto.
        if allow_hidden_fallback:
            for sel in hidden_fallback_selectors:
                try:
                    locator = scope.locator(sel).first
                    if await locator.count() == 0:
                        continue
                    await locator.click(force=True, timeout=3000)
                    logger.info("[AP-FIRMA] Click hidden fallback en %s: %s", label, sel)
                    return True
                except Exception:
                    continue
        return False

    async def _try_click_pre_signar(scope, label: str) -> bool:
        for sel in pre_signar_selectors:
            try:
                locator = scope.locator(sel).first
                if await locator.count() == 0:
                    continue
                if not await locator.is_visible():
                    continue
                await locator.scroll_into_view_if_needed()
                await locator.click(timeout=3000)
                logger.info("[AP-FIRMA][DIAG] Click en boton previo 'Signar' en %s: %s", label, sel)
                return True
            except Exception:
                continue
        return False

    async def _diag_scope(scope, label: str) -> None:
        try:
            diag = await scope.evaluate(
                """() => {
                    const buttons = Array.from(document.querySelectorAll("button"))
                        .map((b) => ((b.textContent || '').trim()).slice(0, 80))
                        .filter(Boolean)
                        .slice(0, 8);
                    const submits = Array.from(document.querySelectorAll("input[type='submit']"))
                        .map((i) => ({ id: i.id || null, name: i.name || null, value: i.value || null }))
                        .slice(0, 8);
                    return { buttons, submits };
                }"""
            )
            logger.warning("[AP-FIRMA][DIAG] No click en %s. candidates=%s", label, diag)
        except Exception as e:
            logger.warning("[AP-FIRMA][DIAG] No click en %s y sin snapshot: %s", label, e)

    # Priorizar frames de firma/modal y dejar main frame al final.
    frame_candidates: list[tuple[Frame | Page, str]] = []
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        frame_url = (frame.url or "").lower()
        priority = (
            "firmar.aspx" in frame_url
            or "firma" in frame_url
            or "sedipualba" in frame_url
        )
        label = f"frame {(frame.url or '')[:60]}"
        if priority:
            frame_candidates.insert(0, (frame, label))
        else:
            frame_candidates.append((frame, label))

    # ventanaModal suele contener el frame correcto, lo ponemos primero si existe.
    try:
        modal_iframe = page.locator("#ventanaModal")
        if await modal_iframe.count() > 0:
            handle = await modal_iframe.element_handle()
            if handle:
                content_frame = await handle.content_frame()
                if content_frame:
                    frame_candidates.insert(0, (content_frame, "ventanaModal"))
    except Exception as e:
        logger.debug("[AP-FIRMA] No se pudo obtener ventanaModal: %s", e)

    for scope, label in frame_candidates:
        try:
            if await _try_locator_click(scope, label):
                return True
        except Exception as e:
            logger.debug("[AP-FIRMA] No se pudo clickar en %s: %s", label, e)

    # Main frame al final.
    try:
        if await _try_locator_click(page, "main frame"):
            return True
    except Exception as e:
        logger.debug("[AP-FIRMA] No se pudo clickar en main frame: %s", e)

    # Fallback intermedio: aun no existe "Signar tots...", intentar "Signar" previo
    # y despues reintentar "Signar tots" durante unos segundos.
    clicked_pre_signar = False
    for scope, label in frame_candidates:
        try:
            if await _try_click_pre_signar(scope, label):
                clicked_pre_signar = True
                break
        except Exception:
            continue
    if not clicked_pre_signar:
        try:
            if await _try_click_pre_signar(page, "main frame"):
                clicked_pre_signar = True
        except Exception:
            pass

    if clicked_pre_signar:
        # Tras click en "Signar", el iframe de firma puede tardar bastante en montar.
        end = asyncio.get_event_loop().time() + 30.0
        while asyncio.get_event_loop().time() < end:
            # Refrescar candidatos: el modal puede aparecer despues.
            try:
                modal_iframe = page.locator("#ventanaModal")
                if await modal_iframe.count() > 0:
                    handle = await modal_iframe.element_handle()
                    if handle:
                        content_frame = await handle.content_frame()
                        if content_frame:
                            frame_candidates.insert(0, (content_frame, "ventanaModal-late"))
            except Exception:
                pass
            for scope, label in frame_candidates:
                try:
                    if await _try_locator_click(scope, label):
                        return True
                except Exception:
                    continue
            try:
                if await _try_locator_click(page, "main frame"):
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.25)
        logger.warning("[AP-FIRMA] Se clicko 'Signar' previo pero no aparecio/clicko 'Signar tots' en ventana esperada.")
        return False

    await _diag_scope(page, "main frame")
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        await _diag_scope(frame, f"frame {(frame.url or '')[:60]}")

    logger.warning("[AP-FIRMA] No se encontro el boton 'Signar tots els documents' ni el previo 'Signar'")
    return False


async def _puede_reintentar_click_signar(page: Page) -> bool:
    """
    Evita bucles de recarga: solo reintentar click si el boton sigue visible
    y no hay un overlay de carga activo.
    """
    try:
        busy = await page.evaluate(
            """() => {
                const velo = document.querySelector('#velo');
                if (!velo) return false;
                const style = window.getComputedStyle(velo);
                return style.display !== 'none' && style.visibility !== 'hidden' && velo.offsetHeight > 0;
            }"""
        )
        if busy:
            return False
    except Exception:
        pass

    try:
        checks = [
            page.locator("button.btnFirmar:visible").first,
            page.locator("button:has-text('Signar tots els documents'):visible").first,
            page.locator("button:has-text('Firmar todos los documentos'):visible").first,
            page.locator("input[type='submit'][value*='Signar']:visible").first,
            page.locator("input[type='submit'][value*='Firmar']:visible").first,
        ]
        for loc in checks:
            if await loc.count() > 0:
                return True
    except Exception:
        pass
    return False


async def firmar_programaticamente(
    page: Page,
    pfx_path: str | None = None,
    pfx_password: str | None = None,
    *,
    url_timeout_ms: int = 45_000,
) -> bool:
    """
    High-level entry point. Locates the signing iframe on *page*, intercepts
    the afirma:// URL, calls AutoFirmaCommandLine and injects the result.

    Returns True if signing completed successfully.
    Returns False if AutoFirmaCommandLine is not available (caller should
    fall back to Windows UIAutomation approach).

    Raises RuntimeError on partial failures (URL not captured, signing error, etc.)

    Sequence:
    1. Inject window.open intercept into ALL frames (before clicking)
    2. Click 'Signar tots els documents' in the signing iframe
    3. Wait for afirma:// URL to be captured
    4. Parse params, call AutoFirmaCommandLine, inject signature, submit
    """
    if not _SIGNING_SUPPORTED:
        logger.info("[AP-FIRMA] Firma programatica no disponible (AutoFirmaCommandLine ausente).")
        return False

    pfx_path = pfx_path or os.environ.get("SIGNING_PFX_PATH") or os.environ.get("PLAYWRIGHT_CERT_PATH")
    pfx_password = pfx_password or os.environ.get("SIGNING_PFX_PASSWORD") or os.environ.get("PLAYWRIGHT_CERT_PASSWORD", "")

    if not pfx_path or not Path(pfx_path).exists():
        raise RuntimeError(
            f"[AP-FIRMA] Certificado PFX no encontrado en: {pfx_path!r}. "
            "Configura SIGNING_PFX_PATH o PLAYWRIGHT_CERT_PATH."
        )

    console_capture: dict[str, str] = {}
    net_diag_enabled = (os.getenv("XALOC_AP_FIRMA_NET_DIAG") or "1").strip().lower() in {"1", "true", "yes", "on"}
    net_events: list[dict] = []
    handler_latest_file = Path(os.getenv("XALOC_AFIRMA_URI_LATEST") or "/tmp/xaloc_afirma_uri.latest")
    handler_log_file = Path(os.getenv("XALOC_AFIRMA_URI_LOG") or "/tmp/xaloc_afirma_uri.log")

    def _extract_afirma_url(text: str) -> str | None:
        if not text:
            return None
        m = re.search(r"(afirma://[^'\"\\s]+)", text)
        if m:
            return m.group(1)
        return None

    def _attach_console_listener(p: Page) -> None:
        try:
            if getattr(p, "_xaloc_afirma_console_hook", False):
                return
            setattr(p, "_xaloc_afirma_console_hook", True)
        except Exception:
            pass

        def _on_console(msg) -> None:
            try:
                txt = getattr(msg, "text", "")
                if callable(txt):
                    txt = txt()
                txt = str(txt or "")
                url = _extract_afirma_url(txt)
                if not url:
                    return
                if not console_capture.get("url"):
                    console_capture["url"] = url
                    console_capture["source"] = "console.external-handler"
                    try:
                        console_capture["page_url"] = p.url or ""
                    except Exception:
                        console_capture["page_url"] = ""
                    logger.info(
                        "[AP-FIRMA][DIAG] URL capturada via console source=%s page_url=%s chars=%d",
                        console_capture.get("source"),
                        (console_capture.get("page_url") or "")[:120],
                        len(url),
                    )
            except Exception:
                pass

        try:
            p.on("console", _on_console)
        except Exception:
            pass

    def _track_net_event(evt: dict) -> None:
        if not net_diag_enabled:
            return
        net_events.append(evt)
        if len(net_events) > 120:
            del net_events[: len(net_events) - 120]

    def _attach_network_listener(p: Page) -> None:
        try:
            if getattr(p, "_xaloc_afirma_net_hook", False):
                return
            setattr(p, "_xaloc_afirma_net_hook", True)
        except Exception:
            pass

        def _interesting(url: str, method: str) -> bool:
            u = (url or "").lower()
            m = (method or "").upper()
            return (
                "triphaseafirma" in u
                or "signature-storage" in u
                or "signatureservice" in u
                or "/firma/" in u
                or "afirma-signature-storage" in u
                or "afirma-server-triphase-signer" in u
                or m in {"POST", "PUT"}
            )

        def _on_request(req) -> None:
            try:
                url = str(req.url or "")
                method = str(req.method or "GET")
                if not _interesting(url, method):
                    return
                _track_net_event(
                    {
                        "kind": "request",
                        "method": method,
                        "url": url[:260],
                        "resource_type": str(getattr(req, "resource_type", "") or ""),
                    }
                )
            except Exception:
                pass

        def _on_response(resp) -> None:
            try:
                req = resp.request
                url = str(getattr(req, "url", "") or "")
                method = str(getattr(req, "method", "GET") or "GET")
                if not _interesting(url, method):
                    return
                _track_net_event(
                    {
                        "kind": "response",
                        "method": method,
                        "url": url[:260],
                        "status": int(resp.status),
                        "ok": bool(resp.ok),
                    }
                )
            except Exception:
                pass

        try:
            p.on("request", _on_request)
            p.on("response", _on_response)
        except Exception:
            pass

    try:
        for _p in page.context.pages:
            _attach_console_listener(_p)
            _attach_network_listener(_p)
        page.context.on("page", _attach_console_listener)
        page.context.on("page", _attach_network_listener)
        logger.info("[AP-FIRMA] Listener de consola activado para captura de afirma://")
    except Exception as e:
        logger.warning("[AP-FIRMA] No se pudo activar listener de consola: %s", e)

    # Clave: mantener interceptor en cada nuevo documento/frame (postbacks, popups, recargas).
    try:
        await page.context.add_init_script(_INTERCEPT_SCRIPT)
        logger.info("[AP-FIRMA] Interceptor registrado como init_script en el contexto.")
    except Exception as e:
        logger.warning("[AP-FIRMA] No se pudo registrar init_script global: %s", e)

    # Limpiar URI previa del handler XDG para evitar lecturas stale.
    try:
        if handler_latest_file.exists():
            handler_latest_file.unlink()
    except Exception:
        pass

    def _iter_context_frames() -> list[Frame]:
        frames: list[Frame] = []
        try:
            pages = [p for p in page.context.pages if not p.is_closed()]
        except Exception:
            pages = [page]
        for p in pages:
            try:
                frames.extend(p.frames)
            except Exception:
                continue
        # Dedup estable por id(obj)
        seen: set[int] = set()
        unique: list[Frame] = []
        for fr in frames:
            marker = id(fr)
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(fr)
        return unique

    # Step 1: Inject the intercept into ALL frames before anything is clicked
    # so we don't miss the URL regardless of where window.open is called.
    logger.info("[AP-FIRMA] Inyectando interceptors en todos los frames/paginas del contexto...")
    target_frame: Frame = page.main_frame
    frames_with_intercept: list[Frame] = []

    for frame in _iter_context_frames():
        try:
            await frame.evaluate(_INTERCEPT_SCRIPT)
            frames_with_intercept.append(frame)
            logger.debug("[AP-FIRMA] Interceptor inyectado en frame: %s", (frame.url or "")[:80])
        except Exception as e:
            logger.debug("[AP-FIRMA] No se pudo inyectar en frame %s: %s", (frame.url or "")[:60], e)

        # Prefer the signing iframe as the primary wait target
        url = frame.url or ""
        if "firmar" in url.lower() or "firma" in url.lower():
            if frame != page.main_frame:
                target_frame = frame
                logger.info("[AP-FIRMA] Iframe de firma (target): %s", url[:120])

    logger.info("[AP-FIRMA] Interceptors en %d frames. Target frame: %s",
                len(frames_with_intercept), (target_frame.url or "")[:80])

    # Step 2: Click the 'Signar tots els documents' button to trigger the URL
    logger.info("[AP-FIRMA] Clickando boton 'Signar tots els documents'...")
    clicked = await _click_signar_tots_programatic(page)
    if not clicked:
        logger.warning("[AP-FIRMA] No se pudo clickar Signar tots. Esperando URL de todos modos...")
    else:
        # Dar margen a posibles aperturas de popup/nueva pestana.
        await asyncio.sleep(0.4)

    # Step 3: Wait for afirma:// URL on any frame that has the intercept.
    # We poll all frames because the URL may land in a different frame than
    # the one holding the button.
    logger.info("[AP-FIRMA] Esperando URL afirma:// (timeout=%sms)...", url_timeout_ms)

    url_afirma: str | None = None
    source_afirma: str | None = None
    diag_enabled = (os.getenv("XALOC_AP_FIRMA_DIAG") or "1").strip().lower() in {"1", "true", "yes", "on"}
    loop = asyncio.get_event_loop()
    deadline = loop.time() + (url_timeout_ms / 1000)
    next_click_retry_at = loop.time() + 2.0
    click_retry_count = 0
    clicked_signar_once = bool(clicked)
    max_click_retries = max(1, int((os.getenv("XALOC_AP_FIRMA_MAX_RETRY_CLICKS") or "3").strip() or "3"))

    while loop.time() < deadline:
        # Tambien inyectar en nuevos frames/paginas que aparezcan tras el click.
        for frame in _iter_context_frames():
            if frame not in frames_with_intercept:
                try:
                    await frame.evaluate(_INTERCEPT_SCRIPT)
                    frames_with_intercept.append(frame)
                    logger.debug("[AP-FIRMA] Interceptor inyectado en nuevo frame: %s", (frame.url or "")[:80])
                except Exception:
                    pass

        # Reintentar click en el boton del popup de firma mientras esperamos la URL.
        # En algunos expedientes el modal tarda en renderizar y el primer click cae demasiado pronto.
        if (
            loop.time() >= next_click_retry_at
            and not url_afirma
            and not clicked_signar_once
            and click_retry_count < max_click_retries
        ):
            if await _puede_reintentar_click_signar(page):
                click_retry_count += 1
                clicked_retry = await _click_signar_tots_programatic(page)
                if clicked_retry:
                    clicked_signar_once = True
                logger.info(
                    "[AP-FIRMA][DIAG] Reintento click Signar tots #%d/%d -> %s",
                    click_retry_count,
                    max_click_retries,
                    "ok" if clicked_retry else "no",
                )
            else:
                logger.debug("[AP-FIRMA][DIAG] Reintento click omitido: UI en carga o boton no visible.")
            next_click_retry_at = loop.time() + 2.0

        # Fallback de captura desde consola Chromium:
        # "Launched external handler for 'afirma://...'"
        if not url_afirma and console_capture.get("url"):
            url_afirma = console_capture["url"]
            source_afirma = console_capture.get("source", "console.external-handler")
            logger.info(
                "[AP-FIRMA][DIAG] Usando URL afirma:// capturada por consola (%d chars).",
                len(url_afirma),
            )
            break

        # Fallback de captura desde handler XDG (afirma-handler.sh).
        if not url_afirma:
            try:
                if handler_latest_file.exists():
                    handler_uri = handler_latest_file.read_text(encoding="utf-8", errors="ignore").strip()
                    if handler_uri.startswith("afirma://"):
                        url_afirma = handler_uri
                        source_afirma = "xdg-handler-file"
                        logger.info(
                            "[AP-FIRMA][DIAG] Usando URL afirma:// capturada por handler XDG (%d chars, file=%s, log=%s).",
                            len(url_afirma),
                            handler_latest_file,
                            handler_log_file,
                        )
                        break
            except Exception:
                pass

        # Check all frames for the captured URL
        for frame in list(frames_with_intercept):
            try:
                diag = await frame.evaluate(
                    """() => {
                        if (window.__afirma_url) {
                            return {
                                afirma_url: window.__afirma_url,
                                afirma_source: window.__afirma_source || null,
                                has_anchor: !!document.querySelector('a[href^="afirma://"]'),
                                has_hidden: !!Array.from(document.querySelectorAll('input[type="hidden"]'))
                                    .find(x => typeof x.value === 'string' && x.value.startsWith('afirma://')),
                            };
                        }
                        const a = document.querySelector('a[href^="afirma://"]');
                        if (a && a.href) {
                            window.__afirma_url = a.href;
                            window.__afirma_source = 'dom-anchor-scan';
                            return {
                                afirma_url: window.__afirma_url,
                                afirma_source: window.__afirma_source,
                                has_anchor: true,
                                has_hidden: false,
                            };
                        }
                        const hidden = Array.from(document.querySelectorAll('input[type="hidden"]'))
                            .map(x => x.value)
                            .find(v => typeof v === 'string' && v.startsWith('afirma://'));
                        if (hidden) {
                            window.__afirma_url = hidden;
                            window.__afirma_source = 'dom-hidden-scan';
                            return {
                                afirma_url: window.__afirma_url,
                                afirma_source: window.__afirma_source,
                                has_anchor: false,
                                has_hidden: true,
                            };
                        }
                        return {
                            afirma_url: null,
                            afirma_source: window.__afirma_source || null,
                            has_anchor: false,
                            has_hidden: false,
                        };
                    }"""
                )
                captured = (diag or {}).get("afirma_url") if isinstance(diag, dict) else None
                if captured:
                    url_afirma = captured
                    source_afirma = (diag or {}).get("afirma_source") if isinstance(diag, dict) else None
                    frame_url = (frame.url or "")[:120]
                    page_url = ""
                    try:
                        page_url = (frame.page.url or "")[:120]
                    except Exception:
                        page_url = ""
                    logger.info(
                        "[AP-FIRMA][DIAG] URL capturada source=%s frame_url=%s page_url=%s chars=%d",
                        source_afirma or "unknown",
                        frame_url,
                        page_url,
                        len(captured),
                    )
                    break
            except Exception:
                pass

        if url_afirma:
            break

        await asyncio.sleep(0.15)

    if not url_afirma:
        if diag_enabled:
            for idx, frame in enumerate(list(frames_with_intercept), start=1):
                try:
                    snap = await frame.evaluate(
                        """() => ({
                            afirma_source: window.__afirma_source || null,
                            afirma_url_prefix: (window.__afirma_url && String(window.__afirma_url).slice(0, 80)) || null,
                            has_anchor: !!document.querySelector('a[href^="afirma://"]'),
                            has_hidden: !!Array.from(document.querySelectorAll('input[type="hidden"]'))
                                .find(x => typeof x.value === 'string' && x.value.startsWith('afirma://')),
                            ready: document.readyState || null,
                        })"""
                    )
                    frame_url = (frame.url or "")[:120]
                    page_url = ""
                    try:
                        page_url = (frame.page.url or "")[:120]
                    except Exception:
                        page_url = ""
                    logger.warning(
                        "[AP-FIRMA][DIAG][TIMEOUT] frame#%d source=%s has_anchor=%s has_hidden=%s ready=%s frame_url=%s page_url=%s prefix=%s",
                        idx,
                        (snap or {}).get("afirma_source"),
                        (snap or {}).get("has_anchor"),
                        (snap or {}).get("has_hidden"),
                        (snap or {}).get("ready"),
                        frame_url,
                        page_url,
                        (snap or {}).get("afirma_url_prefix"),
                    )
                except Exception as e:
                    logger.warning("[AP-FIRMA][DIAG][TIMEOUT] frame#%d snapshot-error=%s", idx, e)
        raise RuntimeError(
            f"[AP-FIRMA] Timeout: URL afirma:// no capturada en {url_timeout_ms}ms. "
            "Verifica que el boton 'Signar tots els documents' fue clickado y que Sedipualba genera una URL afirma://."
        )

    # Step 4: Parse
    params = _parsear_afirma_url(url_afirma)

    # Step 5: Sign in a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    firma_b64 = await loop.run_in_executor(
        None,
        firmar_con_pfx,
        params,
        pfx_path,
        pfx_password,
    )

    # Step 6: Inject result on the real signing frame (avoid main-frame false positives).
    inject_candidates: list[Frame] = []
    seen_ids: set[int] = set()

    def _push_candidate(fr: Frame | None) -> None:
        if fr is None:
            return
        marker = id(fr)
        if marker in seen_ids:
            return
        seen_ids.add(marker)
        inject_candidates.append(fr)

    # 1) frame where URL was captured by JS intercept
    for frame in frames_with_intercept:
        try:
            captured = await frame.evaluate("() => window.__afirma_url")
            if captured:
                _push_candidate(frame)
        except Exception:
            pass

    # 2) ventanaModal content frame
    try:
        modal_iframe = page.locator("#ventanaModal").first
        if await modal_iframe.count() > 0:
            handle = await modal_iframe.element_handle()
            if handle:
                _push_candidate(await handle.content_frame())
    except Exception:
        pass

    # 3) any /firma/ frame
    for frame in page.frames:
        try:
            if "/firma/" in (frame.url or "").lower() or "firmar.aspx" in (frame.url or "").lower():
                _push_candidate(frame)
        except Exception:
            continue

    # 4) original target + fallback list
    _push_candidate(target_frame)
    for frame in frames_with_intercept:
        _push_candidate(frame)

    # 5) parent/main frames as additional fallback (hay expedientes donde hfFirma vive fuera del iframe)
    try:
        _push_candidate(page.main_frame)
    except Exception:
        pass
    try:
        for p in page.context.pages:
            if p.is_closed():
                continue
            _push_candidate(p.main_frame)
    except Exception:
        pass

    inject_errors: list[str] = []
    for frame in inject_candidates:
        frame_url = ""
        try:
            frame_url = (frame.url or "")[:180]
        except Exception:
            frame_url = "<unknown>"
        low_url = (frame_url or "").lower()
        if (
            "google.com/recaptcha" in low_url
            or "gstatic.com/recaptcha" in low_url
            or low_url == "about:blank"
        ):
            continue
        try:
            await inyectar_firma_y_submit(frame, firma_b64)
            logger.info("[AP-FIRMA] Inyeccion OK en frame=%s", frame_url)
            # No refrescar inmediatamente: puede interrumpir la verificacion nativa
            # del popup de firma y dejar el estado "pendiente" aunque la firma exista.
            reflected = await _esperar_firma_reflejada_en_padre(page)
            if not reflected:
                try:
                    frame_trace = await frame.evaluate(
                        "() => (Array.isArray(window.__xaloc_firma_trace) ? window.__xaloc_firma_trace.slice(-20) : [])"
                    )
                except Exception:
                    frame_trace = []
                try:
                    net_tail = net_events[-30:]
                except Exception:
                    net_tail = []
                logger.warning(
                    "[AP-FIRMA][DIAG] Sin reflejo tras inyeccion. frame_trace=%s net_tail=%s",
                    frame_trace,
                    net_tail,
                )
                raise RuntimeError(
                    "[AP-FIRMA] Firma generada e inyectada, pero la pagina padre no la reflejo (sigue pendiente/no realizada)."
                )
            return True
        except Exception as e:
            inject_errors.append(f"{frame_url} -> {e}")
            continue

    raise RuntimeError(
        "[AP-FIRMA] No se pudo inyectar la firma en ningun frame candidato. "
        f"Intentos={len(inject_errors)}. Detalle: {' | '.join(inject_errors[:6])}"
    )

    return True

