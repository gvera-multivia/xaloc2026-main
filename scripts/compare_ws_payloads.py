#!/usr/bin/env python3
"""
Compare two WebSocket payload files byte-by-byte.

Useful to compare:
- manual-good payload captured from browser WS frames
- docker forensic payload captured by autofirma_proxy
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


BASE64_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_-]{80,}")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_likely_base64(text: str) -> str:
    # Pick the longest token that looks like Base64 / Base64URL.
    matches = BASE64_TOKEN_RE.findall(text)
    if not matches:
        return text
    matches.sort(key=len, reverse=True)
    return matches[0]


def normalize_text(
    text: str,
    *,
    extract_base64: bool,
    strip_ws: bool,
    strip_eof: bool,
) -> str:
    out = text

    if extract_base64:
        out = _extract_likely_base64(out)

    if strip_eof and out.endswith("@EOF"):
        out = out[:-4]

    if strip_ws:
        out = re.sub(r"\s+", "", out)

    return out


def first_diff(a: bytes, b: bytes) -> int | None:
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return limit
    return None


def slice_window(data: bytes, idx: int, size: int = 24) -> bytes:
    start = max(0, idx - size)
    end = min(len(data), idx + size)
    return data[start:end]


def as_printable(data: bytes) -> str:
    return "".join(chr(c) if 32 <= c <= 126 else "." for c in data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two WS payload files")
    parser.add_argument("file_a", type=Path)
    parser.add_argument("file_b", type=Path)
    parser.add_argument(
        "--extract-base64",
        action="store_true",
        help="Extract longest Base64-like token before comparing",
    )
    parser.add_argument(
        "--no-strip-whitespace",
        action="store_true",
        help="Do not remove whitespace before comparing",
    )
    parser.add_argument(
        "--no-strip-eof",
        action="store_true",
        help="Do not strip trailing @EOF before comparing",
    )
    args = parser.parse_args()

    raw_a = args.file_a.read_bytes()
    raw_b = args.file_b.read_bytes()

    text_a = raw_a.decode("utf-8", errors="replace")
    text_b = raw_b.decode("utf-8", errors="replace")

    norm_a = normalize_text(
        text_a,
        extract_base64=args.extract_base64,
        strip_ws=not args.no_strip_whitespace,
        strip_eof=not args.no_strip_eof,
    ).encode("utf-8")
    norm_b = normalize_text(
        text_b,
        extract_base64=args.extract_base64,
        strip_ws=not args.no_strip_whitespace,
        strip_eof=not args.no_strip_eof,
    ).encode("utf-8")

    print("== RAW ==")
    print(f"A: {args.file_a} len={len(raw_a)} sha256={sha256_hex(raw_a)}")
    print(f"B: {args.file_b} len={len(raw_b)} sha256={sha256_hex(raw_b)}")
    print()
    print("== NORMALIZED ==")
    print(
        f"flags: extract_base64={args.extract_base64} "
        f"strip_ws={not args.no_strip_whitespace} "
        f"strip_eof={not args.no_strip_eof}"
    )
    print(f"A len={len(norm_a)} sha256={sha256_hex(norm_a)}")
    print(f"B len={len(norm_b)} sha256={sha256_hex(norm_b)}")

    idx = first_diff(norm_a, norm_b)
    if idx is None:
        print("RESULT: EQUAL")
        return 0

    print(f"RESULT: DIFFERENT at offset={idx}")
    a_byte = norm_a[idx] if idx < len(norm_a) else None
    b_byte = norm_b[idx] if idx < len(norm_b) else None
    print(
        f"A byte={a_byte} (0x{a_byte:02x})"
        if a_byte is not None
        else "A byte=<EOF>"
    )
    print(
        f"B byte={b_byte} (0x{b_byte:02x})"
        if b_byte is not None
        else "B byte=<EOF>"
    )

    win_a = slice_window(norm_a, idx)
    win_b = slice_window(norm_b, idx)
    print()
    print("A window hex :", win_a.hex())
    print("B window hex :", win_b.hex())
    print("A window txt :", as_printable(win_a))
    print("B window txt :", as_printable(win_b))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

