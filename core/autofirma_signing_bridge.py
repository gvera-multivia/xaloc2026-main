from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import urllib.parse


def parse_afirma_url(url_raw: str) -> dict:
    """
    Parsea URI afirma://(o xalocafirma://) y devuelve:
      - content_b64
      - format
      - algorithm
      - params_raw
      - qs
    """
    url_decoded = urllib.parse.unquote(url_raw)
    if "?" in url_decoded:
        query_str = url_decoded.split("?", 1)[1]
    else:
        query_str = url_decoded.split("://", 1)[-1]

    qs = urllib.parse.parse_qs(query_str, keep_blank_values=True)

    params_raw: dict = {}
    if "params" in qs:
        params_b64 = qs["params"][0]
        try:
            params_raw = json.loads(base64.b64decode(params_b64 + "=="))
        except Exception:
            params_raw = {"raw_b64": params_b64}

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
            "No se encontro 'content', 'data' ni 'dat' en la URL afirma://. "
            f"Keys params={list(params_raw.keys())} qs={list(qs.keys())}"
        )

    fmt = params_raw.get("format") or qs.get("format", ["CAdES"])[0] or "CAdES"
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


def _normalize_format(fmt: str) -> str:
    value = str(fmt or "").strip().lower()
    mapping = {
        "cades": "cades",
        "pades": "pades",
        "xades": "xades",
        "xadestri": "xades",
        "xadestrifase": "xades",
        "cadestri": "cades",
        "padestri": "pades",
        "auto": "auto",
    }
    return mapping.get(value, "cades")


def _normalize_algorithm(algo: str) -> str:
    lower = str(algo or "").lower()
    if "512" in lower:
        return "sha512"
    if "384" in lower:
        return "sha384"
    if "sha1" in lower:
        return "sha1"
    return "sha256"


def _candidate_sign_profiles(fmt_raw: str, algo_raw: str, *, extra_config: str | None = None) -> list[tuple[str | None, str | None]]:
    """
    Prioriza compatibilidad FIRe y velocidad:
    1) exacto (raw) tal cual llega de FIRe
    2) fallback normalizado (comportamiento previo)
    """
    raw_fmt = str(fmt_raw or "").strip() or "CAdES"
    raw_algo = str(algo_raw or "").strip() or "SHA256withRSA"
    norm_fmt = _normalize_format(raw_fmt)
    norm_algo = _normalize_algorithm(raw_algo)

    profiles: list[tuple[str | None, str | None]] = []
    cfg = str(extra_config or "")
    # En FIRe trifase priorizamos el perfil exacto pedido por el portal.
    profiles.append((raw_fmt, raw_algo))
    if "triphaseSignService" in cfg:
        profiles.append((None, None))
    if (norm_fmt, norm_algo) != (raw_fmt, raw_algo):
        profiles.append((norm_fmt, norm_algo))
    return profiles


def _inspect_signature(signature: bytes) -> dict[str, object]:
    raw = signature or b""
    text = raw.decode("utf-8", errors="ignore")
    looks_xml = bool(re.search(r"<(?:[A-Za-z0-9_]+:)?Signature\\b", text))
    has_x509 = bool(re.search(r"<(?:[A-Za-z0-9_]+:)?X509Certificate>\\s*[^<]+", text))
    return {
        "len": len(raw),
        "looks_xml": looks_xml,
        "has_x509": has_x509,
        "head_hex": raw[:16].hex(),
    }


