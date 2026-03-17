"""
In-process FIRe (Factoría de Firma) 3-phase signing protocol.

Executes retrieve→sign→put using Playwright's APIRequestContext so that
the browser's cookies/session are preserved.  This replaces the subprocess
chain (afirma-handler.sh → afirma_sign_bridge.py) that failed because
the requests library has no access to the browser session.

Protocol extracted from ``infra/docker/afirma_sign_bridge.py``.
"""
from __future__ import annotations

import base64
import dataclasses
import logging
import subprocess
import urllib.parse
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from core.autofirma_signing_bridge import sign_with_pfx

if TYPE_CHECKING:
    from playwright.async_api import APIRequestContext


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class FireSigningResult:
    ok: bool
    signature_b64: str
    put_status: int
    put_body: str
    trace: dict
    error: str


# ---------------------------------------------------------------------------
# URI parsing
# ---------------------------------------------------------------------------

def parse_fire_uri(uri: str) -> dict:
    raw = (uri or "").strip().replace("xalocafirma://", "afirma://")
    if not raw.lower().startswith("afirma://"):
        raise ValueError("URI no valida para FIRe sign bridge")
    fake_http = "http://x/" + raw.split("://", 1)[1]
    parsed = urllib.parse.urlparse(fake_http)
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    return {
        "uri": uri,
        "rtservlet": urllib.parse.unquote((qs.get("rtservlet") or [""])[0]).strip(),
        "stservlet": urllib.parse.unquote((qs.get("stservlet") or [""])[0]).strip(),
        "fileid": (qs.get("fileid") or [""])[0].strip(),
        "key": (qs.get("key") or [""])[0].strip(),
        "query": {k: (v[0] if v else "") for k, v in qs.items()},
    }


# ---------------------------------------------------------------------------
# Base64-URL helpers
# ---------------------------------------------------------------------------

def _b64url_decode(text: str) -> bytes:
    s = "".join(str(text or "").split()).replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return base64.b64decode(s)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


# ---------------------------------------------------------------------------
# DES-ECB cipher (FIRe encrypted blobs)
# ---------------------------------------------------------------------------

def _openssl_des_ecb_transform(data: bytes, key_bytes: bytes, *, decrypt: bool) -> bytes:
    key_hex = key_bytes.hex()
    base = ["openssl", "enc", "-des-ecb", "-nosalt", "-nopad", "-K", key_hex]
    if decrypt:
        base.insert(3, "-d")

    attempts = [
        base,
        ["openssl", "enc", "-provider", "legacy", "-provider", "default",
         "-des-ecb", "-nosalt", "-nopad", "-K", key_hex],
    ]
    if decrypt:
        attempts[1].insert(8, "-d")

    last_err = ""
    for cmd in attempts:
        proc = subprocess.run(cmd, input=data, capture_output=True, check=False)
        if proc.returncode == 0:
            return proc.stdout or b""
        last_err = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()

    raise RuntimeError(f"openssl des-ecb fallo tras reintento legacy: {last_err[:500]}")


def decipher_fire_data(enc: str, key_bytes: bytes) -> bytes:
    if not key_bytes:
        return _b64url_decode(enc)
    if len(key_bytes) != 8:
        raise ValueError(f"Longitud key invalida: {len(key_bytes)} (esperado 8)")
    enc = str(enc or "").strip()
    idx = enc.find(".")
    if idx < 0:
        raise ValueError("Blob cifrado invalido: falta prefijo de padding")
    prefix = enc[:idx]
    if not prefix.isdigit():
        raise ValueError("Blob cifrado invalido: prefijo no numerico")
    padding_len = int(prefix)
    if padding_len < 0 or padding_len > 7:
        raise ValueError(f"Blob cifrado invalido: padding_len={padding_len}")

    raw = _b64url_decode(enc[idx + 1:])
    plain = _openssl_des_ecb_transform(raw, key_bytes, decrypt=True)
    if padding_len:
        if padding_len > len(plain):
            raise ValueError("Padding mayor que longitud descifrada")
        plain = plain[:len(plain) - padding_len]
    return plain


