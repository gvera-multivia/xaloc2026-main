from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.autofirma_js import get_redsara_afirma_hook_script
from core.autofirma_shared import (
    prepare_autofirma_context,
    prewarm_autofirma_process,
    reset_afirma_uri_capture_file,
    stop_autofirma_prewarm,
    wait_for_afirma_uri_trigger,
    wait_autofirma_prewarm_ready,
)
from core.fire_signing_bridge import FireSigningResult, execute_fire_signing
from core.justificantes_storage import (
    build_non_overwrite_path,
    build_receipt_filename,
    resolve_receipt_dir_from_payload,
    save_receipt_from_tmp,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from ..config import ValenciaConfig
    from ..data_models import ValenciaTarget

logger = logging.getLogger("xaloc_automation.valencia")
_AFIRMA_URI_RE = re.compile(r"((?:afirma|xalocafirma)://[^'\"\s]+)", re.IGNORECASE)
_VALENCIA_HOOK_FN_NAME = "__xaloc_valencia_capture_afirma_uri"
_VALENCIA_JUSTIFICANTE_INPUT_ID = "formDescargas:j_id988508038_1_2cd7c38b"
_VALENCIA_JUSTIFICANTE_SELECTORS = (
    f'input[id="{_VALENCIA_JUSTIFICANTE_INPUT_ID}"]',
    'input[name^="formDescargas:"][type="submit"][value*="Descàrrega"]',
    'input[name^="formDescargas:"][type="submit"][value*="Descarga"]',
    'form[id^="formDescargas"] input[type="submit"][value*="pdf"]',
    '[data-clickable-url*=".pdf"]',
    'a[href*=".pdf"]',
    'a[href*="descarga"]',
)
_CERT_B64_CACHE: str | None = None


def _is_afirma_debug_enabled() -> bool:
    return (os.getenv("VALENCIA_AFIRMA_DEBUG") or "0").strip().lower() in {"1", "true", "yes", "on"}


def _is_afirma_deep_debug_enabled() -> bool:
    if not _is_afirma_debug_enabled():
        return False
    return (os.getenv("VALENCIA_AFIRMA_DEEP_DEBUG") or "1").strip().lower() in {"1", "true", "yes", "on"}


def _should_block_external_afirma_launch() -> bool:
    return (os.getenv("VALENCIA_BLOCK_EXTERNAL_AFIRMA_LAUNCH") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _extract_afirma_uri(value: object) -> str | None:
    txt = str(value or "")
    m = _AFIRMA_URI_RE.search(txt)
    if m:
        return m.group(1)
    low = txt.lower()
    idx = low.find("afirma://")
    if idx < 0:
        idx = low.find("xalocafirma://")
    if idx < 0:
        return None
    raw = txt[idx:]
    stop = len(raw)
    for sep in (" ", "\n", "\r", "\t", "'", '"', "<", ">"):
        pos = raw.find(sep)
        if pos != -1:
            stop = min(stop, pos)
    uri = raw[:stop].strip()
    return uri or None


def _latest_afirma_uri_from_telemetry(telemetry: dict) -> str | None:
    direct = str(telemetry.get("_last_afirma_uri") or "").strip()
    if _AFIRMA_URI_RE.match(direct):
        return direct
    events = telemetry.get("events") or []
    if not isinstance(events, list):
        return None
    for ev in reversed(events):
        if not isinstance(ev, dict):
            continue
        data = ev.get("data") or {}
        if not isinstance(data, dict):
            continue
        for key in ("uri", "uri_prefix", "url", "raw"):
            uri = _extract_afirma_uri(data.get(key))
            if uri:
                return uri
    return None


def _extract_signing_cert_b64() -> str:
    global _CERT_B64_CACHE
    if _CERT_B64_CACHE is not None:
        return _CERT_B64_CACHE
    pfx_path = (os.getenv("PLAYWRIGHT_CERT_PATH") or "/data/certificates/certificate.pfx").strip()
    pfx_password = (os.getenv("PLAYWRIGHT_CERT_PASSWORD") or os.getenv("SIGNING_PFX_PASSWORD") or "").strip()
    if not pfx_path or not Path(pfx_path).exists():
        _CERT_B64_CACHE = ""
        return _CERT_B64_CACHE
    try:
        openssl_cmd = ["openssl", "pkcs12", "-in", pfx_path, "-clcerts", "-nokeys", "-passin", f"pass:{pfx_password}"]
        proc = subprocess.run(openssl_cmd, capture_output=True, check=False, timeout=20)
        if proc.returncode != 0:
            proc = subprocess.run(openssl_cmd + ["-legacy"], capture_output=True, check=False, timeout=20)
        pem = (proc.stdout or b"").decode("utf-8", errors="ignore")
        if proc.returncode != 0 or "BEGIN CERTIFICATE" not in pem:
            _CERT_B64_CACHE = ""
            return _CERT_B64_CACHE
        m = re.search(r"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----", pem, re.S)
        if not m:
            _CERT_B64_CACHE = ""
            return _CERT_B64_CACHE
        _CERT_B64_CACHE = "".join((m.group(1) or "").split())
        return _CERT_B64_CACHE
    except Exception:
        _CERT_B64_CACHE = ""
        return _CERT_B64_CACHE


def _extract_cert_b64_from_signature(signature_b64: str) -> str:
    sig_txt = "".join(str(signature_b64 or "").split()).strip()
    if not sig_txt:
        return ""
    try:
        raw = base64.b64decode(sig_txt + ("=" * ((4 - len(sig_txt) % 4) % 4)))
    except Exception:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    if not text:
        return ""
    m = re.search(
        r"<(?:[A-Za-z0-9_]+:)?X509Certificate>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?X509Certificate>",
        text,
        re.S,
    )
    if not m:
        return ""
    return "".join((m.group(1) or "").split()).strip()


def _patch_urlencoded_field(raw_post: str, key: str, value: str) -> str:
    raw_txt = str(raw_post or "")
    key_txt = str(key or "").strip()
    if not key_txt:
        return raw_txt
    encoded_value = urllib.parse.quote_plus(str(value or ""))
    # Sustituye el valor existente preservando intacto el resto del payload (ViewState/otros tokens).
    pattern = rf"(^|&){re.escape(key_txt)}=[^&]*"
    repl = lambda m: f"{m.group(1)}{key_txt}={encoded_value}"
    patched, count = re.subn(pattern, repl, raw_txt, count=1)
    if count > 0:
        return patched
    if not raw_txt:
        return f"{key_txt}={encoded_value}"
    sep = "&" if not raw_txt.endswith("&") else ""
    return f"{raw_txt}{sep}{key_txt}={encoded_value}"


def _safe_resource_id(datos: "ValenciaTarget") -> str:
    rid = getattr(datos, "idRecurso", None)
    if rid in (None, ""):
        return "unknown"
    try:
        return str(int(rid))
    except Exception:
        return str(rid)


def _add_debug_event(telemetry: dict, *, kind: str, data: dict) -> None:
    telemetry.setdefault("events", []).append(
        {
            "ts": datetime.now().isoformat(),
            "kind": kind,
            "data": data,
        }
    )


async def _capture_dom_signature_snapshot(page: "Page", *, step: str, telemetry: dict) -> None:
    try:
        data = await page.evaluate(
            """(stepName) => {
                const short = (s, max=180) => {
                    const t = String(s || '').replace(/\\s+/g, ' ').trim();
                    return t.length > max ? t.slice(0, max) + '…' : t;
                };
                const q = (sel) => Array.from(document.querySelectorAll(sel));
                const buttons = q("button,input[type='button'],input[type='submit'],a.button,a[href]")
                    .map((el) => {
                        const text = short(el.innerText || el.value || el.getAttribute('title') || '');
                        const href = short(el.getAttribute('href') || '');
                        const id = short(el.id || '');
                        const cls = short(el.className || '');
                        return { text, href, id, cls };
                    })
                    .filter((it) => /firm|sign|accept|acept|acceder|certificat|certificado/i.test(it.text + ' ' + it.href))
                    .slice(0, 40);
                const afirmaAnchors = q("a[href^='afirma://'],a[href^='xalocafirma://']")
                    .map((a) => short(a.getAttribute("href") || a.href || ""))
                    .slice(0, 20);
                const forms = q("form")
                    .map((f) => short(f.getAttribute("action") || ""))
                    .filter((x) => /afirma|xalocafirma/i.test(x))
                    .slice(0, 20);
                return {
                    step: stepName,
                    url: String(window.location.href || ''),
                    title: String(document.title || ''),
                    readyState: String(document.readyState || ''),
                    frameCount: window.frames ? window.frames.length : 0,
                    hrefAfirma: String(window.__afirma_url || ''),
                    hrefAfirmaSource: String(window.__afirma_source || ''),
                    afirmaAnchors,
                    formsWithAfirmaAction: forms,
                    signatureRelevantButtons: buttons,
                };
            }""",
            step,
        )
        _add_debug_event(telemetry, kind="dom_snapshot", data=dict(data or {}))
    except Exception as exc:
        _add_debug_event(telemetry, kind="dom_snapshot_error", data={"step": step, "error": str(exc)})


async def _setup_afirma_debug(page: "Page", *, datos: "ValenciaTarget", telemetry: dict) -> None:
    if telemetry.get("hook_installed"):
        return

    async def _on_uri(uri: str) -> None:
        uri_txt = str(uri or "").strip()
        if not uri_txt:
            return
        _add_debug_event(
            telemetry,
            kind="afirma_uri_callback",
            data={"uri_prefix": uri_txt[:220], "source": "js_callback"},
        )
        logger.info("valencia.afirma.debug callback uri=%s", uri_txt[:160])

    try:
        await page.expose_function(_VALENCIA_HOOK_FN_NAME, _on_uri)
    except Exception:
        # Si ya estaba expuesta en reintentos, continuamos.
        pass

    hook_script = get_redsara_afirma_hook_script(
        block_external_launch=_should_block_external_afirma_launch()
    )
    block_flag = "true" if _should_block_external_afirma_launch() else "false"
    wrapped = f"({hook_script})('{_VALENCIA_HOOK_FN_NAME}', {block_flag})"
    try:
        await page.context.add_init_script(wrapped)
    except Exception as exc:
        _add_debug_event(telemetry, kind="add_init_script_error", data={"error": str(exc)})
    try:
        await page.evaluate(wrapped)
    except Exception as exc:
        _add_debug_event(telemetry, kind="evaluate_hook_error", data={"error": str(exc)})

    def _on_console(msg) -> None:
        try:
            text = msg.text if isinstance(msg.text, str) else msg.text()
        except Exception:
            text = ""
        uri = _extract_afirma_uri(text)
        if uri:
            _add_debug_event(
                telemetry,
                kind="afirma_uri_console",
                data={"uri_prefix": uri[:220], "raw": str(text)[:300]},
            )
            logger.info("valencia.afirma.debug console uri=%s", uri[:160])

    def _on_request(request) -> None:
        try:
            req_url = str(request.url or "")
        except Exception:
            req_url = ""
        method = str(getattr(request, "method", ""))
        post_data = ""
        try:
            if method.upper() == "POST":
                getter = getattr(request, "post_data", None)
                if callable(getter):
                    post_data = str(getter() or "")
                else:
                    post_data = str(getattr(request, "post_data", "") or "")
        except Exception:
            post_data = ""
        uri = _extract_afirma_uri(req_url)
        if uri:
            _add_debug_event(
                telemetry,
                kind="afirma_uri_request",
                data={"uri_prefix": uri[:220], "method": method},
            )
        elif "autofirma" in req_url.lower():
            _add_debug_event(
                telemetry,
                kind="autofirma_request",
                data={"url": req_url[:260], "method": method, "post_data_head": post_data[:2000]},
            )
        elif "fire-signature" in req_url.lower() or "localhost" in req_url.lower() or "127.0.0.1" in req_url.lower():
            _add_debug_event(
                telemetry,
                kind="fire_request",
                data={
                    "url": req_url[:260],
                    "method": method,
                    "resource_type": str(getattr(request, "resource_type", "")),
                    "post_data_head": post_data[:3000],
                },
            )

    def _on_response(response) -> None:
        try:
            res_url = str(response.url or "")
        except Exception:
            res_url = ""
        if "fire-signature" not in res_url.lower() and "autofirma" not in res_url.lower():
            return
        try:
            req = response.request
            method = str(getattr(req, "method", ""))
        except Exception:
            method = ""
        _add_debug_event(
            telemetry,
            kind="fire_response",
            data={
                "url": res_url[:260],
                "status": int(getattr(response, "status", 0) or 0),
                "ok": bool(getattr(response, "ok", False)),
                "method": method,
            },
        )
        try:
            low_url = res_url.lower()
            if (
                method.upper() == "POST"
                and ("fire-signature/public/afirma/retrieve" in low_url or "fire-signature/public/afirma/storage" in low_url)
            ):
                async def _capture_body(resp=response, url=res_url, m=method) -> None:
                    try:
                        txt = await resp.text()
                    except Exception as exc:
                        _add_debug_event(
                            telemetry,
                            kind="fire_response_body_error",
                            data={"url": url[:260], "method": m, "error": str(exc)[:220]},
                        )
                        return
                    _add_debug_event(
                        telemetry,
                        kind="fire_response_body",
                        data={"url": url[:260], "method": m, "body_head": str(txt or "")[:2000]},
                    )
                    low = str(url or "").lower()
                    if "fire-signature/public/afirma/retrieve" in low:
                        body_txt = str(txt or "")
                        if body_txt and not body_txt.upper().startswith("ERR"):
                            telemetry["_last_fire_retrieve_body"] = body_txt
                            _add_debug_event(
                                telemetry,
                                kind="afirma_retrieve_body_captured",
                                data={"len": len(body_txt)},
                            )

                asyncio.create_task(_capture_body())
        except Exception:
            pass

    def _on_request_failed(request) -> None:
        try:
            req_url = str(request.url or "")
            method = str(getattr(request, "method", ""))
            failure_text = ""
            uri = _extract_afirma_uri(req_url)
            if uri:
                telemetry["_last_afirma_uri"] = uri
                _add_debug_event(
                    telemetry,
                    kind="afirma_uri_request_failed",
                    data={"uri": uri, "method": method},
                )
            failure = getattr(request, "failure", None)
            if callable(failure):
                fobj = failure()
                if isinstance(fobj, dict):
                    failure_text = str(fobj.get("errorText", ""))
            _add_debug_event(
                telemetry,
                kind="fire_request_failed",
                data={"url": req_url[:260], "method": method, "failure": failure_text[:220]},
            )
        except RuntimeError:
            raise
        except Exception:
            pass

    def _on_page_error(exc) -> None:
        _add_debug_event(telemetry, kind="page_error", data={"error": str(exc)[:400]})

    def _on_framenavigated(frame) -> None:
        try:
            _add_debug_event(
                telemetry,
                kind="frame_navigated",
                data={"name": str(frame.name or ""), "url": str(frame.url or "")[:260]},
            )
        except Exception:
            pass

    async def _on_afirma_scheme_route(route, request) -> None:
        try:
            req_url = str(request.url or "")
        except Exception:
            req_url = ""
        # Store the FULL URI so the in-process bridge can parse rtservlet/fileid/key
        # (do NOT truncate here — truncation was silently breaking the bridge).
        if req_url and _AFIRMA_URI_RE.match(req_url):
            telemetry["_last_afirma_uri"] = req_url
        _add_debug_event(
            telemetry,
            kind="afirma_uri_route_abort",
            data={"url": req_url[:260], "method": str(getattr(request, "method", ""))},
        )
        try:
            await route.abort()
        except Exception as exc:
            _add_debug_event(
                telemetry,
                kind="afirma_uri_route_abort_error",
                data={"url": req_url[:260], "error": str(exc)[:300]},
            )
            await route.continue_()

    page.on("console", _on_console)
    page.on("request", _on_request)
    page.on("response", _on_response)
    page.on("requestfailed", _on_request_failed)
    page.on("framenavigated", _on_framenavigated)
    page.on("pageerror", _on_page_error)
    await page.context.route(re.compile(r"^(?:afirma|xalocafirma)://", re.IGNORECASE), _on_afirma_scheme_route)

    async def _on_retrieve_route(route, request) -> None:
        try:
            method = str(getattr(request, "method", "") or "").upper()
            if method != "POST":
                await route.continue_()
                return
            resp = await route.fetch()
            txt = await resp.text()
            body_txt = str(txt or "")
            body_txt_clean = body_txt.strip()
            if body_txt_clean and not body_txt_clean.upper().startswith("ERR"):
                telemetry["_last_fire_retrieve_body"] = body_txt_clean
                _add_debug_event(
                    telemetry,
                    kind="afirma_retrieve_body_captured_route",
                    data={"len": len(body_txt_clean), "raw_len": len(body_txt)},
                )
            else:
                _add_debug_event(
                    telemetry,
                    kind="afirma_retrieve_body_captured_route_empty",
                    data={"len": len(body_txt_clean), "raw_len": len(body_txt)},
                )
            await route.fulfill(response=resp, body=body_txt)
        except Exception as exc:
            _add_debug_event(telemetry, kind="afirma_retrieve_route_error", data={"error": str(exc)[:300]})
            await route.continue_()

    await page.context.route("**/fire-signature/public/afirma/retrieve", _on_retrieve_route)

    async def _on_success_route(route, request) -> None:
        try:
            url = str(request.url or "")
            method = str(getattr(request, "method", "") or "").upper()
            post_data = ""
            getter = getattr(request, "post_data", None)
            if callable(getter):
                post_data = str(getter() or "")
            else:
                post_data = str(getattr(request, "post_data", "") or "")
            if method != "POST":
                await route.continue_()
                return
            params_before = urllib.parse.parse_qs(post_data, keep_blank_values=True)
            before_batch = str((params_before.get("afirmabatchresult") or [""])[0] or "")
            before_cert = str((params_before.get("cert") or [""])[0] or "")
            is_batch_operation = str((params_before.get("isbatchop") or [""])[0] or "").strip().lower() == "true"

            signature_b64 = str(telemetry.get("_last_fire_signature_b64") or "").strip()
            retrieve_body = str(telemetry.get("_last_fire_retrieve_body") or "").strip()
            chosen_batch = (signature_b64 or retrieve_body) if is_batch_operation else ""
            new_post = post_data
            if is_batch_operation and chosen_batch and not before_batch:
                new_post = _patch_urlencoded_field(new_post, "afirmabatchresult", chosen_batch)
            elif not is_batch_operation and before_batch:
                new_post = _patch_urlencoded_field(new_post, "afirmabatchresult", "")
            cert_from_signature = _extract_cert_b64_from_signature(signature_b64)
            cert_b64 = cert_from_signature or _extract_signing_cert_b64()
            if cert_b64 and not before_cert:
                new_post = _patch_urlencoded_field(new_post, "cert", cert_b64)

            params_after = urllib.parse.parse_qs(new_post, keep_blank_values=True)
            body_changed = new_post != post_data

            _add_debug_event(
                telemetry,
                kind="afirma_success_service_rewrite",
                data={
                    "url": url[:260],
                    "before_batch_len": len(before_batch),
                    "after_batch_len": len(str((params_after.get("afirmabatchresult") or [""])[0] or "")),
                    "batch_source": (
                        "signature_b64"
                        if is_batch_operation and signature_b64
                        else ("retrieve_body" if is_batch_operation and retrieve_body else "none")
                    ),
                    "before_cert_len": len(before_cert),
                    "after_cert_len": len(str((params_after.get("cert") or [""])[0] or "")),
                    "cert_source": "signature_x509" if cert_from_signature else ("pfx_extract" if cert_b64 else "none"),
                    "is_batch_operation": is_batch_operation,
                    "body_changed": body_changed,
                    "route_mode": "continue",
                },
            )
            if body_changed:
                await route.continue_(post_data=new_post)
            else:
                await route.continue_()
        except Exception as exc:
            _add_debug_event(telemetry, kind="afirma_success_service_rewrite_error", data={"error": str(exc)[:300]})
            await route.continue_()

    await page.context.route("**/fire-signature/public/miniappletSuccessService", _on_success_route)

    telemetry["hook_installed"] = True
    _add_debug_event(
        telemetry,
        kind="debug_start",
        data={
            "idRecurso": _safe_resource_id(datos),
            "expediente": str(getattr(datos, "expediente", "") or ""),
            "url": str(page.url or ""),
        },
    )
    await _capture_dom_signature_snapshot(page, step="debug_start", telemetry=telemetry)


async def _flush_afirma_debug_artifacts(page: "Page", *, datos: "ValenciaTarget", telemetry: dict) -> None:
    if not _is_afirma_debug_enabled():
        return

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    rid = _safe_resource_id(datos)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = logs_dir / f"valencia_afirma_{rid}_{stamp}.json"
    html_path = logs_dir / f"valencia_afirma_{rid}_{stamp}.html"
    png_path = logs_dir / f"valencia_afirma_{rid}_{stamp}.png"

    try:
        telemetry["finished_at"] = datetime.now().isoformat()
        telemetry["final_url"] = str(page.url or "")
        json_path.write_text(json.dumps(telemetry, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("valencia.afirma.debug json=%s", json_path)
    except Exception as exc:
        logger.warning("valencia.afirma.debug no se pudo guardar json: %s", exc)
    try:
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        logger.info("valencia.afirma.debug html=%s", html_path)
    except Exception as exc:
        logger.warning("valencia.afirma.debug no se pudo guardar html: %s", exc)
    try:
        await page.screenshot(path=png_path, full_page=True)
        logger.info("valencia.afirma.debug png=%s", png_path)
    except Exception as exc:
        logger.warning("valencia.afirma.debug no se pudo guardar screenshot: %s", exc)


async def _install_fire_runtime_hooks(page: "Page", *, telemetry: dict) -> None:
    if not _is_afirma_deep_debug_enabled():
        return
    script = """() => {
        if (window.__xaloc_fire_diag_installed) {
            return { installed: false, already: true, url: String(window.location.href || '') };
        }
        window.__xaloc_fire_diag_installed = true;
        window.__xaloc_fire_diag = window.__xaloc_fire_diag || [];
        const push = (kind, data) => {
            try {
                window.__xaloc_fire_diag.push({
                    ts: new Date().toISOString(),
                    kind: String(kind || ''),
                    data: data || {}
                });
                if (window.__xaloc_fire_diag.length > 1200) {
                    window.__xaloc_fire_diag = window.__xaloc_fire_diag.slice(-800);
                }
            } catch (e) {}
        };
        const short = (v, max=240) => {
            const t = String(v == null ? '' : v);
            return t.length > max ? t.slice(0, max) + '...' : t;
        };
        const describeArg = (a) => {
            if (a == null) return { type: String(a) };
            if (typeof a === 'string') return { type: 'string', len: a.length, sample: short(a) };
            if (typeof a === 'number' || typeof a === 'boolean') return { type: typeof a, value: a };
            if (typeof a === 'function') return { type: 'function', name: String(a.name || '') };
            if (Array.isArray(a)) return { type: 'array', len: a.length };
            if (typeof a === 'object') return { type: 'object', keys: Object.keys(a).slice(0, 20) };
            return { type: typeof a };
        };
        const wrapFn = (obj, fnName) => {
            try {
                if (!obj || typeof obj[fnName] !== 'function') return false;
                const original = obj[fnName];
                if (original.__xaloc_wrapped) return true;
                const wrapped = function(...args) {
                    push('miniapplet_call', { fn: fnName, args: args.map((a) => describeArg(a)) });
                    try {
                        const out = original.apply(this, args);
                        push('miniapplet_return', { fn: fnName, result: describeArg(out) });
                        return out;
                    } catch (err) {
                        push('miniapplet_throw', { fn: fnName, error: short(err) });
                        throw err;
                    }
                };
                wrapped.__xaloc_wrapped = true;
                obj[fnName] = wrapped;
                return true;
            } catch (e) {
                push('wrap_error', { fn: fnName, error: short(e) });
                return false;
            }
        };

        if (window.MiniApplet) {
            ['sign', 'coSign', 'counterSign', 'setForceWSMode', 'setForceAFirma', 'cargarAppAfirma', 'setServlets', 'echo', 'getErrorType', 'getErrorMessage']
                .forEach((name) => wrapFn(window.MiniApplet, name));
            push('miniapplet_detected', {
                keys: Object.keys(window.MiniApplet).slice(0, 60),
                hasSign: typeof MiniApplet.sign === 'function'
            });
        } else {
            push('miniapplet_missing', { url: String(window.location.href || '') });
        }

        const oldOnError = window.onerror;
        window.onerror = function(message, source, lineno, colno, error) {
            push('window_onerror', {
                message: short(message),
                source: short(source),
                line: lineno || 0,
                column: colno || 0,
                error: short(error)
            });
            if (typeof oldOnError === 'function') {
                return oldOnError.apply(this, arguments);
            }
            return false;
        };
        window.addEventListener('unhandledrejection', (ev) => {
            push('unhandled_rejection', { reason: short(ev && ev.reason) });
        });

        try {
            const oldFetch = window.fetch;
            if (typeof oldFetch === 'function' && !oldFetch.__xaloc_wrapped) {
                const wrappedFetch = function(...args) {
                    const url = short(args && args[0] && args[0].url ? args[0].url : args[0]);
                    push('fetch_start', { url });
                    return oldFetch.apply(this, args)
                        .then((resp) => {
                            push('fetch_end', {
                                url,
                                status: resp ? resp.status : 0,
                                ok: !!(resp && resp.ok),
                                redirected: !!(resp && resp.redirected)
                            });
                            return resp;
                        })
                        .catch((err) => {
                            push('fetch_error', { url, error: short(err) });
                            throw err;
                        });
                };
                wrappedFetch.__xaloc_wrapped = true;
                window.fetch = wrappedFetch;
            }
        } catch (e) {
            push('fetch_wrap_error', { error: short(e) });
        }

        try {
            const xOpen = XMLHttpRequest.prototype.open;
            const xSend = XMLHttpRequest.prototype.send;
            if (!xOpen.__xaloc_wrapped) {
                XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                    this.__xaloc_url = short(url);
                    this.__xaloc_method = short(method);
                    return xOpen.call(this, method, url, ...rest);
                };
                XMLHttpRequest.prototype.open.__xaloc_wrapped = true;
            }
            if (!xSend.__xaloc_wrapped) {
                XMLHttpRequest.prototype.send = function(body) {
                    const url = this.__xaloc_url || '';
                    const method = this.__xaloc_method || '';
                    const bodyText = body == null ? '' : String(body);
                    push('xhr_send', { method, url, bodyLen: bodyText.length, bodySample: short(bodyText, 1200) });
                    this.addEventListener('load', () => {
                        push('xhr_load', { method, url, status: this.status || 0, readyState: this.readyState || 0 });
                    });
                    this.addEventListener('error', () => {
                        push('xhr_error', { method, url, status: this.status || 0 });
                    });
                    return xSend.call(this, body);
                };
                XMLHttpRequest.prototype.send.__xaloc_wrapped = true;
            }
        } catch (e) {
            push('xhr_wrap_error', { error: short(e) });
        }

        try {
            const WS = window.WebSocket;
            if (typeof WS === 'function' && !WS.__xaloc_wrapped) {
                const WrappedWS = function(url, protocols) {
                    const ws = new WS(url, protocols);
                    push('ws_create', { url: short(url), protocols: short(protocols) });
                    ws.addEventListener('open', () => push('ws_open', { url: short(url) }));
                    ws.addEventListener('close', (ev) => push('ws_close', { url: short(url), code: ev.code, reason: short(ev.reason) }));
                    ws.addEventListener('error', () => push('ws_error', { url: short(url) }));
                    ws.addEventListener('message', (ev) => {
                        const data = (ev && ev.data != null) ? String(ev.data) : '';
                        push('ws_message', { url: short(url), len: data.length, sample: short(data, 180) });
                    });
                    return ws;
                };
                WrappedWS.prototype = WS.prototype;
                WrappedWS.__xaloc_wrapped = true;
                window.WebSocket = WrappedWS;
            }
        } catch (e) {
            push('ws_wrap_error', { error: short(e) });
        }

        try {
            const submit = HTMLFormElement.prototype.submit;
            if (typeof submit === 'function' && !submit.__xaloc_wrapped) {
                HTMLFormElement.prototype.submit = function(...args) {
                    const pairs = [];
                    try {
                        const fd = new FormData(this);
                        for (const [k, v] of fd.entries()) {
                            const sval = String(v == null ? '' : v);
                            pairs.push({ key: short(k, 80), len: sval.length, sample: short(sval, 140) });
                            if (pairs.length >= 60) break;
                        }
                    } catch (e) {}
                    push('form_submit', {
                        id: short(this.id || ''),
                        action: short(this.action || ''),
                        method: short(this.method || ''),
                        fields: pairs
                    });
                    return submit.apply(this, args);
                };
                HTMLFormElement.prototype.submit.__xaloc_wrapped = true;
            }
        } catch (e) {
            push('form_wrap_error', { error: short(e) });
        }

        push('hook_ready', { url: String(window.location.href || '') });
        return { installed: true, url: String(window.location.href || ''), hasMiniApplet: !!window.MiniApplet };
    }"""
    try:
        await page.context.add_init_script(script)
    except Exception as exc:
        _add_debug_event(telemetry, kind="fire_hook_add_init_error", data={"error": str(exc)})
    try:
        data = await page.evaluate(script)
        _add_debug_event(telemetry, kind="fire_hook_install", data=dict(data or {}))
    except Exception as exc:
        _add_debug_event(telemetry, kind="fire_hook_install_error", data={"error": str(exc)})


async def _drain_fire_runtime_events(page: "Page", *, telemetry: dict, step: str, max_items: int = 300) -> None:
    if not _is_afirma_deep_debug_enabled():
        return
    try:
        data = await page.evaluate(
            """(limit) => {
                const all = Array.isArray(window.__xaloc_fire_diag) ? window.__xaloc_fire_diag.slice() : [];
                const kept = all.slice(-Math.max(1, Number(limit || 300)));
                window.__xaloc_fire_diag = [];
                return kept;
            }""",
            max_items,
        )
        items = list(data or [])
        if items:
            _add_debug_event(
                telemetry,
                kind="fire_runtime_events",
                data={"step": step, "count": len(items), "items": items},
            )
    except Exception as exc:
        _add_debug_event(telemetry, kind="fire_runtime_events_error", data={"step": step, "error": str(exc)})


async def _capture_fire_runtime_state(page: "Page", *, telemetry: dict, step: str) -> None:
    if not _is_afirma_deep_debug_enabled():
        return
    try:
        data = await page.evaluate(
            """(stepName) => {
                const q = (id) => document.getElementById(id);
                const txt = (x, max=400) => {
                    const s = String(x == null ? '' : x).replace(/\\s+/g, ' ').trim();
                    return s.length > max ? s.slice(0, max) + '...' : s;
                };
                const prog = q('progressDialog');
                const errorType = q('inputerrortype');
                const errorMsg = q('inputerrormsg');
                const cert = q('cert');
                const batch = q('afirmaBatchResult');
                const errorNode = q('errorMsg');
                const signBtn = q('buttonSign');
                const forms = Array.from(document.querySelectorAll('form')).slice(0, 10).map((f) => ({
                    id: txt(f.id || '', 120),
                    action: txt(f.getAttribute('action') || '', 220),
                    method: txt(f.getAttribute('method') || '', 20)
                }));
                let miniInfo = { exists: !!window.MiniApplet };
                if (window.MiniApplet) {
                    miniInfo = {
                        exists: true,
                        hasSign: typeof MiniApplet.sign === 'function',
                        hasEcho: typeof MiniApplet.echo === 'function',
                        hasSetForceWSMode: typeof MiniApplet.setForceWSMode === 'function',
                        hasSetForceAFirma: typeof MiniApplet.setForceAFirma === 'function',
                    };
                    try { miniInfo.echo = txt(MiniApplet.echo(), 120); } catch (e) { miniInfo.echoError = txt(e, 160); }
                    try { miniInfo.errorType = txt(MiniApplet.getErrorType && MiniApplet.getErrorType(), 220); } catch (e) { miniInfo.errorTypeError = txt(e, 160); }
                    try { miniInfo.errorMessage = txt(MiniApplet.getErrorMessage && MiniApplet.getErrorMessage(), 220); } catch (e) { miniInfo.errorMessageError = txt(e, 160); }
                }
                return {
                    step: stepName,
                    ts: new Date().toISOString(),
                    url: String(window.location.href || ''),
                    title: String(document.title || ''),
                    readyState: String(document.readyState || ''),
                    progressDialogVisible: !!(prog && prog.style.display !== 'none'),
                    progressDialogStyle: txt(prog ? prog.getAttribute('style') : ''),
                    progressText: txt((q('progressText') || {}).innerText || ''),
                    errorTypeValue: txt(errorType ? errorType.value : '', 240),
                    errorMsgValue: txt(errorMsg ? errorMsg.value : '', 240),
                    errorText: txt(errorNode ? errorNode.innerText : '', 300),
                    certLen: cert && cert.value ? String(cert.value).length : 0,
                    batchResultLen: batch && batch.value ? String(batch.value).length : 0,
                    signButtonVisible: !!(signBtn && signBtn.offsetParent !== null),
                    signButtonDisabled: !!(signBtn && signBtn.disabled),
                    forms,
                    afirmaUrl: txt(window.__afirma_url || '', 240),
                    afirmaSource: txt(window.__afirma_source || '', 120),
                    miniApplet: miniInfo,
                };
            }""",
            step,
        )
        _add_debug_event(telemetry, kind="fire_runtime_state", data=dict(data or {}))
    except Exception as exc:
        _add_debug_event(telemetry, kind="fire_runtime_state_error", data={"step": step, "error": str(exc)})


async def _sample_fire_runtime(page: "Page", *, telemetry: dict, step: str, total_ms: int, interval_ms: int = 1000) -> None:
    if not _is_afirma_deep_debug_enabled():
        return
    loops = max(1, total_ms // max(200, interval_ms))
    for idx in range(loops):
        await _capture_fire_runtime_state(page, telemetry=telemetry, step=f"{step}_tick_{idx + 1}")
        await _drain_fire_runtime_events(page, telemetry=telemetry, step=f"{step}_tick_{idx + 1}")
        if idx < loops - 1:
            await page.wait_for_timeout(interval_ms)


def _tail_text_file(path: Path, *, max_chars: int = 2000) -> dict:
    out: dict[str, object] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return out
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        out["size"] = len(content)
        out["tail"] = content[-max_chars:]
    except Exception as exc:
        out["read_error"] = str(exc)
    return out


def _read_bridge_expected_contract() -> dict:
    path = Path("/tmp/xaloc_afirma_sign_bridge_trace.json")
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "error": str(exc)[:200]}
    return {
        "exists": True,
        "path": str(path),
        "ok": bool(raw.get("ok")),
        "error": str(raw.get("error") or ""),
        "expected_contract": raw.get("expected_contract") or {},
        "retrieved_hints": raw.get("retrieved_hints") or {},
        "sign_profile_used": raw.get("sign_profile_used") or {},
        "signature_b64_len": int(raw.get("signature_b64_len") or 0),
        "put_selected": raw.get("put_selected") or {},
        "put_attempts": (raw.get("put_attempts") or [])[:5],
    }


async def _probe_justificante_target(page: "Page") -> dict:
    try:
        data = await page.evaluate(
            """() => {
                const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
                const elements = Array.from(document.querySelectorAll('input,button,a')).slice(0, 400);
                const candidates = [];
                for (const el of elements) {
                    const text = norm(el.innerText || el.value || el.getAttribute('title') || '');
                    const href = norm(el.getAttribute('href') || '');
                    const onclick = norm(el.getAttribute('onclick') || '');
                    const dataUrl = norm(el.getAttribute('data-clickable-url') || '');
                    const blob = `${text} ${href} ${onclick} ${dataUrl}`.toLowerCase();
                    if (!blob) continue;
                    const looksLikeReceipt =
                        blob.includes('justificant') ||
                        blob.includes('justificante') ||
                        blob.includes('descàrrega') ||
                        blob.includes('descarga') ||
                        blob.includes('.pdf') ||
                        blob.includes('formdescargas');
                    if (!looksLikeReceipt) continue;
                    candidates.push({
                        tag: String(el.tagName || '').toLowerCase(),
                        id: norm(el.id || ''),
                        name: norm(el.getAttribute('name') || ''),
                        text: text.slice(0, 180),
                        href: href.slice(0, 500),
                        onclick: onclick.slice(0, 500),
                        data_clickable_url: dataUrl.slice(0, 500),
                        visible: !!(el.offsetParent !== null),
                    });
                }
                return {
                    ok: true,
                    title: String(document.title || ''),
                    url: String(window.location.href || ''),
                    body_text_head: norm(document.body?.innerText || '').slice(0, 1600),
                    candidates: candidates.slice(0, 20),
                };
            }"""
        )
        return dict(data or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _replay_bridge_put_with_browser_session(page: "Page", *, telemetry: dict) -> None:
    """
    Reenvia el put de FIRe desde el contexto HTTP del navegador para mantener
    cookies/sesion del flujo web cuando el bridge externo no comparte sesion.
    """
    path = Path("/tmp/xaloc_afirma_sign_bridge_trace.json")
    if not path.exists():
        _add_debug_event(telemetry, kind="afirma_bridge_replay_skip", data={"reason": "trace_missing", "path": str(path)})
        return
    try:
        trace = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        _add_debug_event(telemetry, kind="afirma_bridge_replay_skip", data={"reason": "trace_parse_error", "error": str(exc)[:200]})
        return

    payload = (trace.get("put_payload_selected") or {}).get("body") or {}
    url = str((trace.get("put_payload_selected") or {}).get("url") or trace.get("storage_url") or "").strip()
    try:
        signature_b64 = str(trace.get("signature_b64") or "").strip()
        if signature_b64:
            telemetry["_last_fire_signature_b64"] = signature_b64
            _add_debug_event(
                telemetry,
                kind="afirma_signature_b64_seeded_from_bridge",
                data={"len": len(signature_b64)},
            )
    except Exception:
        pass
    try:
        dat_seed = str((payload or {}).get("dat") or "")
        if dat_seed and not str(telemetry.get("_last_fire_retrieve_body") or "").strip():
            telemetry["_last_fire_retrieve_body"] = dat_seed
            _add_debug_event(
                telemetry,
                kind="afirma_retrieve_body_seeded_from_bridge_put",
                data={"len": len(dat_seed)},
            )
    except Exception:
        pass
    if not url or not isinstance(payload, dict):
        _add_debug_event(
            telemetry,
            kind="afirma_bridge_replay_skip",
            data={"reason": "missing_payload_or_url", "url": url, "has_payload": bool(payload)},
        )
        return

    try:
        resp = await page.context.request.post(url, form=payload, timeout=30_000)
        body = (await resp.text())[:400]
        _add_debug_event(
            telemetry,
            kind="afirma_bridge_replay_result",
            data={
                "url": url,
                "status": int(resp.status),
                "ok": bool(resp.ok),
                "body_head": body,
                "payload_head": {k: (str(v)[:80] if k != "dat" else f"len={len(str(v))}") for k, v in payload.items()},
            },
        )
    except Exception as exc:
        _add_debug_event(
            telemetry,
            kind="afirma_bridge_replay_error",
            data={"url": url, "error": str(exc)[:300]},
        )


async def _collect_afirma_host_diag(*, telemetry: dict, step: str) -> None:
    if not _is_afirma_deep_debug_enabled():
        return
    files = [
        Path(os.getenv("XALOC_AFIRMA_URI_LOG") or "/tmp/xaloc_afirma_uri.log"),
        Path(os.getenv("XALOC_AFIRMA_URI_LATEST") or "/tmp/xaloc_afirma_uri.latest"),
        Path(os.getenv("XALOC_AFIRMA_PROXY_READY") or "/tmp/xaloc_afirma_proxy.ready"),
        Path(os.getenv("XALOC_AFIRMA_PROXY_PID") or "/tmp/xaloc_afirma_proxy.pid"),
        Path("/tmp/xaloc_afirma_proxy.log"),
        Path("/tmp/xaloc_afirma_native.log"),
        Path("/tmp/xaloc_afirma_sign_probe.log"),
        Path("/tmp/xaloc_afirma_sign_bridge.log"),
        Path("/tmp/xaloc_afirma_sign_bridge_trace.json"),
        Path("/tmp/autofirma-always-on.log"),
    ]
    file_diag = [_tail_text_file(p) for p in files]

    process_diag = ""
    socket_diag = ""
    try:
        proc = await asyncio.create_subprocess_shell(
            "ps -ef | grep -E 'autofirma|afirma-handler|autofirma_proxy' | grep -v grep || true",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        process_diag = (stdout or b"").decode("utf-8", errors="ignore")[-2400:]
    except Exception as exc:
        process_diag = f"error:{exc}"
    try:
        proc = await asyncio.create_subprocess_shell(
            "(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null || true)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        socket_diag = (stdout or b"").decode("utf-8", errors="ignore")[-4000:]
    except Exception as exc:
        socket_diag = f"error:{exc}"

    _add_debug_event(
        telemetry,
        kind="fire_host_diag",
        data={
            "step": step,
            "files": file_diag,
            "processes": process_diag,
            "sockets": socket_diag,
        },
    )


async def _click_first_available(
    page: "Page",
    selectors: list[str],
    *,
    step: str,
    required: bool = True,
) -> bool:
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        for idx in range(count):
            candidate = loc.nth(idx)
            try:
                if not await candidate.is_visible():
                    continue
                if await candidate.is_disabled():
                    continue
                await candidate.click()
                await page.wait_for_load_state("networkidle")
                logger.info("valencia.run_confirmacion -> %s ok selector=%s index=%s", step, selector, idx)
                return True
            except Exception:
                try:
                    await candidate.click(force=True)
                    await page.wait_for_load_state("networkidle")
                    logger.info(
                        "valencia.run_confirmacion -> %s ok selector=%s index=%s forced=1",
                        step,
                        selector,
                        idx,
                    )
                    return True
                except Exception:
                    continue
    if required:
        raise RuntimeError(f"valencia.confirmacion: no se encontro elemento para {step}")
    logger.warning("valencia.run_confirmacion -> %s no encontrado (continuando)", step)
    return False


async def _click_acceder_second_preferred(page: "Page") -> None:
    selectors = [
        'a[title*="Firma con certificado local"]',
        'a.button:has-text("Acceder")',
        'a:has-text("Acceder")',
    ]
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        if count <= 0:
            continue
        # Si hay dos o mas, usar el segundo. Si no, usar el primero.
        index = 1 if count >= 2 else 0
        candidate = loc.nth(index)
        try:
            await candidate.click()
            await page.wait_for_load_state("networkidle")
            logger.info(
                "valencia.run_confirmacion -> click_acceder_autofirma ok selector=%s index=%s",
                selector,
                index,
            )
            return
        except Exception:
            try:
                await candidate.click(force=True)
                await page.wait_for_load_state("networkidle")
                logger.info(
                    "valencia.run_confirmacion -> click_acceder_autofirma ok selector=%s index=%s forced=1",
                    selector,
                    index,
                )
                return
            except Exception:
                continue
    raise RuntimeError("valencia.confirmacion: no se encontro elemento para click_acceder_autofirma")


async def _presentar_state(page: "Page") -> dict:
    return await page.evaluate(
        """() => {
            const nodes = Array.from(document.querySelectorAll('input[type="submit"][value="Presentar"]'));
            const seleccionarNodes = Array.from(document.querySelectorAll('input[type="submit"][value="Seleccionar"]'));
            const details = nodes.slice(0, 5).map((el) => ({
                id: String(el.id || ''),
                name: String(el.name || ''),
                className: String(el.className || ''),
                disabled: !!el.disabled,
                visible: !!(el.offsetParent !== null),
            }));
            const disabledVisible = details.some((d) => d.visible && d.disabled);
            const enabledVisible = details.some((d) => d.visible && !d.disabled);
            return {
                url: String(window.location.href || ''),
                count: nodes.length,
                disabledVisible,
                enabledVisible,
                seleccionarVisibleCount: seleccionarNodes.filter((el) => !!(el.offsetParent !== null) && !el.disabled).length,
                details,
            };
        }"""
    )


async def _try_click_cookie_accept(page: "Page") -> None:
    cookie = page.locator("#cookieAcceptBarConfirm")
    if await cookie.count() <= 0:
        return
    try:
        if await cookie.first.is_visible():
            await cookie.first.click()
            await page.wait_for_timeout(250)
            logger.info("valencia.run_confirmacion -> cookie_accept clicked")
    except Exception:
        pass


async def _click_presentar_with_recovery(page: "Page", *, telemetry: dict, datos: "ValenciaTarget") -> None:
    selectors = [
        '[id="j_id1929771016_1_7c0efcb1:j_id1929771016_1_7c0eff57"]',
        'input[type="submit"][value="Presentar"]',
    ]
    last_state: dict | None = None
    disabled_seen = False
    attempted_reupload = False

    for attempt in range(1, 4):
        clicked = await _click_first_available(
            page,
            selectors=selectors,
            step=f"click_presentar_try_{attempt}",
            required=False,
        )
        if clicked:
            logger.info("valencia.run_confirmacion -> click_presentar ok attempt=%s", attempt)
            return

        state = await _presentar_state(page)
        last_state = state
        _add_debug_event(telemetry, kind="presentar_state", data={"attempt": attempt, **state})

        if state.get("disabledVisible"):
            disabled_seen = True
            logger.warning(
                "valencia.run_confirmacion -> presentar visible pero deshabilitado attempt=%s url=%s",
                attempt,
                state.get("url"),
            )
            seleccionar_visible = int(state.get("seleccionarVisibleCount") or 0)
            if seleccionar_visible > 0 and not attempted_reupload:
                files = [Path(str(p)) for p in (getattr(datos, "archivos_para_subir", None) or []) if Path(str(p)).exists()]
                if files:
                    attempted_reupload = True
                    logger.warning(
                        "valencia.run_confirmacion -> presentar deshabilitado con seleccionar_visible=%s. Reintentando upload documentos=%s",
                        seleccionar_visible,
                        len(files),
                    )
                    from .common import upload_documents

                    await upload_documents(page, files)

            await _try_click_cookie_accept(page)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            if attempt < 3:
                await page.reload(wait_until="domcontentloaded")
                await page.wait_for_load_state("networkidle")
            continue

        if attempt < 3:
            await page.wait_for_timeout(1000)

    if disabled_seen:
        raise RuntimeError(
            "valencia.confirmacion: boton Presentar detectado pero deshabilitado. "
            f"state={last_state}"
        )
    raise RuntimeError(f"valencia.confirmacion: no se encontro elemento para click_presentar. state={last_state}")


async def _ensure_detalle_before_presentar(page: "Page", config: "ValenciaConfig", *, telemetry: dict) -> None:
    present_locator = page.locator('input[type="submit"][value="Presentar"]')
    if await present_locator.count() > 0:
        return

    save_selectors = [
        config.save_form_selector,
        'input[type="submit"][value*="Guardar"]',
        'button:has-text("Guardar")',
    ]
    last_url = str(page.url or "")
    for attempt in range(1, 5):
        current_url = str(page.url or "")
        if await present_locator.count() > 0:
            return

        _add_debug_event(
            telemetry,
            kind="ensure_detalle_attempt",
            data={"attempt": attempt, "url": current_url, "present_count": await present_locator.count()},
        )

        if "formulario.xhtml" in current_url:
            clicked_save = False
            for selector in save_selectors:
                loc = page.locator(selector)
                if await loc.count() <= 0:
                    continue
                try:
                    candidate = loc.first
                    if await candidate.is_visible() and not await candidate.is_disabled():
                        await candidate.click(no_wait_after=True)
                        clicked_save = True
                        logger.info(
                            "valencia.run_confirmacion -> ensure_detalle click save attempt=%s selector=%s",
                            attempt,
                            selector,
                        )
                        break
                except Exception:
                    continue
            if not clicked_save:
                logger.warning(
                    "valencia.run_confirmacion -> ensure_detalle sin boton save usable attempt=%s url=%s",
                    attempt,
                    current_url,
                )

        try:
            await page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass
        await page.wait_for_timeout(700 * attempt)

        if await present_locator.count() > 0:
            return

        # Si el DOM no muta y seguimos en formulario, forzamos refresh para intentar salir de estado intermedio.
        if str(page.url or "") == last_url and "formulario.xhtml" in str(page.url or "") and attempt >= 2:
            try:
                await page.reload(wait_until="domcontentloaded")
            except Exception:
                pass
        last_url = str(page.url or "")


def _payload_for_storage(datos: "ValenciaTarget") -> dict:
    payload = dict(getattr(datos, "payload", {}) or {})
    payload.setdefault("idRecurso", getattr(datos, "idRecurso", None))
    payload.setdefault("expediente", getattr(datos, "expediente", ""))
    payload.setdefault("fase_procedimiento", getattr(datos, "fase_procedimiento", ""))
    payload.setdefault("tipodecliente", getattr(datos, "tipodecliente", ""))
    payload.setdefault("nif", getattr(datos, "nif", ""))
    payload.setdefault("nifempresa", getattr(datos, "nifempresa", ""))
    payload.setdefault("nombre", getattr(datos, "nombre", ""))
    payload.setdefault("apellido1", getattr(datos, "apellido1", ""))
    payload.setdefault("apellido2", getattr(datos, "apellido2", ""))
    payload.setdefault("nombrefiscal", getattr(datos, "nombrefiscal", ""))
    # Alias esperados por client_identity_from_payload para persona juridica.
    empresa = str(getattr(datos, "nombrefiscal", "") or "").strip()
    if empresa:
        payload.setdefault("empresa", empresa)
        payload.setdefault("razon_social", empresa)
        payload.setdefault("cliente_razon_social", empresa)
        payload.setdefault("Nombrefiscal", empresa)
    return payload


def _valencia_afirma_wait_timeout_ms() -> int:
    raw = (os.getenv("VALENCIA_AFIRMA_RESULT_TIMEOUT_MS") or "180000").strip()
    try:
        return max(30_000, int(raw))
    except Exception:
        return 180_000


async def _wait_post_sign_ready_for_receipt(page: "Page", *, telemetry: dict) -> None:
    selector = _VALENCIA_JUSTIFICANTE_SELECTORS[0]
    timeout_ms = _valencia_afirma_wait_timeout_ms()
    loop = asyncio.get_event_loop()
    start_ts = loop.time()
    deadline = start_ts + (timeout_ms / 1000)
    last_diag: dict | None = None
    consecutive_error_hits = 0
    while loop.time() < deadline:
        for candidate_selector in _VALENCIA_JUSTIFICANTE_SELECTORS:
            try:
                btn = page.locator(candidate_selector).first
                if await btn.count() > 0 and await btn.is_visible():
                    logger.info(
                        "valencia.afirma post-sign listo: boton justificante visible selector=%s",
                        candidate_selector,
                    )
                    return
            except Exception:
                continue

        try:
            last_diag = await page.evaluate(
                """(sel) => {
                    const btn = document.querySelector(sel);
                    const txt = String(document.body?.innerText || '').slice(0, 4000).toLowerCase();
                    const url = String(window.location.href || '');
                    const hasErrorText =
                        txt.includes('error') ||
                        txt.includes('time out') ||
                        txt.includes('timeout') ||
                        txt.includes('caducat') ||
                        txt.includes('caducada') ||
                        txt.includes('no s\\'ha pogut');
                    const isErrorPage =
                        txt.includes('pagina de error') ||
                        txt.includes('página de error') ||
                        txt.includes('dificultad técnica') ||
                        txt.includes('dificultat tècnica') ||
                        txt.includes('s\\'ha produït un error en el servidor');
                    const isSuccessPage =
                        url.includes('/justificanteCompulsado/') ||
                        txt.includes('sol·licitud presentada') ||
                        txt.includes('solicitud presentada') ||
                        txt.includes('número d\\'instància') ||
                        txt.includes('numero de instancia');
                    const fireErrorText = String(document.getElementById('errorMsg')?.innerText || '').trim();
                    const fireErrorType = String(document.getElementById('inputerrortype')?.value || '').trim();
                    const fireErrorMsg = String(document.getElementById('inputerrormsg')?.value || '').trim();
                    const progress = document.getElementById('progressDialog');
                    const progressVisible = !!(progress && progress.style.display !== 'none');
                    const progressText = String(document.getElementById('progreso')?.innerText || '').trim();
                    const receiptCandidates = Array.from(document.querySelectorAll('input,button,a'))
                        .map((el) => ({
                            text: String(el.innerText || el.value || el.getAttribute('title') || '').replace(/\\s+/g, ' ').trim(),
                            href: String(el.getAttribute('href') || '').trim(),
                            onclick: String(el.getAttribute('onclick') || '').trim(),
                            dataUrl: String(el.getAttribute('data-clickable-url') || '').trim(),
                            visible: !!(el.offsetParent !== null),
                        }))
                        .filter((it) => {
                            const blob = `${it.text} ${it.href} ${it.onclick} ${it.dataUrl}`.toLowerCase();
                            return blob.includes('justificant') ||
                                   blob.includes('justificante') ||
                                   blob.includes('descàrrega') ||
                                   blob.includes('descarga') ||
                                   blob.includes('.pdf') ||
                                   blob.includes('formdescargas');
                        })
                        .slice(0, 12);
                    return {
                        url,
                        ready: String(document.readyState || ''),
                        has_btn: !!btn,
                        btn_visible: !!(btn && btn.offsetParent !== null),
                        afirma_url: String(window.__afirma_url || ''),
                        afirma_source: String(window.__afirma_source || ''),
                        has_error_text: hasErrorText,
                        is_error_page: isErrorPage,
                        is_success_page: isSuccessPage,
                        fire_error_text: fireErrorText,
                        fire_error_type: fireErrorType,
                        fire_error_msg: fireErrorMsg,
                        progress_visible: progressVisible,
                        progress_text: progressText,
                        body_text_head: txt.slice(0, 1200),
                        receipt_candidates: receiptCandidates,
                    };
                }""",
                selector,
            )
            if isinstance(last_diag, dict) and last_diag.get("has_btn") and last_diag.get("btn_visible"):
                logger.info("valencia.afirma post-sign listo via DOM snapshot")
                return
            if isinstance(last_diag, dict) and last_diag.get("is_success_page"):
                logger.info("valencia.afirma post-sign listo via success page heuristic")
                return
            if isinstance(last_diag, dict) and last_diag.get("receipt_candidates"):
                logger.info("valencia.afirma post-sign listo via receipt heuristic")
                return

            if isinstance(last_diag, dict):
                elapsed_ms = int((loop.time() - start_ts) * 1000)
                url_now = str(last_diag.get("url") or "")
                fire_error_type = str(last_diag.get("fire_error_type") or "").strip()
                fire_error_msg = str(last_diag.get("fire_error_msg") or "").strip()
                fire_error_text = str(last_diag.get("fire_error_text") or "").strip()
                progress_visible = bool(last_diag.get("progress_visible"))
                has_error_text = bool(last_diag.get("has_error_text"))
                is_error_page = bool(last_diag.get("is_error_page"))
                is_success_page = bool(last_diag.get("is_success_page"))
                has_receipt_candidates = bool(last_diag.get("receipt_candidates"))
                in_presentar_instancia = "/presentarInstancia/" in url_now
                generic_fire_text = fire_error_text.lower() in {
                    "ocurrió un error en la operación de firma",
                    "ha ocurrido un error en la operación de firma",
                }
                hard_fire_error = bool(
                    (fire_error_type or fire_error_msg) and not is_success_page and elapsed_ms >= 45_000
                )
                explicit_error_page = bool(
                    is_error_page
                    and not is_success_page
                    and not in_presentar_instancia
                    and not progress_visible
                    and not has_receipt_candidates
                    and elapsed_ms >= 45_000
                )
                stuck_presentar_error = bool(
                    in_presentar_instancia
                    and has_error_text
                    and not is_success_page
                    and not progress_visible
                    and not has_receipt_candidates
                    and elapsed_ms >= 120_000
                )
                stale_generic_error = bool(
                    generic_fire_text
                    and not is_success_page
                    and not in_presentar_instancia
                    and not progress_visible
                    and elapsed_ms >= 60_000
                )

                should_count_error = bool(
                    hard_fire_error or explicit_error_page or stuck_presentar_error or stale_generic_error
                )
            else:
                should_count_error = False

            if should_count_error:
                consecutive_error_hits += 1
                if consecutive_error_hits >= 3:
                    if isinstance(last_diag, dict):
                        last_diag["bridge_expected"] = _read_bridge_expected_contract()
                    _add_debug_event(
                        telemetry,
                        kind="afirma_post_sign_error_detected",
                        data={"diag": last_diag},
                    )
                    raise RuntimeError(
                        "valencia.afirma: FIRe reporta error tras firma y no publica justificante. "
                        f"diag={last_diag}"
                    )
            else:
                consecutive_error_hits = 0
        except RuntimeError:
            raise
        except Exception:
            pass

        try:
            await page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass
        await page.wait_for_timeout(500)

    _add_debug_event(
        telemetry,
        kind="afirma_post_sign_timeout",
        data={
            "selector": selector,
            "diag": last_diag or {},
            "bridge_expected": _read_bridge_expected_contract(),
        },
    )
    raise RuntimeError(
        "valencia.afirma: timeout esperando refresco post-firma y boton de justificante. "
        f"selector={selector} diag={last_diag} bridge={_read_bridge_expected_contract()}"
    )


def _detect_miniapplet_storage_put(telemetry: dict) -> bool:
    """
    Returns True if a successful FIRe storage PUT was already captured from
    MiniApplet's own browser-side XHR request (i.e. before our in-process code runs).
    This means MiniApplet completed its own trifase signing using session cookies.
    """
    for ev in telemetry.get("events") or []:
        if ev.get("kind") != "fire_response_body":
            continue
        d = ev.get("data") or {}
        url = str(d.get("url") or "").lower()
        body = str(d.get("body_head") or "").strip().upper()
        if "fire-signature/public/afirma/storage" in url and body == "OK":
            return True
    return False


async def _execute_fire_signing_inprocess(page: "Page", *, telemetry: dict, signing_frame=None) -> None:
    """
    Execute FIRe 3-phase signing protocol in-process using browser session.
    Replaces the subprocess-based _maybe_force_afirma_handler.

    signing_frame: the Playwright Frame where buttonSign was clicked (if in an iframe).
    Used to read window.__afirma_url and to submit formSign from the correct context.
    """
    await _capture_fire_runtime_state(page, telemetry=telemetry, step="before_fire_inprocess")
    await _drain_fire_runtime_events(page, telemetry=telemetry, step="before_fire_inprocess")

    # ── URI acquisition ──────────────────────────────────────────────────
    uri_js = ""
    uri_evt = _latest_afirma_uri_from_telemetry(telemetry)
    if uri_evt and _AFIRMA_URI_RE.match(uri_evt):
        uri_js = uri_evt
        _add_debug_event(telemetry, kind="fire_inprocess_uri_immediate", data={"uri_prefix": uri_js[:220]})

    if not uri_js:
        # Check main page and same-origin iframes in one JS call.
        try:
            uri_js = await page.evaluate("""() => {
                const u = String(window.__afirma_url || '').trim();
                if (u) return u;
                for (const f of Array.from(document.querySelectorAll('iframe'))) {
                    try { const w = f.contentWindow; if (w && w.__afirma_url) return String(w.__afirma_url).trim(); } catch (_e) {}
                }
                return '';
            }""")
        except Exception:
            uri_js = ""
        uri_js = str(uri_js or "").strip()

    if not uri_js or not _AFIRMA_URI_RE.match(uri_js):
        start_url = str(page.url or "")
        for _ in range(30):  # ~15s
            uri_evt = _latest_afirma_uri_from_telemetry(telemetry)
            if uri_evt and _AFIRMA_URI_RE.match(uri_evt):
                uri_js = uri_evt
                break
            try:
                val = await page.evaluate("""() => {
                    const u = String(window.__afirma_url || '').trim();
                    if (u) return u;
                    for (const f of Array.from(document.querySelectorAll('iframe'))) {
                        try { const w = f.contentWindow; if (w && w.__afirma_url) return String(w.__afirma_url).trim(); } catch (_e) {}
                    }
                    return '';
                }""")
                val = str(val or "").strip()
                if val and _AFIRMA_URI_RE.match(val):
                    uri_js = val
                    break
            except Exception:
                pass
            await page.wait_for_timeout(500)
            current_url = str(page.url or "")
            if current_url != start_url:
                _add_debug_event(
                    telemetry,
                    kind="fire_inprocess_navigated_without_uri",
                    data={"from": start_url, "to": current_url},
                )
                return

    if not uri_js or not _AFIRMA_URI_RE.match(uri_js):
        await _capture_fire_runtime_state(page, telemetry=telemetry, step="fire_inprocess_no_uri")
        await _drain_fire_runtime_events(page, telemetry=telemetry, step="fire_inprocess_no_uri")
        raise RuntimeError(
            "valencia.fire_signing: no afirma:// URI captured after clicking Firmar"
        )

    _add_debug_event(
        telemetry,
        kind="fire_inprocess_uri_captured",
        data={"uri_prefix": uri_js[:220]},
    )

    # ── In-process FIRe 3-phase ──────────────────────────────────────────
    pfx_path = os.getenv("PLAYWRIGHT_CERT_PATH") or "/data/certificates/certificate.pfx"
    pfx_password = os.getenv("PLAYWRIGHT_CERT_PASSWORD") or ""

    # Check if MiniApplet already PUT a valid signature to FIRe storage via its
    # own browser-side trifase protocol (XHR with session cookies). In that case
    # skip our CLI-based re-signing to avoid overwriting a valid trifase signature
    # with a local one that the server would reject.
    _miniapplet_already_signed = _detect_miniapplet_storage_put(telemetry)
    if _miniapplet_already_signed:
        _add_debug_event(
            telemetry,
            kind="fire_inprocess_skip_resign",
            data={"reason": "miniapplet_put_detected_before_inprocess"},
        )
        logger.info(
            "valencia.fire_signing: MiniApplet already PUT to storage – skipping in-process re-signing"
        )
        # Wait briefly for MiniApplet to populate cert/form fields asynchronously.
        await page.wait_for_timeout(2000)
        result = FireSigningResult(
            ok=True,
            signature_b64="",
            put_status=0,
            put_body="",
            trace={"skipped": "miniapplet_put_detected"},
            error="",
        )
    else:
        result = await execute_fire_signing(
            page.context.request,
            uri_js,
            pfx_path,
            pfx_password,
            logger=logger,
        )

    # Seed telemetry with signature BEFORE MiniApplet callback can fire
    if result.signature_b64:
        telemetry["_last_fire_signature_b64"] = result.signature_b64
        _add_debug_event(
            telemetry,
            kind="fire_inprocess_signature_seeded",
            data={"len": len(result.signature_b64)},
        )

    _add_debug_event(
        telemetry,
        kind="fire_inprocess_result",
        data={"ok": result.ok, "error": result.error[:300], "trace": result.trace},
    )

    if not result.ok:
        raise RuntimeError(f"valencia.fire_signing: in-process signing failed: {result.error}")

    logger.info("valencia.fire_signing: in-process FIRe signing completed OK")

    # ── Trigger miniappletSuccessService ─────────────────────────────────
    # MiniApplet's afirma:// launch was blocked by our JS hooks, so it never
    # calls miniappletSuccessService to notify the web app. We must emulate
    # the callback using FIRe's own form to preserve transaction/session fields.
    cert_b64 = _extract_signing_cert_b64()
    cert_from_sig = _extract_cert_b64_from_signature(result.signature_b64)
    final_cert = cert_from_sig or cert_b64

    submit_info = await page.evaluate(
        """(payload) => {
            const signatureB64 = String(payload?.signatureB64 || '');
            const certB64 = String(payload?.certB64 || '');
            // Search for miniappletSuccessService URL in page scripts
            var successUrl = '';
            var scripts = document.querySelectorAll('script');
            for (var i = 0; i < scripts.length; i++) {
                var txt = scripts[i].textContent || '';
                var match = txt.match(/(https?:\\/\\/[^"'\\s]*fire-signature\\/public\\/miniappletSuccessService[^"'\\s]*)/i);
                if (match) { successUrl = match[1]; break; }
                var baseMatch = txt.match(/(https?:\\/\\/[^"'\\s]*fire-signature\\/public)[/"'\\s]/i);
                if (baseMatch && !successUrl) { successUrl = baseMatch[1] + '/miniappletSuccessService'; }
            }
            // Also check for existing forms targeting it
            var forms = document.querySelectorAll('form');
            for (var i = 0; i < forms.length; i++) {
                if (forms[i].action && forms[i].action.indexOf('miniappletSuccessService') !== -1) {
                    successUrl = forms[i].action;
                    break;
                }
            }
            // Fallback: same origin
            if (!successUrl) {
                successUrl = window.location.origin + '/fire-signature/public/miniappletSuccessService';
            }

            var ensureField = function(form, name, value, overwrite) {
                var input =
                    form.querySelector('input[name="' + name + '"]') ||
                    form.querySelector('textarea[name="' + name + '"]');
                if (!input) {
                    input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = name;
                    form.appendChild(input);
                }
                var current = String(input.value || '');
                if (overwrite || !current) {
                    input.value = value || '';
                }
                return input;
            };
            var submitOnce = function(form) {
                if (form.__xalocSubmitWrapped) {
                    form.submit();
                    return;
                }
                var nativeSubmit = HTMLFormElement.prototype.submit;
                form.__xalocSubmitWrapped = true;
                form.__xalocSubmitted = false;
                form.submit = function() {
                    if (form.__xalocSubmitted) {
                        return;
                    }
                    form.__xalocSubmitted = true;
                    return nativeSubmit.call(form);
                };
                form.submit();
            };

            // Prefer the original FIRe form so transaction-specific hidden inputs
            // are preserved exactly as generated by the portal.
            // Search the main document first, then same-origin iframes
            // (FIRe often loads MiniApplet inside an iframe on the Valencia portal).
            var form =
                document.getElementById('formSign') ||
                document.querySelector('form[action*="miniappletSuccessService"]');
            if (!form) {
                var _iframes = Array.from(document.querySelectorAll('iframe'));
                for (var _ii = 0; _ii < _iframes.length; _ii++) {
                    try {
                        var _idoc = _iframes[_ii].contentDocument;
                        if (!_idoc) continue;
                        form = _idoc.getElementById('formSign') ||
                               _idoc.querySelector('form[action*="miniappletSuccessService"]');
                        if (form) { successUrl = form.action || successUrl; break; }
                    } catch (_ie) {}
                }
            }
            if (form) {
                var isBatchOperation =
                    String(
                        (form.querySelector('[name="isbatchop"]') || {}).value || ''
                    ).toLowerCase() === 'true';
                form.method = 'POST';
                form.action = successUrl;
                ensureField(form, 'afirmabatchresult', isBatchOperation ? signatureB64 : '', true);
                ensureField(form, 'cert', certB64, false);
                ensureField(form, 'errortype', '', true);
                ensureField(form, 'errormsg', '', true);
                submitOnce(form);
                return {
                    ok: true,
                    url: successUrl,
                    mode: 'existing_form',
                    isBatchOperation,
                    fieldNames: Array.from(form.elements || [])
                        .map((el) => String(el.name || ''))
                        .filter(Boolean)
                        .slice(0, 40),
                };
            }

            // Fallback only when FIRe's form is absent.
            form = document.createElement('form');
            form.method = 'POST';
            form.action = successUrl;
            form.style.display = 'none';
            ensureField(form, 'afirmabatchresult', signatureB64, true);
            ensureField(form, 'cert', certB64, false);
            ensureField(form, 'op', 'sign', false);
            document.body.appendChild(form);
            submitOnce(form);
            return { ok: true, url: successUrl, mode: 'fallback_form' };
        }""",
        {
            "signatureB64": result.signature_b64,
            "certB64": final_cert or "",
        },
    )
    _add_debug_event(
        telemetry,
        kind="fire_inprocess_success_service_triggered",
        data=submit_info or {},
    )
    logger.info(
        "valencia.fire_signing: miniappletSuccessService triggered url=%s",
        (submit_info or {}).get("url", "?"),
    )
    # Give the form submission time to navigate
    await page.wait_for_timeout(3000)
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass


async def _maybe_force_afirma_handler(page: "Page", *, telemetry: dict) -> None:
    """
    En algunos entornos Docker/headed el click en "Firmar" captura URI afirma://
    pero no ejecuta el handler del esquema. En ese caso lo lanzamos manualmente.
    """
    # Espera corta al flujo normal de protocolo.
    start_url = str(page.url or "")
    await _capture_fire_runtime_state(page, telemetry=telemetry, step="before_wait_uri")
    await _drain_fire_runtime_events(page, telemetry=telemetry, step="before_wait_uri")
    uri_js = ""
    uri_evt = _latest_afirma_uri_from_telemetry(telemetry)
    if uri_evt and _AFIRMA_URI_RE.match(uri_evt):
        uri_js = uri_evt
        _add_debug_event(
            telemetry,
            kind="afirma_uri_recovered_immediate",
            data={"uri_prefix": uri_js[:220], "source": "telemetry_immediate"},
        )
    # Evitar latencia extra antes del primer intento de retrieve de FIRe.
    # El diagnóstico de host se mantiene para rutas de error y deep-debug.
    if _is_afirma_deep_debug_enabled():
        await _collect_afirma_host_diag(telemetry=telemetry, step="before_wait_uri")
    wait_timeout_ms = 250 if uri_js else 1500
    uri_from_handler = await wait_for_afirma_uri_trigger(timeout_ms=wait_timeout_ms)
    if uri_from_handler:
        _add_debug_event(
            telemetry,
            kind="afirma_uri_handler_detected",
            data={"uri_prefix": uri_from_handler[:220]},
        )
        await _replay_bridge_put_with_browser_session(page, telemetry=telemetry)
        return

    if not uri_js:
        try:
            uri_js = await page.evaluate("() => String(window.__afirma_url || '').trim()")
        except Exception:
            uri_js = ""
        uri_js = str(uri_js or "").strip()
    if not uri_js or not _AFIRMA_URI_RE.match(uri_js):
        uri_evt = _latest_afirma_uri_from_telemetry(telemetry)
        if uri_evt and _AFIRMA_URI_RE.match(uri_evt):
            uri_js = uri_evt
            _add_debug_event(
                telemetry,
                kind="afirma_uri_recovered_from_events",
                data={"uri_prefix": uri_js[:220], "source": "request_failed_or_telemetry"},
            )
    if not uri_js or not _AFIRMA_URI_RE.match(uri_js):
        # FIRe puede trabajar en modo WebSocket sin exponer afirma://.
        # En ese caso esperamos navegación/callback o error explícito del propio FIRe.
        await _sample_fire_runtime(page, telemetry=telemetry, step="fire_wait_loop", total_ms=15_000, interval_ms=1000)
        for _ in range(30):  # 15s
            uri_evt = _latest_afirma_uri_from_telemetry(telemetry)
            if uri_evt and _AFIRMA_URI_RE.match(uri_evt):
                uri_js = uri_evt
                _add_debug_event(
                    telemetry,
                    kind="afirma_uri_recovered_during_wait",
                    data={"uri_prefix": uri_js[:220], "source": "request_failed_or_telemetry"},
                )
                break
            await page.wait_for_timeout(500)
            current_url = str(page.url or "")
            if current_url != start_url:
                _add_debug_event(
                    telemetry,
                    kind="fire_post_sign_navigated_without_uri",
                    data={"from": start_url, "to": current_url},
                )
                return
            try:
                fire_err = await page.evaluate(
                    """() => ({
                        errorType: String(document.getElementById('inputerrortype')?.value || ''),
                        errorMsg: String(document.getElementById('inputerrormsg')?.value || ''),
                        errorText: String(document.getElementById('errorMsg')?.innerText || ''),
                        progressVisible: !!(document.getElementById('progressDialog') && document.getElementById('progressDialog').style.display !== 'none')
                    })"""
                )
            except Exception:
                fire_err = {}
            if (fire_err or {}).get("errorType") or (fire_err or {}).get("errorMsg"):
                _add_debug_event(telemetry, kind="fire_sign_error", data=fire_err or {})
                raise RuntimeError(
                    "valencia.afirma.fire: error en cliente local de firma. "
                    f"type={(fire_err or {}).get('errorType','')} "
                    f"msg={(fire_err or {}).get('errorMsg','') or (fire_err or {}).get('errorText','')}"
                )

        if not uri_js or not _AFIRMA_URI_RE.match(uri_js):
            _add_debug_event(
                telemetry,
                kind="afirma_uri_missing_after_sign",
                data={"url": str(page.url or ""), "start_url": start_url},
            )
            await _capture_fire_runtime_state(page, telemetry=telemetry, step="missing_uri_before_raise")
            await _drain_fire_runtime_events(page, telemetry=telemetry, step="missing_uri_before_raise", max_items=900)
            await _collect_afirma_host_diag(telemetry=telemetry, step="missing_uri_before_raise")
            raise RuntimeError(
                "valencia.afirma.fire: no hubo callback de firma tras pulsar Firmar. "
                "FIRe esperaba resultado para enviar miniappletSuccessService, pero no hubo URI/callback del cliente local."
            )
        _add_debug_event(
            telemetry,
            kind="afirma_uri_recovered_before_raise",
            data={"uri_prefix": uri_js[:220]},
        )

    handler_script = (os.getenv("XALOC_AFIRMA_HANDLER_SCRIPT") or "/app/infra/docker/afirma-handler.sh").strip()
    if not Path(handler_script).exists():
        _add_debug_event(
            telemetry,
            kind="afirma_handler_missing",
            data={"handler_script": handler_script, "uri_prefix": uri_js[:220]},
        )
        raise RuntimeError(
            f"valencia.afirma: URI capturada pero handler no encontrado en {handler_script}"
        )

    _add_debug_event(
        telemetry,
        kind="afirma_handler_forced",
        data={"handler_script": handler_script, "uri_prefix": uri_js[:220]},
    )
    logger.warning(
        "valencia.afirma -> URI capturada en JS pero no lanzada por navegador. Forzando handler: %s",
        handler_script,
    )
    proc = await asyncio.create_subprocess_exec(
        "bash" if sys.platform != "win32" else "cmd",
        handler_script if sys.platform != "win32" else "/c",
        uri_js if sys.platform != "win32" else handler_script,
        *( [] if sys.platform != "win32" else [uri_js] ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out_txt = (stdout or b"").decode("utf-8", errors="ignore")[:2000]
    err_txt = (stderr or b"").decode("utf-8", errors="ignore")[:2000]
    _add_debug_event(
        telemetry,
        kind="afirma_handler_result",
        data={"rc": int(proc.returncode or 0), "stdout_head": out_txt, "stderr_head": err_txt},
    )
    if proc.returncode != 0:
        err_summary = (err_txt or out_txt or "").strip()
        await _collect_afirma_host_diag(telemetry=telemetry, step="forced_handler_failed")
        raise RuntimeError(
            f"valencia.afirma: fallo forzando handler (rc={proc.returncode}) err={err_summary[:500]}"
        )

    uri_after_force = await wait_for_afirma_uri_trigger(timeout_ms=6000)
    if not uri_after_force:
        await _capture_fire_runtime_state(page, telemetry=telemetry, step="forced_handler_no_uri")
        await _drain_fire_runtime_events(page, telemetry=telemetry, step="forced_handler_no_uri")
        await _collect_afirma_host_diag(telemetry=telemetry, step="forced_handler_no_uri")
        raise RuntimeError(
            "valencia.afirma: handler forzado ejecutado pero no se detecto inicio de proxy/URI."
        )
    await _replay_bridge_put_with_browser_session(page, telemetry=telemetry)


async def _prepare_fire_signature_client(page: "Page", *, telemetry: dict) -> None:
    """
    Valencia/FIRe: evita dependencia estricta de WS local en entornos dockerizados.
    """
    try:
        data = await page.evaluate(
            """() => {
                const out = { url: String(window.location.href || ''), hasMiniApplet: !!window.MiniApplet };
                if (!window.MiniApplet) return out;
                try { MiniApplet.setForceWSMode(false); out.forceWSMode = false; } catch(e) { out.forceWSModeError = String(e); }
                try { MiniApplet.setForceAFirma(true); out.forceAFirma = true; } catch(e) { out.forceAFirmaError = String(e); }
                return out;
            }"""
        )
        _add_debug_event(telemetry, kind="fire_signature_client_prepared", data=dict(data or {}))
    except Exception as exc:
        _add_debug_event(telemetry, kind="fire_signature_client_prepare_error", data={"error": str(exc)})


async def _descargar_y_guardar_justificante_post_firma(page: "Page", datos: "ValenciaTarget") -> Path:
    btn = None
    selected_selector = None
    heuristic_probe: dict | None = None
    for selector in _VALENCIA_JUSTIFICANTE_SELECTORS:
        candidate = page.locator(selector).first
        try:
            await candidate.wait_for(state="visible", timeout=10000)
            btn = candidate
            selected_selector = selector
            break
        except Exception:
            continue
    if btn is None:
        heuristic_probe = await _probe_justificante_target(page)
        if not list((heuristic_probe or {}).get("candidates") or []):
            raise RuntimeError(
                "valencia.justificante: no se encontro boton de descarga en selectores esperados. "
                f"selectors={list(_VALENCIA_JUSTIFICANTE_SELECTORS)} probe={heuristic_probe}"
            )
        logger.info("valencia.justificante detectado via heuristica candidatos=%s", len(heuristic_probe["candidates"]))
    else:
        logger.info("valencia.justificante boton de descarga detectado selector=%s", selected_selector)

    rid = _safe_resource_id(datos)
    tmp_dir = Path("tmp") / "valencia" / "justificantes" / rid
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fallback_tmp_path = build_non_overwrite_path(tmp_dir, f"justificante_{rid}.pdf")
    tmp_path: Path | None = None

    try:
        if btn is None:
            raise RuntimeError("heuristic-http-only")
        async with page.expect_download(timeout=60000) as dl_info:
            await btn.click(force=True)
        download = await dl_info.value
        suggested = download.suggested_filename or fallback_tmp_path.name
        tmp_path = build_non_overwrite_path(tmp_dir, suggested)
        await download.save_as(str(tmp_path))
        logger.info("valencia.justificante descarga por evento ok tmp=%s", tmp_path)
    except Exception as exc:
        logger.warning("valencia.justificante descarga por evento fallo; usando fallback HTTP. error=%s", exc)
        download_url = ""
        if btn is not None:
            download_url = (await btn.get_attribute("data-clickable-url")) or ""
            if not download_url:
                download_url = (await btn.get_attribute("href")) or ""
            if not download_url:
                onclick = (await btn.get_attribute("onclick")) or ""
                match = re.search(r"""['"](https?://[^'"]+|/[^'"]+)['"]""", onclick)
                if match:
                    download_url = match.group(1)
        if not download_url:
            heuristic_probe = heuristic_probe or await _probe_justificante_target(page)
            for candidate in list((heuristic_probe or {}).get("candidates") or []):
                data_url = str(candidate.get("data_clickable_url") or "").strip()
                href = str(candidate.get("href") or "").strip()
                onclick = str(candidate.get("onclick") or "").strip()
                if data_url:
                    download_url = data_url
                    break
                if href and href.lower() != "javascript:{}":
                    download_url = href
                    break
                match = re.search(r"""['"](https?://[^'"]+|/[^'"]+)['"]""", onclick)
                if match:
                    download_url = match.group(1)
                    break
        if not download_url:
            raise RuntimeError(
                "valencia.justificante: boton/candidato detectado, pero no se pudo resolver URL de descarga. "
                f"probe={heuristic_probe}"
            ) from exc
        if download_url.startswith("/"):
            download_url = f"https://sede.valencia.es{download_url}"
        response = await page.context.request.get(download_url, timeout=90000)
        if not response.ok:
            raise RuntimeError(f"valencia.justificante: error descargando PDF (HTTP {response.status}).") from exc
        pdf_bytes = await response.body()
        if not pdf_bytes.startswith(b"%PDF"):
            raise RuntimeError("valencia.justificante: respuesta descargada no es un PDF valido.") from exc
        fallback_tmp_path.write_bytes(pdf_bytes)
        tmp_path = fallback_tmp_path
        logger.info("valencia.justificante descarga por HTTP ok tmp=%s bytes=%s", tmp_path, len(pdf_bytes))

    if tmp_path is None or not tmp_path.exists():
        raise RuntimeError("valencia.justificante: no se genero archivo temporal de justificante.")

    payload = _payload_for_storage(datos)
    destino_dir = resolve_receipt_dir_from_payload(
        payload=payload,
        fase_procedimiento=str(getattr(datos, "fase_procedimiento", "") or "").strip() or None,
    )
    final_name = build_receipt_filename(expediente=str(getattr(datos, "expediente", "") or "UNKNOWN"))
    final_path = save_receipt_from_tmp(tmp_path=tmp_path, destino_dir=destino_dir, filename=final_name)
    payload["valencia_justificante_descargado"] = True
    payload["valencia_justificante_path"] = str(final_path)
    logger.info("valencia.justificante guardado final=%s", final_path)
    return final_path


async def run_confirmacion(page: "Page", config: "ValenciaConfig", datos: "ValenciaTarget") -> "Page":
    _ = (config, datos)
    telemetry: dict = {"site_id": "valencia", "afirma_debug": _is_afirma_debug_enabled(), "events": []}
    logger.info(
        "valencia.run_confirmacion START idRecurso=%s expediente=%s tramite=%s",
        datos.idRecurso,
        datos.expediente,
        datos.tramite_tipo,
    )
    reset_afirma_uri_capture_file()
    await prepare_autofirma_context(page.context, logger=logger)
    await _setup_afirma_debug(page, datos=datos, telemetry=telemetry)
    await _install_fire_runtime_hooks(page, telemetry=telemetry)
    prewarm_proc = prewarm_autofirma_process(logger=logger)
    try:
        await wait_autofirma_prewarm_ready(prewarm_proc, timeout_ms=5000, logger=logger)
        await page.wait_for_load_state("networkidle")
        await _ensure_detalle_before_presentar(page, config, telemetry=telemetry)
        await _capture_dom_signature_snapshot(page, step="before_click_presentar", telemetry=telemetry)

        # 1) Presentar
        await _click_presentar_with_recovery(page, telemetry=telemetry, datos=datos)
        await _capture_dom_signature_snapshot(page, step="after_click_presentar", telemetry=telemetry)

        # 2) Checkbox privacidad
        privacy = page.locator('[id="checkBoxPrivacidad"]')
        if await privacy.count():
            if not await privacy.first.is_checked():
                await privacy.first.check()
            logger.info("valencia.run_confirmacion -> checkbox_privacidad ok")
        else:
            logger.warning("valencia.run_confirmacion -> checkbox_privacidad no encontrado")

        # 3) Firmar y presentar
        await _click_first_available(
            page,
            selectors=[
                '[id="formFirma:j_id914586918_1_72a7e174"]',
                'input[type="submit"][value*="Firmar"]',
                'input[type="submit"][value*="Signar"]',
            ],
            step="click_firmar_presentar",
        )
        await _capture_dom_signature_snapshot(page, step="after_click_firmar_presentar", telemetry=telemetry)

        # 4) Acceptar del panel/modal
        await _click_first_available(
            page,
            selectors=[
                "div.ui-dialog-buttonset button:has-text('Acceptar')",
                'button:has-text("Acceptar")',
                'button:has-text("Aceptar")',
                'button.ui-button:has-text("Acceptar")',
            ],
            step="click_acceptar_modal",
        )
        await _capture_dom_signature_snapshot(page, step="after_click_acceptar_modal", telemetry=telemetry)

        # 5) Acceder con AutoFirma
        await _click_acceder_second_preferred(page)
        await _capture_dom_signature_snapshot(page, step="after_click_acceder_autofirma", telemetry=telemetry)
        await _prepare_fire_signature_client(page, telemetry=telemetry)
        await _capture_fire_runtime_state(page, telemetry=telemetry, step="after_prepare_fire_signature_client")
        await _drain_fire_runtime_events(page, telemetry=telemetry, step="after_prepare_fire_signature_client")

        # 6) Boton grande de Firmar (puede aparecer en la pagina actual o en un frame/dialog).
        sign_selectors = [
            '[id="buttonSign"]',
            'input[type="button"][value="Firmar"]',
            'input.button_firmar',
        ]
        signing_frame = None
        clicked_sign = await _click_first_available(
            page,
            selectors=sign_selectors,
            step="click_button_sign",
            required=False,
        )
        if not clicked_sign:
            for idx, frame in enumerate(page.frames):
                for selector in sign_selectors:
                    loc = frame.locator(selector)
                    if await loc.count():
                        try:
                            await loc.first.click()
                            signing_frame = frame
                            logger.info(
                                "valencia.run_confirmacion -> click_button_sign ok in_frame=%s selector=%s",
                                idx,
                                selector,
                            )
                            clicked_sign = True
                            break
                        except Exception:
                            continue
                if clicked_sign:
                    break
        if not clicked_sign:
            logger.warning("valencia.run_confirmacion -> click_button_sign no disponible tras Acceder (continuando)")
        await _capture_dom_signature_snapshot(page, step="after_click_button_sign", telemetry=telemetry)
        await _capture_fire_runtime_state(page, telemetry=telemetry, step="after_click_button_sign")
        await _drain_fire_runtime_events(page, telemetry=telemetry, step="after_click_button_sign")
        await _collect_afirma_host_diag(telemetry=telemetry, step="after_click_button_sign")
        _use_inprocess = os.getenv("VALENCIA_FIRE_INPROCESS", "1").strip().lower() in {"1", "true", "yes", "on"}
        if _use_inprocess:
            await _execute_fire_signing_inprocess(page, telemetry=telemetry, signing_frame=signing_frame)
        else:
            await _maybe_force_afirma_handler(page, telemetry=telemetry)

        await _wait_post_sign_ready_for_receipt(page, telemetry=telemetry)
        await _capture_fire_runtime_state(page, telemetry=telemetry, step="post_sign_ready_for_receipt")
        await _drain_fire_runtime_events(page, telemetry=telemetry, step="post_sign_ready_for_receipt")
        justificante_path = await _descargar_y_guardar_justificante_post_firma(page, datos)
        logger.info("valencia.run_confirmacion -> justificante_guardado=%s", justificante_path)

        logger.info("valencia.run_confirmacion END")
        return page
    finally:
        stop_autofirma_prewarm(prewarm_proc, logger=logger)
        await _flush_afirma_debug_artifacts(page, datos=datos, telemetry=telemetry)