def _decode_properties_config(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    # Caso 1: ya viene en texto plano tipo properties.
    if "serverUrl=" in raw or "includeOnlySigningCertificate=" in raw or "\n" in raw:
        return raw

    # Caso 2: properties en Base64/Base64URL.
    normalized = "".join(raw.split()).replace("-", "+").replace("_", "/")
    pad = (-len(normalized)) % 4
    if pad:
        normalized += "=" * pad
    try:
        decoded = base64.b64decode(normalized)
        text = decoded.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if "serverUrl=" in text or "includeOnlySigningCertificate=" in text or "format=" in text:
        return text
    return None


def _resolve_extra_config(params: dict) -> str | None:
    raw = params.get("params_raw") or {}
    qs = params.get("qs") or {}

    props = raw.get("properties")
    if not props and isinstance(qs, dict):
        qv = qs.get("properties")
        if isinstance(qv, list) and qv:
            props = qv[0]
        elif isinstance(qv, str):
            props = qv
    cfg = _decode_properties_config(str(props or ""))
    if cfg:
        return cfg
    return None


def _resolve_alias_pfx(pfx_path: str, pfx_password: str, logger: logging.Logger | None = None) -> str | None:
    log = logger or logging.getLogger("xaloc_automation.autofirma")
    try:
        result = subprocess.run(
            [
                "autofirma",
                "listaliases",
                "-store",
                f"pkcs12:{pfx_path}",
                "-password",
                pfx_password,
            ],
            capture_output=True,
            timeout=5,
        )
        output = result.stdout.decode("utf-8", errors="ignore").strip()
        for line in output.splitlines():
            line = line.strip()
            if line and not line.startswith("INFO") and not line.startswith("WARNING"):
                log.info("[AUTOFIRMA] Alias detectado via listaliases: %s", line)
                return line
    except Exception as exc:
        log.warning("[AUTOFIRMA] No se pudo resolver alias del PFX: %s", exc)
    return None


def sign_with_pfx(
    params: dict,
    pfx_path: str,
    pfx_password: str,
    *,
    logger: logging.Logger | None = None,
) -> str:
    """
    Firma contenido base64 con CLI `autofirma sign` y devuelve firma base64.
    """
    log = logger or logging.getLogger("xaloc_automation.autofirma")
    content_b64 = params["content_b64"]
    fmt_raw = str(params.get("format", "CAdES") or "CAdES")
    algo_raw = str(params.get("algorithm", "SHA256withRSA") or "SHA256withRSA")
    extra_config = _resolve_extra_config(params)
    sign_profiles = _candidate_sign_profiles(fmt_raw, algo_raw, extra_config=extra_config)

    normalized = "".join(str(content_b64).split()).replace("-", "+").replace("_", "/")
    pad = (-len(normalized)) % 4
    if pad:
        normalized = normalized + ("=" * pad)
    content_bytes = base64.b64decode(normalized)

    alias = os.environ.get("SIGNING_PFX_ALIAS") or _resolve_alias_pfx(pfx_path, pfx_password, log)

    with tempfile.TemporaryDirectory(prefix="xaloc_firma_") as tmpdir:
        f_input = os.path.join(tmpdir, "input.dat")
        f_output = os.path.join(tmpdir, "output.sig")
        with open(f_input, "wb") as fh:
            fh.write(content_bytes)

        last_error: RuntimeError | None = None
        signature: bytes = b""
        for fmt, algo in sign_profiles:
            cmd = [
                "autofirma",
                "sign",
                "-i",
                f_input,
                "-o",
                f_output,
                "-store",
                f"pkcs12:{pfx_path}",
                "-password",
                pfx_password,
            ]
            if fmt:
                cmd += ["-format", fmt]
            if algo:
                cmd += ["-algorithm", algo]
            if alias:
                cmd += ["-alias", alias]
            if extra_config:
                cmd += ["-config", extra_config]
            try:
                log.info("[AUTOFIRMA] Intento sign format=%s algorithm=%s cfg=%s", fmt or "<config>", algo or "<config>", bool(extra_config))
                result = subprocess.run(cmd, check=True, capture_output=True, timeout=25)
                stdout = result.stdout.decode("utf-8", errors="ignore").strip()
                if stdout:
                    log.info("[AUTOFIRMA] stdout: %s", stdout[:500])
                with open(f_output, "rb") as fh:
                    candidate_signature = fh.read()
                probe = _inspect_signature(candidate_signature)
                signature = candidate_signature
                try:
                    params["__used_sign_profile"] = {
                        "format": fmt or "",
                        "algorithm": algo or "",
                        "used_config_only": not bool(fmt or algo),
                        "probe": probe,
                    }
                except Exception:
                    pass
                last_error = None
                break
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.decode("utf-8", errors="ignore").strip() if exc.stderr else ""
                last_error = RuntimeError(
                    f"autofirma sign fallo (format={fmt}, algorithm={algo}, rc={exc.returncode}): {stderr}"
                )
                continue
        if last_error is not None:
            raise last_error

    log.info("[AUTOFIRMA] Firma completada (%d bytes).", len(signature))
    return base64.b64encode(signature).decode("ascii")