def cipher_fire_data(data: bytes, key_bytes: bytes) -> str:
    if not key_bytes:
        return _b64url_encode(data)
    if len(key_bytes) != 8:
        raise ValueError(f"Longitud key invalida: {len(key_bytes)} (esperado 8)")

    pad_len = (-len(data)) % 8
    padded = data + (b"\x00" * pad_len)
    enc = _openssl_des_ecb_transform(padded, key_bytes, decrypt=False)
    return f"{pad_len}.{_b64url_encode(enc)}"


# ---------------------------------------------------------------------------
# FIRe retrieve XML parsing
# ---------------------------------------------------------------------------

def parse_fire_retrieve_xml(plain: bytes) -> dict[str, str]:
    params: dict[str, str] = {}
    root = ElementTree.fromstring(plain.decode("utf-8", errors="replace"))
    for node in list(root):
        if node.tag != "e":
            continue
        k = node.attrib.get("k")
        v = node.attrib.get("v", "")
        if not k:
            continue
        params[k] = urllib.parse.unquote(v)
    return params


# ---------------------------------------------------------------------------
# Sign-param building
# ---------------------------------------------------------------------------

def build_fire_sign_params(uri_info: dict, extra_params: dict) -> dict:
    qs = dict(uri_info.get("query") or {})
    merged = dict(extra_params or {})
    for k, v in qs.items():
        merged.setdefault(k, v)
    content = (
        merged.get("content")
        or merged.get("data")
        or merged.get("dat")
        or merged.get("doc")
        or merged.get("hash")
    )
    if not content:
        raise ValueError(f"No se encontro contenido para firmar en params: {sorted(merged.keys())}")
    return {
        "content_b64": content,
        "format": merged.get("format") or "CAdES",
        "algorithm": merged.get("algorithm") or merged.get("Algorithm") or "SHA256withRSA",
        "params_raw": merged,
        "qs": {k: [str(v)] for k, v in merged.items()},
    }


def resolve_fire_storage_url(uri_info: dict, params: dict) -> str:
    st = str((params or {}).get("stservlet") or "").strip()
    if st:
        return st
    st_uri = str((uri_info or {}).get("stservlet") or "").strip()
    if st_uri:
        return st_uri
    rt = str((uri_info or {}).get("rtservlet") or "").strip()
    if rt.endswith("/retrieve"):
        return rt[:-len("/retrieve")] + "/storage"
    return rt


# ---------------------------------------------------------------------------
# Unique-keep-order helper
# ---------------------------------------------------------------------------

def _unique_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        val = str(v or "").strip()
        if not val or val in seen:
            continue
        out.append(val)
        seen.add(val)
    return out


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------

