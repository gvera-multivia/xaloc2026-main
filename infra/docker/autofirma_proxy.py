"""
autofirma_proxy.py
==================
WebSocket proxy that emulates local AutoFirma daemon in Docker/headless.
It accepts both JSON protocol and legacy text protocol ending with @EOF.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

try:
    import websockets
    from websockets.server import serve as ws_serve

    _WS_VERSION = int(websockets.__version__.split(".")[0])
except ImportError:
    raise SystemExit("[autofirma-proxy] 'websockets' not installed. pip install websockets")

log = logging.getLogger("autofirma-proxy")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [autofirma-proxy] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

CERT_PATH = os.getenv("PLAYWRIGHT_CERT_PATH", "/data/certificates/certificate.pfx")
CERT_PASS = os.getenv("PLAYWRIGHT_CERT_PASSWORD", "")
CERT_ALIAS = (os.getenv("SIGNING_PFX_ALIAS") or os.getenv("PLAYWRIGHT_CERT_ALIAS") or "").strip()
NSS_DB_CANDIDATES = [
    os.getenv("PLAYWRIGHT_NSS_DB_DIR", "/root/.pki/nssdb"),
    os.getenv("PLAYWRIGHT_GLOBAL_NSS_DB_DIR", "/root/.pki/nssdb"),
]
LATEST_FILE = os.getenv("XALOC_AFIRMA_URI_LATEST", "/tmp/xaloc_afirma_uri.latest")
LOG_FILE = os.getenv("XALOC_AFIRMA_URI_LOG", "/tmp/xaloc_afirma_uri.log")
PROXY_READY = os.getenv("XALOC_AFIRMA_PROXY_READY", "/tmp/xaloc_afirma_proxy.ready")
PROXY_PID = os.getenv("XALOC_AFIRMA_PROXY_PID", "/tmp/xaloc_afirma_proxy.pid")
IDLE_TIMEOUT = int(os.getenv("XALOC_AFIRMA_PROXY_IDLE_TIMEOUT", "120"))
FORENSIC_LOG = os.getenv("XALOC_AFIRMA_FORENSIC_LOG", "/tmp/xaloc_afirma_forensic.jsonl")
FORENSIC_PAYLOAD_DIR = os.getenv("XALOC_AFIRMA_FORENSIC_PAYLOAD_DIR", "/tmp/xaloc_afirma_forensic_payloads")
FORENSIC_ENABLED = os.getenv("XALOC_AFIRMA_FORENSIC_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
TEXT_SIGN_RESPONSE_MODE = os.getenv("XALOC_AFIRMA_TEXT_SIGN_RESPONSE_MODE", "auto").strip().lower()
SELF_PID = os.getpid()

_URI_RE = re.compile(r"^(?:afirma|xalocafirma)://", re.IGNORECASE)
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_name(value: str, default: str = "na") -> str:
    cleaned = _SAFE_NAME_RE.sub("_", (value or "").strip())
    return cleaned[:80] if cleaned else default


def _write_forensic_event(
    *,
    direction: str,
    mode: str,
    op: str,
    mid: str,
    payload: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if not FORENSIC_ENABLED:
        return
    try:
        payload_text = str(payload or "")
        ts = time.time()
        ts_ms = int(ts * 1000)
        ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + f".{int((ts % 1) * 1000):03d}Z"
        digest = hashlib.sha256(payload_text.encode("utf-8", errors="replace")).hexdigest()

        out_dir = Path(FORENSIC_PAYLOAD_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = (
            f"{ts_ms}-"
            f"{_safe_name(direction)}-"
            f"{_safe_name(mode)}-"
            f"{_safe_name(op)}-"
            f"{_safe_name(mid, default='noid')}.txt"
        )
        payload_path = out_dir / fname
        payload_path.write_text(payload_text, encoding="utf-8")

        event: dict[str, Any] = {
            "ts": ts_iso,
            "direction": direction,
            "mode": mode,
            "op": op,
            "id": mid,
            "len": len(payload_text),
            "sha256": digest,
            "payload_file": str(payload_path),
        }
        if extra:
            event.update(extra)

        Path(FORENSIC_LOG).parent.mkdir(parents=True, exist_ok=True)
        with open(FORENSIC_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True) + "\n")

        log.info(
            "FORENSIC saved: dir=%s mode=%s op=%s id=%s len=%d sha256=%s file=%s",
            direction,
            mode,
            op,
            mid or "",
            len(payload_text),
            digest[:16],
            payload_path,
        )
    except Exception as exc:
        log.warning("FORENSIC write failed: %s", exc)


def parse_afirma_uri(uri: str) -> dict[str, Any]:
    from urllib.parse import parse_qs, urlparse

    normalized = re.sub(r"^[a-zA-Z]+://", "http://x/", uri)
    parsed = urlparse(normalized)
    qs = parse_qs(parsed.query, keep_blank_values=True)

    ports_raw = qs.get("ports", [""])[0]
    ports = [int(p.strip()) for p in ports_raw.split(",") if p.strip().isdigit()]

    return {
        "ports": ports,
        "idsession": qs.get("idsession", [""])[0],
        "algorithm": qs.get("algorithm", ["SHA512withRSA"])[0],
        "format": qs.get("format", ["XAdES"])[0],
        "raw": uri,
        "qs": qs,
    }


def _generate_self_signed_cert() -> tuple[str, str]:
    tmp = tempfile.mkdtemp(prefix="afirma-proxy-tls-")
    key_path = os.path.join(tmp, "server.key")
    cert_path = os.path.join(tmp, "server.crt")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            key_path,
            "-out",
            cert_path,
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1,DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    log.info("TLS cert generated in %s", tmp)
    return cert_path, key_path


def _build_ssl_context(cert_path: str, key_path: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _extract_cert_b64_from_pfx() -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="afirma-cert-") as tmp:
            cert_der = os.path.join(tmp, "cert.der")
            cert_pem = os.path.join(tmp, "cert.pem")
            cmd = [
                "openssl",
                "pkcs12",
                "-in",
                CERT_PATH,
                "-nokeys",
                "-clcerts",
                "-out",
                cert_pem,
                "-passin",
                f"pass:{CERT_PASS}",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=20)
            if result.returncode != 0:
                result = subprocess.run(cmd + ["-legacy"], capture_output=True, timeout=20)
            if result.returncode != 0 or not os.path.exists(cert_pem):
                log.warning("Could not extract cert DER from PFX, trying NSS fallback")
                return _extract_cert_b64_from_nss()
            # Intento 1: convertir PEM->DER y codificar
            der_conv = subprocess.run(
                ["openssl", "x509", "-in", cert_pem, "-outform", "DER", "-out", cert_der],
                capture_output=True,
                timeout=20,
            )
            if der_conv.returncode == 0 and os.path.exists(cert_der):
                return base64.b64encode(Path(cert_der).read_bytes()).decode("ascii")

            # Intento 2: extraer body base64 del PEM (equivalente DER base64)
            pem_text = Path(cert_pem).read_text(encoding="utf-8", errors="ignore")
            m = re.search(
                r"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----",
                pem_text,
                flags=re.DOTALL,
            )
            if m:
                cert_b64 = re.sub(r"\s+", "", m.group(1))
                if cert_b64:
                    return cert_b64
            log.warning("PFX cert extracted but could not normalize as DER base64; trying NSS fallback")
            return _extract_cert_b64_from_nss()
    except Exception as exc:
        log.warning("Error extracting cert from PFX: %s (trying NSS fallback)", exc)
        return _extract_cert_b64_from_nss()


def _extract_cert_b64_from_nss() -> str:
    """
    Fallback: exporta certificado desde NSS DB con certutil y devuelve Base64 DER.
    El PEM body ya es Base64 de DER (prefijo típico MII...).
    """
    for db_dir in NSS_DB_CANDIDATES:
        if not db_dir:
            continue
        db_path = Path(db_dir)
        if not db_path.exists():
            continue
        nss_db = f"sql:{db_dir}"
        try:
            listed = subprocess.run(
                ["certutil", "-L", "-d", nss_db],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if listed.returncode != 0:
                continue
            output = listed.stdout or ""

            nicknames: list[str] = []
            if CERT_ALIAS and CERT_ALIAS in output:
                nicknames.append(CERT_ALIAS)

            # Fallback: elegir primer cert de usuario (trust u,u,u)
            for raw in output.splitlines():
                line = raw.rstrip()
                if not line or line.startswith("Certificate Nickname") or line.startswith("SSL,"):
                    continue
                if "u,u,u" in line:
                    nn = line.split("u,u,u", 1)[0].rstrip()
                    if nn and nn not in nicknames:
                        nicknames.append(nn)

            for nickname in nicknames:
                exported = subprocess.run(
                    ["certutil", "-L", "-d", nss_db, "-n", nickname, "-a"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if exported.returncode != 0:
                    continue
                pem = exported.stdout or ""
                m = re.search(
                    r"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----",
                    pem,
                    flags=re.DOTALL,
                )
                if not m:
                    continue
                cert_b64 = re.sub(r"\s+", "", m.group(1))
                if cert_b64:
                    log.info("Certificate exported from NSS db=%s nickname=%s", db_dir, nickname)
                    return cert_b64
        except Exception as exc:
            log.warning("NSS cert extract failed db=%s: %s", db_dir, exc)
            continue
    return ""


def _sign_with_autofirma_cli(
    data_b64: str,
    algorithm: str,
    fmt: str,
    extra_params: str = "",
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="afirma-sign-") as tmp:
        input_path = os.path.join(tmp, "input.bin")
        output_path = os.path.join(tmp, "output.bin")

        try:
            raw_data = _decode_b64_tolerant(data_b64)
        except Exception as exc:
            raise RuntimeError(f"Invalid Base64 payload: {exc}") from exc

        Path(input_path).write_bytes(raw_data)

        fmt_map = {
            "xades": "xades",
            "xades detached": "xades",
            "cades": "cades",
            "pades": "pades",
            "facturae": "facturae",
            "ooxml": "ooxml",
            "odf": "odf",
            "auto": "auto",
        }
        alg_map = {
            "sha1withrsa": "sha1",
            "sha256withrsa": "sha256",
            "sha384withrsa": "sha384",
            "sha512withrsa": "sha512",
            "sha1": "sha1",
            "sha256": "sha256",
            "sha384": "sha384",
            "sha512": "sha512",
        }
        fmt_norm = fmt_map.get((fmt or "").strip().lower(), "xades")
        alg_norm = alg_map.get((algorithm or "").strip().lower(), "sha512")

        cmd = [
            "autofirma",
            "sign",
            "-i",
            input_path,
            "-o",
            output_path,
            "-store",
            f"pkcs12:{CERT_PATH}",
            "-format",
            fmt_norm,
            "-algorithm",
            alg_norm,
        ]
        if CERT_PASS:
            cmd += ["-password", CERT_PASS]
        if CERT_ALIAS:
            cmd += ["-alias", CERT_ALIAS]
        if extra_params:
            cmd += ["-config", extra_params]

        run_env = os.environ.copy()
        # AutoFirma CLI requiere AWT; damos DISPLAY y evitamos forzar flags Java por defecto.
        if not run_env.get("DISPLAY"):
            run_env["DISPLAY"] = os.getenv("XALOC_AFIRMA_DISPLAY", ":99")
        run_env.pop("JAVA_TOOL_OPTIONS", None)

        log.info(
            "Running AutoFirma CLI with DISPLAY=%s format=%s algorithm=%s alias=%s",
            run_env.get("DISPLAY", ""),
            fmt_norm,
            alg_norm,
            CERT_ALIAS or "(none)",
        )
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90, env=run_env)
        if result.returncode != 0 and "HeadlessException" in ((result.stderr or "") + (result.stdout or "")):
            # Fallback: ejecutar sin JAVA_TOOL_OPTIONS por si la JVM ignora DISPLAY con ciertos flags.
            retry_env = dict(run_env)
            retry_env["JAVA_TOOL_OPTIONS"] = ""
            log.warning("HeadlessException detectada. Reintentando AutoFirma sin JAVA_TOOL_OPTIONS.")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90, env=retry_env)
        if result.returncode != 0:
            err = ((result.stderr or "") + "\n" + (result.stdout or ""))[:2500]
            raise RuntimeError(f"AutoFirma CLI failed (rc={result.returncode}): {err}")

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("AutoFirma CLI did not generate output")

        firma_bytes = Path(output_path).read_bytes()
        firma_b64 = base64.b64encode(firma_bytes).decode("ascii")
        cert_b64 = _extract_cert_b64_from_pfx()

        log.info("Sign OK: %d input bytes -> %d signature bytes", len(raw_data), len(firma_bytes))
        return firma_b64, cert_b64


def _decode_b64_tolerant(raw: str) -> bytes:
    """
    Decodifica Base64 tolerando variaciones de AutoScript:
    - URL-safe ('-' y '_')
    - sin padding '='
    - espacios/saltos
    - payload ya percent-decoded
    """
    if raw is None:
        raise ValueError("empty payload")
    txt = str(raw).strip()
    if not txt:
        raise ValueError("empty payload")

    # Normaliza espacios y remueve ruido visual.
    cleaned = re.sub(r"\s+", "", txt)

    # Intento 1: base64 estÃ¡ndar (con padding forzado).
    pad = "=" * ((4 - (len(cleaned) % 4)) % 4)
    try:
        return base64.b64decode(cleaned + pad, validate=False)
    except Exception:
        pass

    # Intento 2: variante URL-safe.
    cleaned_url = cleaned.replace("-", "+").replace("_", "/")
    pad2 = "=" * ((4 - (len(cleaned_url) % 4)) % 4)
    try:
        return base64.b64decode(cleaned_url + pad2, validate=False)
    except Exception as exc:
        raise ValueError(
            f"cannot decode base64 (len={len(cleaned)} prefix={cleaned[:24]!r}): {exc}"
        ) from exc


def _strip_eof_marker(raw: str) -> str:
    txt = (raw or "").strip()
    if txt.endswith("@EOF"):
        txt = txt[:-4]
    return txt.strip()


def _parse_text_kv_message(raw_msg: str) -> dict[str, Any]:
    raw = _strip_eof_marker(raw_msg)
    params: dict[str, str] = {}
    for chunk in raw.split("&"):
        if not chunk:
            continue
        if "=" in chunk:
            key, value = chunk.split("=", 1)
        else:
            key, value = chunk, ""
        key = key.strip().lower()
        if not key:
            continue
        params[key] = unquote(value.strip())

    idsession = ""
    m = re.search(r"(?:^|[&\-])idsession=([^&@]+)", raw, flags=re.IGNORECASE)
    if m:
        idsession = unquote(m.group(1).strip())

    op = (
        (params.get("operation") or "")
        or (params.get("op") or "")
        or (params.get("cmd") or "")
        or (params.get("command") or "")
    ).strip().lower()

    if not op:
        if "echo" in params:
            op = "echo"
        elif "sign" in params:
            op = "sign"
        elif any(k in params for k in ("data", "dat", "algorithm", "format", "extraparams", "properties")):
            # Algunos clientes no envian operation/cmd y solo incluyen campos de firma.
            op = "sign"
        elif "idsession=" in raw.lower() and len(params) <= 2:
            # Mensaje corto de keepalive estilo echo=-idsession=...
            op = "echo"

    return {
        "operation": op,
        "id": params.get("id", "") or idsession,
        "algorithm": params.get("algorithm", "SHA512withRSA"),
        "format": params.get("format", "XAdES"),
        "data": params.get("data", "") or params.get("dat", "") or params.get("sign", ""),
        "extraParams": params.get("extraparams", "") or params.get("properties", ""),
    }


def _parse_incoming_message(raw_msg: str) -> tuple[dict[str, Any], str]:
    stripped = _strip_eof_marker(raw_msg)
    if stripped.startswith("{"):
        try:
            return json.loads(stripped), "json"
        except json.JSONDecodeError:
            pass
    return _parse_text_kv_message(raw_msg), "text"


def _build_text_response(
    *,
    op: str,
    ok: bool,
    mid: str = "",
    signature: str = "",
    certificate: str = "",
    error: str = "",
) -> str:
    # Compatibilidad amplia para clientes @firma en modo texto.
    # Para "sign" devolvemos KV plano sin prefijo URI para evitar errores Base64 con "?".
    # Incluimos dat/data/signature y cert/certificate para compatibilidad.
    if op == "sign":
        parts = [f"result={'OK' if ok else 'ERROR'}", "operation=sign", "op=sign"]
        if mid:
            parts.append(f"idsession={mid}")
            parts.append(f"id={mid}")
        if signature:
            parts.append(f"dat={signature}")
            parts.append(f"data={signature}")
            parts.append(f"signature={signature}")
        if certificate:
            parts.append(f"cert={certificate}")
            parts.append(f"certificate={certificate}")
        if error:
            parts.append(f"errorMessage={quote(error[:300], safe='')}")
        return "&".join(parts) + "@EOF"

    parts = [f"result={'OK' if ok else 'ERROR'}"]
    if op:
        parts.append(f"operation={quote(op, safe='')}")
    if mid:
        parts.append(f"id={quote(mid, safe='')}")
        parts.append(f"idsession={quote(mid, safe='')}")
    if error:
        parts.append(f"errorMessage={quote(error[:300], safe='')}")
    return "&".join(parts) + "@EOF"


def _build_legacy_text_response_for_sign(
    signature_b64: str,
    certificate_b64: str = "",
    mode: str = "auto",
) -> str:
    """
    Compatibilidad con AutoScript en modo texto:
    - echo espera "OK"
    - sign espera un payload base64 plano (sin clave=valor, sin URI).
    """
    def _to_urlsafe_b64(txt: str) -> str:
        norm = re.sub(r"\s+", "", txt or "")
        # Redsara manual capture uses URL-safe base64 (e.g. "MII...-..._...").
        return norm.replace("+", "-").replace("/", "_").rstrip("=")

    sig = _to_urlsafe_b64(signature_b64)
    cert = _to_urlsafe_b64(certificate_b64)
    mode_norm = (mode or "auto").strip().lower()
    if mode_norm not in {"auto", "cert", "sign", "pair"}:
        mode_norm = "auto"

    # Modo forzado para pruebas controladas.
    if mode_norm == "cert":
        if cert:
            return cert
        if sig:
            return sig
        return "ERROR"
    if mode_norm == "sign":
        if sig:
            return sig
        if cert:
            return cert
        return "ERROR"
    if mode_norm == "pair":
        # Formato observado en flujo Redsara exitoso:
        #   <cert_base64url_sin_padding>|<firma_base64url_sin_padding>
        # donde la firma en XAdES puede empezar por PD94...
        if cert and sig:
            return f"{cert}|{sig}"
        if sig:
            return sig
        if cert:
            return cert
        return "ERROR"

    # Heuristica Redsara:
    # - Payload correcto para sign suele ser bloque MII "grande" (no certificado corto).
    # - Evitar devolver XML base64 (PD94...) cuando haya alternativa.
    if sig and sig.startswith("MII") and len(sig) >= 5000:
        return sig
    if cert and cert.startswith("MII") and len(cert) >= 5000:
        return cert
    if sig and not sig.startswith("PD94"):
        return sig
    if cert:
        return cert
    if sig:
        return sig
    return "ERROR"


async def _handle_connection(websocket: Any) -> None:
    remote = getattr(websocket, "remote_address", "?")
    log.info("Connection from %s", remote)

    try:
        async for raw_msg in websocket:
            if isinstance(raw_msg, bytes):
                raw_msg = raw_msg.decode("utf-8", errors="replace")

            raw_str = str(raw_msg)
            msg, mode = _parse_incoming_message(raw_str)
            op = (msg.get("operation") or "").lower()
            mid = msg.get("id", "")
            log.info("Operation received: op=%s id=%s mode=%s", op, mid, mode)
            if mode == "text":
                log.info("Text payload preview: %r", _strip_eof_marker(raw_str)[:240])

            if op == "echo":
                if mode == "json":
                    await websocket.send(json.dumps({"result": "OK", "id": mid}))
                else:
                    await websocket.send("OK")
                continue

            if op == "sign":
                data_b64 = msg.get("data", "")
                algorithm = msg.get("algorithm", "SHA512withRSA")
                fmt = msg.get("format", "XAdES")
                extra_b64 = msg.get("extraParams", "")
                _write_forensic_event(
                    direction="in",
                    mode=mode,
                    op="sign",
                    mid=mid,
                    payload=raw_str,
                    extra={
                        "algorithm": algorithm,
                        "format": fmt,
                    },
                )

                extra_str = ""
                if extra_b64:
                    try:
                        extra_str = base64.b64decode(extra_b64).decode("utf-8", errors="replace")
                    except Exception:
                        extra_str = extra_b64

                try:
                    firma_b64, cert_b64 = await asyncio.get_event_loop().run_in_executor(
                        None,
                        _sign_with_autofirma_cli,
                        data_b64,
                        algorithm,
                        fmt,
                        extra_str,
                    )
                    # Redsara/AutoScript en modo text suele aceptar mejor payload tipo MII...
                    # Si XAdES produce XML (PD94...), intentar una vez con CAdES.
                    if (
                        mode == "text"
                        and TEXT_SIGN_RESPONSE_MODE != "pair"
                        and firma_b64.startswith("PD94")
                    ):
                        try:
                            log.info(
                                "Text mode sign produced XML payload (len=%d). Retrying with CAdES fallback.",
                                len(firma_b64),
                            )
                            alt_firma_b64, _ = await asyncio.get_event_loop().run_in_executor(
                                None,
                                _sign_with_autofirma_cli,
                                data_b64,
                                algorithm,
                                "CAdES",
                                extra_str,
                            )
                            # Si el original es XML (PD94...) y el fallback produce MII..., usar fallback.
                            # No exigir mayor longitud: CAdES puede ser mas corto que XAdES XML.
                            if alt_firma_b64.startswith("MII"):
                                log.info(
                                    "Using CAdES fallback signature (len=%d, prefix=%s).",
                                    len(alt_firma_b64),
                                    alt_firma_b64[:12],
                                )
                                firma_b64 = alt_firma_b64
                        except Exception as exc:
                            log.warning("CAdES fallback failed: %s", exc)
                    response = {
                        "result": "OK",
                        "id": mid,
                        "signature": firma_b64,
                        "certificate": cert_b64,
                    }
                except Exception as exc:
                    log.error("Sign error: %s", exc)
                    response = {
                        "result": "ERROR",
                        "id": mid,
                        "errorCode": "SIGN_ERROR",
                        "errorMessage": str(exc)[:300],
                    }

                if mode == "json":
                    out_payload = json.dumps(response)
                    _write_forensic_event(
                        direction="out",
                        mode="json",
                        op="sign",
                        mid=mid,
                        payload=out_payload,
                    )
                    await websocket.send(out_payload)
                else:
                    if response.get("result") == "OK":
                        sig_dbg = (response.get("signature", "") or "").strip()
                        cert_dbg = (response.get("certificate", "") or "").strip()
                        log.info(
                            "Text sign response candidates: sig_len=%d sig_prefix=%r cert_len=%d cert_prefix=%r",
                            len(sig_dbg),
                            sig_dbg[:12],
                            len(cert_dbg),
                            cert_dbg[:12],
                        )
                        payload = _build_legacy_text_response_for_sign(
                            signature_b64=response.get("signature", ""),
                            certificate_b64=response.get("certificate", ""),
                            mode=TEXT_SIGN_RESPONSE_MODE,
                        )
                        # En modo "pair" de Redsara exitoso no se observó @EOF en respuesta sign.
                        if (
                            payload
                            and TEXT_SIGN_RESPONSE_MODE != "pair"
                            and not payload.endswith("@EOF")
                        ):
                            payload = payload + "@EOF"
                    else:
                        payload = "ERROR"
                    if response.get("result") == "OK":
                        log.info("Text sign response mode: %s", TEXT_SIGN_RESPONSE_MODE)
                    log.info("Text response preview: %r", payload[:240])
                    _write_forensic_event(
                        direction="out",
                        mode="text",
                        op="sign",
                        mid=mid,
                        payload=payload,
                    )
                    await websocket.send(payload)
                continue

            if mode == "text" and not op:
                # Mensaje intermedio sin op clara: no inyectar respuesta de error.
                log.warning("Text message without operation. Ignored.")
                continue

            err_msg = f"Unknown operation: {op}"
            if mode == "json":
                await websocket.send(
                    json.dumps(
                        {
                            "result": "ERROR",
                            "id": mid,
                            "errorCode": "UNKNOWN_OPERATION",
                            "errorMessage": err_msg,
                        }
                    )
                )
            else:
                await websocket.send(_build_text_response(op=op or "unknown", ok=False, mid=mid, error=err_msg))
    except Exception as exc:
        log.info("Connection closed: %s", exc)


def _cleanup_files(owner_pid: int) -> None:
    pid_path = Path(PROXY_PID)
    ready_path = Path(PROXY_READY)

    try:
        current_owner = pid_path.read_text(encoding="utf-8").strip()
    except Exception:
        current_owner = ""

    if current_owner and current_owner != str(owner_pid):
        log.info("Skipping cleanup. current owner=%s expected=%s", current_owner, owner_pid)
        return

    try:
        ready_path.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        pid_path.unlink(missing_ok=True)
    except Exception:
        pass


async def _idle_sentinel() -> None:
    while True:
        await asyncio.sleep(10)


async def run_proxy(ports: list[int], ssl_ctx: ssl.SSLContext) -> None:
    servers = []
    bound_ports: list[int] = []

    for port in ports:
        try:
            if _WS_VERSION >= 10:
                server = await ws_serve(_handle_connection, "127.0.0.1", port, ssl=ssl_ctx)
            else:
                server = await websockets.serve(_handle_connection, "127.0.0.1", port, ssl=ssl_ctx)
            servers.append(server)
            bound_ports.append(port)
            log.info("Listening on wss://127.0.0.1:%d/", port)
        except OSError as exc:
            log.warning("Cannot bind port %d: %s", port, exc)

    if not servers:
        raise RuntimeError("Could not bind any requested port")

    try:
        Path(PROXY_PID).write_text(str(SELF_PID), encoding="utf-8")
    except Exception as exc:
        log.warning("Could not write pid file: %s", exc)

    Path(PROXY_READY).write_text(",".join(str(p) for p in bound_ports), encoding="utf-8")
    log.info("Proxy ready on ports: %s", bound_ports)

    try:
        await asyncio.wait_for(_idle_sentinel(), timeout=IDLE_TIMEOUT)
    except asyncio.TimeoutError:
        log.info("Idle timeout reached (%ss). Closing proxy.", IDLE_TIMEOUT)
    finally:
        for srv in servers:
            srv.close()
            await srv.wait_closed()
        _cleanup_files(owner_pid=SELF_PID)


def main() -> None:
    arg = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if arg in {"-h", "--help"}:
        print("Usage: python autofirma_proxy.py 'afirma://websocket?ports=..'")
        print("If URI is omitted, it is read from XALOC_AFIRMA_URI_LATEST")
        return

    uri = arg
    if not uri:
        log.info("No URI argument. Waiting %s ...", LATEST_FILE)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                uri = Path(LATEST_FILE).read_text(encoding="utf-8").strip()
                if uri and _URI_RE.match(uri):
                    break
            except FileNotFoundError:
                pass
            time.sleep(0.3)

    if not uri or not _URI_RE.match(uri):
        log.error("No afirma:// URI received. Exiting.")
        sys.exit(1)

    log.info("Captured URI: %s", uri[:120])

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{ts}\t{uri}\n")
        Path(LATEST_FILE).write_text(uri, encoding="utf-8")
    except Exception as exc:
        log.warning("Could not write uri log/latest: %s", exc)

    params = parse_afirma_uri(uri)
    ports = params["ports"]
    if not ports:
        log.error("No ports found in URI: %s", uri)
        sys.exit(1)

    try:
        cert_file, key_file = _generate_self_signed_cert()
        ssl_ctx = _build_ssl_context(cert_file, key_file)
    except Exception as exc:
        log.error("Failed generating TLS cert: %s", exc)
        sys.exit(1)

    try:
        asyncio.run(run_proxy(ports, ssl_ctx))
    except KeyboardInterrupt:
        log.info("Proxy interrupted by signal")
    finally:
        _cleanup_files(owner_pid=SELF_PID)


if __name__ == "__main__":
    main()

