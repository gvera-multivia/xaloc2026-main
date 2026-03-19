from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalize(value: Any) -> str:
    text = _clean(value).lower()
    if not text:
        return ""
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


@lru_cache(maxsize=1)
def _load_motivos() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "config_motivos.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_phase_texts(
    *,
    fase_procedimiento: Any,
    expediente: Any,
    sujeto_recurso: Any = "",
    asunto: Any = "",
    expone: Any = "",
    solicita: Any = "",
) -> tuple[str, str, str]:
    expediente_txt = _clean(expediente)
    sujeto_txt = _clean(sujeto_recurso)

    asunto_txt = _clean(asunto)
    expone_txt = _clean(expone)
    solicita_txt = _clean(solicita)

    selected: dict[str, Any] | None = None
    fase_norm = _normalize(fase_procedimiento)
    if fase_norm:
        for key, value in _load_motivos().items():
            if _normalize(key) in fase_norm:
                selected = value
                break

    if selected:
        if not asunto_txt:
            asunto_txt = _clean(selected.get("asunto"))
        if not expone_txt:
            expone_txt = _clean(selected.get("expone"))
        if not solicita_txt:
            solicita_txt = _clean(selected.get("solicita"))

    replacements = {
        "{expediente}": expediente_txt,
        "{sujeto_recurso}": sujeto_txt,
    }
    for needle, replacement in replacements.items():
        asunto_txt = asunto_txt.replace(needle, replacement)
        expone_txt = expone_txt.replace(needle, replacement)
        solicita_txt = solicita_txt.replace(needle, replacement)

    if not asunto_txt:
        asunto_txt = f"Escrito relativo al expediente {expediente_txt or 'N/A'}"
    if not expone_txt:
        expone_txt = (
            f"Se presenta escrito en relacion con el expediente {expediente_txt or 'N/A'}"
            + (f" a nombre de {sujeto_txt}." if sujeto_txt else ".")
        )
    if not solicita_txt:
        solicita_txt = f"Se solicita la admision y tramitacion del presente escrito relativo al expediente {expediente_txt or 'N/A'}."

    return asunto_txt, expone_txt, solicita_txt


def build_fets_solicitud(
    *,
    fase_procedimiento: Any,
    expediente: Any,
    sujeto_recurso: Any = "",
    asunto: Any = "",
    expone: Any = "",
    solicita: Any = "",
    max_length: int = 3200,
) -> str:
    asunto_txt, expone_txt, solicita_txt = resolve_phase_texts(
        fase_procedimiento=fase_procedimiento,
        expediente=expediente,
        sujeto_recurso=sujeto_recurso,
        asunto=asunto,
        expone=expone,
        solicita=solicita,
    )
    text = "\n\n".join(
        [
            f"ASUNTO: {asunto_txt}",
            f"EXPONE: {expone_txt}",
            f"SOLICITA: {solicita_txt}",
        ]
    ).strip()
    return text[:max_length]