async def execute_fire_signing(
    api_request: "APIRequestContext",
    uri: str,
    pfx_path: str,
    pfx_password: str,
    *,
    logger: logging.Logger | None = None,
) -> FireSigningResult:
    """
    Execute the full FIRe 3-phase protocol in-process.

    Phase 1 - Retrieve:  GET rtservlet (via browser session)
    Phase 2 - Sign:      Decrypt params, call sign_with_pfx()
    Phase 3 - Put:       POST stservlet (via browser session)
    """
    log = logger or logging.getLogger("xaloc_automation.fire_signing")
    trace: dict = {"uri_head": uri[:320]}

    try:
        info = parse_fire_uri(uri)
        rtservlet = info["rtservlet"]
        fileid = info["fileid"]
        key = info["key"]
        key_bytes = key.encode("utf-8", errors="ignore")

        if not rtservlet or not fileid:
            raise ValueError("URI sign sin rtservlet/fileid")

        # ── Phase 1: Retrieve ────────────────────────────────────────────
        retrieve_url = rtservlet
        retrieve_params = f"op=get&v=1&id={urllib.parse.quote(fileid)}"
        sep = "&" if "?" in retrieve_url else "?"
        full_retrieve_url = f"{retrieve_url}{sep}{retrieve_params}"

        log.info("[FIRe-inprocess] Retrieve -> %s id=%s", retrieve_url, fileid)
        resp = await api_request.get(full_retrieve_url, timeout=30_000)
        txt = (await resp.text()).strip()
        if resp.status >= 400:
            raise RuntimeError(f"retrieve status={resp.status} body={txt[:240]}")
        if txt.upper().startswith("ERR"):
            raise RuntimeError(f"retrieve devolvio error: {txt[:240]}")

        plain = decipher_fire_data(txt, key_bytes)
        params = parse_fire_retrieve_xml(plain)
        trace["retrieved_keys"] = sorted(params.keys())
        trace["retrieved_hints"] = {
            "id": str(params.get("id") or ""),
            "aw": str(params.get("aw") or ""),
            "format": str(params.get("format") or ""),
            "algorithm": str(params.get("algorithm") or ""),
        }

        # ── Phase 2: Sign ────────────────────────────────────────────────
        sign_params = build_fire_sign_params(info, params)
        trace["sign_format"] = sign_params.get("format")
        trace["sign_algorithm"] = sign_params.get("algorithm")

        log.info("[FIRe-inprocess] Sign format=%s algo=%s", sign_params.get("format"), sign_params.get("algorithm"))
        signature_b64 = sign_with_pfx(sign_params, pfx_path, pfx_password, logger=log)
        trace["signature_b64_len"] = len(signature_b64)
        used_profile = sign_params.get("__used_sign_profile") or {}
        trace["sign_profile_used"] = {
            "format": str(used_profile.get("format") or ""),
            "algorithm": str(used_profile.get("algorithm") or ""),
            "used_config_only": bool(used_profile.get("used_config_only")),
        }

        # ── Phase 3: Put ─────────────────────────────────────────────────
        storage_url = resolve_fire_storage_url(info, params)
        trace["storage_url"] = storage_url
        signature_bytes = base64.b64decode(signature_b64.encode("ascii"))
        dat = cipher_fire_data(signature_bytes, key_bytes)

        put_ids = _unique_keep_order([
            str(params.get("id") or ""),
            str(params.get("aw") or ""),
            fileid,
        ])
        retrieved_ver = str(params.get("ver") or "").strip()
        if retrieved_ver in {"1", "1_0"}:
            put_versions = _unique_keep_order(["1_0", "1"])
        else:
            put_versions = _unique_keep_order(["1_0", retrieved_ver, "1"])

        trace["put_ids"] = put_ids
        trace["put_versions"] = put_versions

        attempts: list[dict] = []
        ok = False
        last_status = 0
        last_body = ""
        for put_id in put_ids:
            for version in put_versions:
                payload = {"op": "put", "v": version, "id": put_id, "dat": dat}
                log.info("[FIRe-inprocess] Put -> %s id=%s v=%s", storage_url, put_id, version)
                put_resp = await api_request.post(storage_url, form=payload, timeout=30_000)
                body = (await put_resp.text()).strip()
                last_status = put_resp.status
                last_body = body
                entry = {
                    "id": put_id,
                    "version": version,
                    "status": put_resp.status,
                    "body_head": body[:240],
                }
                attempts.append(entry)
                if put_resp.status < 400 and (not body or not body.upper().startswith("ERR")):
                    ok = True
                    trace["put_selected"] = entry
                    break
            if ok:
                break

        trace["put_attempts"] = attempts
        if not ok:
            raise RuntimeError(f"put sin aceptacion FIRe: attempts={attempts}")

        log.info("[FIRe-inprocess] Completado OK")
        return FireSigningResult(
            ok=True,
            signature_b64=signature_b64,
            put_status=last_status,
            put_body=last_body[:240],
            trace=trace,
            error="",
        )

    except Exception as exc:
        trace["error"] = str(exc)
        log.error("[FIRe-inprocess] ERROR: %s", exc)
        return FireSigningResult(
            ok=False,
            signature_b64="",
            put_status=0,
            put_body="",
            trace=trace,
            error=str(exc),
        )
