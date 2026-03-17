from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent / "signing_scripts"


@lru_cache(maxsize=32)
def _read_script(name: str) -> str:
    return (_SCRIPTS_DIR / name).read_text(encoding="utf-8")


PALMA_WAIT_FOR_URL_SCRIPT = _read_script("palma_wait_for_url.js")


def build_palma_intercept_script(*, block_external_launch: bool) -> str:
    return _read_script("palma_intercept.js").replace(
        "__BLOCK_EXTERNAL_LAUNCH__",
        "true" if block_external_launch else "false",
    )


def get_redsara_afirma_hook_script(*, block_external_launch: bool = False) -> str:
    script = _read_script("redsara_afirma_hook.js")
    # El bloqueo se pasa como 2º argumento al invocar la IIFE.
    return script


def get_redsara_ws_tap_script() -> str:
    return _read_script("redsara_ws_tap.js")
