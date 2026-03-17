#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path
from xml.etree import ElementTree

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.autofirma_signing_bridge import sign_with_pfx


def _log(msg: str) -> None:
    print(f"[afirma-sign-bridge] {msg}", flush=True)


def _parse_uri(uri: str) -> dict:
    raw = (uri or "").strip().replace("xalocafirma://", "afirma://")
    if not raw.lower().startswith("afirma://"):
        raise ValueError("URI no valida para bridge sign")
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


def _b64url_decode(text: str) -> bytes:
    s = "".join(str(text or "").split()).replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return base64.b64decode(s)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _openssl_des_ecb_transform(data: bytes, key_bytes: bytes, *, decrypt: bool) -> bytes:
    key_hex = key_bytes.hex()
    base = ["openssl", "enc", "-des-ecb", "-nosalt", "-nopad", "-K", key_hex]
    if decrypt:
        base.insert(3, "-d")

    # OpenSSL 3 puede requerir provider legacy para DES.
    attempts = [
        base,
        ["openssl", "enc", "-provider", "legacy", "-provider", "default", "-des-ecb", "-nosalt", "-nopad", "-K", key_hex],
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


def _decipher_data(enc: str, key_bytes: bytes) -> bytes:
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

    raw = _b64url_decode(enc[idx + 1 :])
    plain = _openssl_des_ecb_transform(raw, key_bytes, decrypt=True)
    if padding_len:
        if padding_len > len(plain):
            raise ValueError("Padding mayor que longitud descifrada")
        plain = plain[: len(plain) - padding_len]
    return plain


def _cipher_data(data: bytes, key_bytes: bytes) -> str:
    if not key_bytes:
        return _b64url_encode(data)
    if len(key_bytes) != 8:
        raise ValueError(f"Longitud key invalida: {len(key_bytes)} (esperado 8)")

    pad_len = (-len(data)) % 8
    padded = data + (b"\x00" * pad_len)
    enc = _openssl_des_ecb_transform(padded, key_bytes, decrypt=False)
    return f"{pad_len}.{_b64url_encode(enc)}"


def _retrieve_params(rtservlet: str, fileid: str, key: str) -> dict:
    if not rtservlet or not fileid:
        raise ValueError("Faltan rtservlet/fileid para retrieve")
    url = rtservlet
    body = {"op": "get", "v": "1", "id": fileid}
    _log(f"GET retrieve params -> {url} id={fileid}")
    resp = requests.get(url, params=body, timeout=30)
    txt = (resp.text or "").strip()
    if resp.status_code >= 400:
        raise RuntimeError(f"retrieve status={resp.status_code} body={txt[:240]}")
    if txt.upper().startswith("ERR"):
        raise RuntimeError(f"retrieve devolvio error: {txt[:240]}")

    key_bytes = key.encode("utf-8", errors="ignore")
    plain = _decipher_data(txt, key_bytes)

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


def _parse_properties(raw: str) -> dict[str, str]:
    txt = str(raw or "").strip()
    if not txt:
        return {}
    # FIRe suele enviar properties en Base64 de un bloque tipo .properties.
    compact = "".join(txt.split()).replace("-", "+").replace("_", "/")
    pad = (-len(compact)) % 4
    if pad:
        compact += "=" * pad
    try:
        decoded = base64.b64decode(compact).decode("utf-8", errors="ignore").strip()
        if "serverUrl=" in decoded or "includeOnlySigningCertificate=" in decoded or "format=" in decoded:
            return {"_encoding": "base64", "_decoded": decoded}
    except Exception:
        pass

    parsed: dict[str, str] = {}
    norm = txt.replace("\r", "&").replace("\n", "&").replace(";", "&")
    for k, v in urllib.parse.parse_qsl(norm, keep_blank_values=True):
        kk = str(k or "").strip()
        if not kk:
            continue
        parsed[kk] = str(v or "").strip()
    return parsed


def _build_sign_params(uri_info: dict, extra_params: dict) -> dict:
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


def _resolve_storage_url(uri_info: dict, params: dict) -> str:
    st = str((params or {}).get("stservlet") or "").strip()
    if st:
        return st
    st_uri = str((uri_info or {}).get("stservlet") or "").strip()
    if st_uri:
        return st_uri
    rt = str((uri_info or {}).get("rtservlet") or "").strip()
    if rt.endswith("/retrieve"):
        return rt[: -len("/retrieve")] + "/storage"
    return rt


def _push_signature(
    storage_url: str, fileid: str, key: str, signature_b64: str, *, version: str
) -> tuple[int, str, dict]:
    signature = base64.b64decode(signature_b64.encode("ascii"))
    dat = _cipher_data(signature, key.encode("utf-8", errors="ignore"))
    body = {"op": "put", "v": (version or "1_0"), "id": fileid, "dat": dat}
    _log(f"POST put firma -> {storage_url} id={fileid} bytes={len(signature)}")
    resp = requests.post(storage_url, data=body, timeout=30)
    txt = (resp.text or "").strip()
    return int(resp.status_code), txt, body


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


def main() -> int:
    uri = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not uri:
        print("Uso: afirma_sign_bridge.py <afirma://sign?...>", file=sys.stderr)
        return 2

    trace: dict[str, object] = {"uri_head": uri[:320]}
    trace_file = Path(os.getenv("XALOC_AFIRMA_SIGN_BRIDGE_TRACE") or "/tmp/xaloc_afirma_sign_bridge_trace.json")
    try:
        info = _parse_uri(uri)
        trace["parsed"] = {k: v for k, v in info.items() if k != "query"} | {"query_keys": sorted((info.get("query") or {}).keys())}
        rtservlet = info.get("rtservlet") or ""
        fileid = info.get("fileid") or ""
        key = info.get("key") or ""
        if not rtservlet or not fileid:
            raise ValueError("URI sign sin rtservlet/fileid")

        pfx_path = os.getenv("PLAYWRIGHT_CERT_PATH") or "/data/certificates/certificate.pfx"
        pfx_password = os.getenv("PLAYWRIGHT_CERT_PASSWORD") or ""
        if not pfx_password:
            raise ValueError("PLAYWRIGHT_CERT_PASSWORD vacio")
        if not Path(pfx_path).exists():
            raise FileNotFoundError(f"PFX no encontrado: {pfx_path}")

        params = _retrieve_params(rtservlet, fileid, key)
        trace["retrieved_keys"] = sorted(params.keys())
        trace["retrieved_hints"] = {
            "id": str(params.get("id") or ""),
            "aw": str(params.get("aw") or ""),
            "op": str(params.get("op") or ""),
            "ver": str(params.get("ver") or ""),
            "format": str(params.get("format") or ""),
            "algorithm": str(params.get("algorithm") or ""),
            "stservlet": str(params.get("stservlet") or "")[:220],
            "properties_len": len(str(params.get("properties") or "")),
        }
        properties_map = _parse_properties(str(params.get("properties") or ""))
        trace["retrieved_properties"] = properties_map
        storage_url = _resolve_storage_url(info, params)
        trace["storage_url"] = storage_url
        put_ids = _unique_keep_order(
            [
                str(params.get("id") or ""),
                str(params.get("aw") or ""),
                fileid,
            ]
        )
        retrieved_ver = str(params.get("ver") or "").strip()
        # FIRe suele consultar retrieve con v=1_0; si guardamos solo v=1 puede
        # devolver ERR-06 (id invalido) aunque storage responda OK.
        if retrieved_ver in {"1", "1_0"}:
            put_versions = _unique_keep_order(["1_0", "1"])
        else:
            put_versions = _unique_keep_order(["1_0", retrieved_ver, "1"])
        trace["put_ids"] = put_ids
        trace["put_versions"] = put_versions
        trace["uri_fileid"] = fileid
        trace["expected_contract"] = {
            "retrieve_url": rtservlet,
            "storage_url": storage_url,
            "expected_id": str(params.get("id") or ""),
            "expected_versions": put_versions,
            "expected_format": str(params.get("format") or ""),
            "expected_algorithm": str(params.get("algorithm") or ""),
            "expected_op": str(params.get("op") or ""),
            "properties": properties_map,
        }
        _log(
            "EXPECTED "
            f"id={trace['expected_contract']['expected_id']} "
            f"v={','.join(put_versions)} "
            f"fmt={trace['expected_contract']['expected_format']} "
            f"algo={trace['expected_contract']['expected_algorithm']}"
        )

        sign_params = _build_sign_params(info, params)
        trace["sign_format"] = sign_params.get("format")
        trace["sign_algorithm"] = sign_params.get("algorithm")
        trace["content_b64_len"] = len(str(sign_params.get("content_b64") or ""))

        signature_b64 = sign_with_pfx(sign_params, pfx_path, pfx_password)
        used_profile = (sign_params.get("__used_sign_profile") if isinstance(sign_params, dict) else None) or {}
        trace["sign_profile_used"] = used_profile
        trace["signature_b64_len"] = len(signature_b64)
        trace["signature_b64"] = signature_b64
        attempts: list[dict[str, object]] = []
        ok = False
        for put_id in put_ids:
            for version in put_versions:
                status, body, payload = _push_signature(storage_url, put_id, key, signature_b64, version=version)
                entry = {
                    "id": put_id,
                    "version": version,
                    "status": int(status),
                    "body_head": str(body or "")[:240],
                }
                attempts.append(entry)
                # Éxito típico: OK. También aceptamos vacío/no-ERR en 2xx.
                if status < 400 and (not body or not str(body).upper().startswith("ERR")):
                    ok = True
                    trace["put_selected"] = entry
                    trace["put_payload_selected"] = {
                        "url": storage_url,
                        "body": payload,
                    }
                    break
            if ok:
                break
        trace["put_attempts"] = attempts
        if not ok:
            raise RuntimeError(f"put sin aceptacion FIRe: attempts={attempts}")

        trace["ok"] = True
        trace_file.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        _log("Bridge sign/rtservlet completado OK.")
        return 0
    except Exception as exc:
        trace["ok"] = False
        trace["error"] = str(exc)
        try:
            trace_file.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        _log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
