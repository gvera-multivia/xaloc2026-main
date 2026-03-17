#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import gzip
import zlib
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests


def _parse(uri: str) -> dict:
    normalized = uri.replace("xalocafirma://", "afirma://")
    parsed = urlparse(normalized.replace("afirma://", "http://x/"))
    qs = parse_qs(parsed.query, keep_blank_values=True)
    rt = unquote((qs.get("rtservlet") or [""])[0]).strip()
    fileid = (qs.get("fileid") or [""])[0].strip()
    key = (qs.get("key") or [""])[0].strip()
    st = unquote((qs.get("stservlet") or [""])[0]).strip()
    return {
        "uri": uri,
        "rtservlet": rt,
        "stservlet": st,
        "fileid": fileid,
        "key": key,
        "query": {k: (v[0] if v else "") for k, v in qs.items()},
    }


def main() -> int:
    uri = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not uri:
        print("[afirma-sign-probe] missing uri", file=sys.stderr)
        return 2

    info = _parse(uri)
    ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    out_dir = Path(os.getenv("XALOC_AFIRMA_SIGN_PROBE_DIR") or "/tmp")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"xaloc_afirma_sign_probe_{ts}.json"

    result: dict = {
        "ts": ts,
        "info": info,
        "retrieve": {},
    }

    rt = info.get("rtservlet") or ""
    fileid = info.get("fileid") or ""
    if rt and fileid:
        retrieve_url = f"{rt}?op=get&v=1_0&id={fileid}"
        result["retrieve"]["url"] = retrieve_url
        try:
            resp = requests.get(retrieve_url, timeout=20)
            body = resp.text or ""
            result["retrieve"].update(
                {
                    "status": int(resp.status_code),
                    "content_type": str(resp.headers.get("content-type") or ""),
                    "headers": {k: v for k, v in resp.headers.items()},
                    "len": len(body),
                    "body_head": body[:3000],
                    "is_error_prefix": body.startswith("ERR-"),
                }
            )
            if not body.startswith("ERR-"):
                decoded: dict = {}
                try:
                    raw = requests.utils.unquote(body).strip()
                    raw_bytes = __import__("base64").urlsafe_b64decode(raw + "===")
                    decoded["raw_len"] = len(raw_bytes)
                    decoded["raw_head_hex"] = raw_bytes[:48].hex()
                except Exception as exc:
                    decoded["raw_decode_error"] = str(exc)
                    raw_bytes = b""

                # AutoFirma usa DES/ECB/NoPadding para el blob intermedio con key de 8 bytes.
                key = (info.get("key") or "").encode("utf-8", errors="ignore")
                if raw_bytes and len(key) == 8:
                    try:
                        p = subprocess.run(
                            [
                                "openssl",
                                "enc",
                                "-des-ecb",
                                "-d",
                                "-nopad",
                                "-nosalt",
                                "-K",
                                key.hex(),
                            ],
                            input=raw_bytes,
                            capture_output=True,
                            check=False,
                        )
                        decoded["des_rc"] = int(p.returncode)
                        decoded["des_err"] = (p.stderr or b"").decode("utf-8", errors="ignore")[:300]
                        plain = p.stdout or b""
                        if plain:
                            pad = plain[-1]
                            if 1 <= pad <= 8 and plain.endswith(bytes([pad]) * pad):
                                plain = plain[:-pad]
                        decoded["plain_len"] = len(plain)
                        decoded["plain_head_hex"] = plain[:80].hex()
                        for enc in ("utf-8", "latin1"):
                            try:
                                txt = plain.decode(enc)
                                decoded[f"plain_{enc}_head"] = txt[:2000]
                            except Exception:
                                pass
                        for name, fn in (("gzip", gzip.decompress), ("zlib", zlib.decompress)):
                            try:
                                dec = fn(plain)
                                decoded[f"{name}_len"] = len(dec)
                                decoded[f"{name}_head"] = dec[:2000].decode("utf-8", errors="replace")
                            except Exception:
                                pass
                    except Exception as exc:
                        decoded["des_error"] = str(exc)
                else:
                    decoded["des_skipped"] = f"raw={bool(raw_bytes)} key_len={len(key)}"

                result["decoded"] = decoded
        except Exception as exc:
            result["retrieve"]["error"] = str(exc)
    else:
        result["retrieve"]["error"] = "missing rtservlet/fileid"

    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[afirma-sign-probe] wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
