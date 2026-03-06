from __future__ import annotations

import base64
import json
import logging
import os
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
            timeout=15,
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
    fmt = _normalize_format(params.get("format", "CAdES"))
    algo = _normalize_algorithm(params.get("algorithm", "SHA256withRSA"))

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
            "-format",
            fmt,
            "-algorithm",
            algo,
        ]
        if alias:
            cmd += ["-alias", alias]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            stdout = result.stdout.decode("utf-8", errors="ignore").strip()
            if stdout:
                log.info("[AUTOFIRMA] stdout: %s", stdout[:500])
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore").strip() if exc.stderr else ""
            raise RuntimeError(f"autofirma sign fallo (rc={exc.returncode}): {stderr}") from exc

        with open(f_output, "rb") as fh:
            signature = fh.read()

    log.info("[AUTOFIRMA] Firma completada (%d bytes).", len(signature))
    return base64.b64encode(signature).decode("ascii")
