from __future__ import annotations

import inspect
import re


def extract_expediente_number(payload: dict) -> str:
    keys = (
        "expediente",
        "expediente_num",
        "denuncia_num",
        "Expedient",
        "nExp",
        "numero_expediente",
    )
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    exp_nnn = str(payload.get("exp_nnn") or payload.get("expediente_nnn") or "").strip()
    exp_eeeeeeeee = str(payload.get("exp_eeeeeeeee") or payload.get("expediente_eeeeeeeee") or "").strip()
    exp_d = str(payload.get("exp_d") or payload.get("expediente_d") or "").strip()
    if exp_nnn and exp_eeeeeeeee and exp_d:
        return f"{exp_nnn}/{exp_eeeeeeeee}.{exp_d}"

    exp_lll = str(payload.get("exp_lll") or payload.get("expediente_lll") or "").strip()
    exp_aaaa = str(payload.get("exp_aaaa") or payload.get("expediente_aaaa") or "").strip()
    exp_exp_num = str(payload.get("exp_exp_num") or payload.get("expediente_exp_num") or "").strip()
    if exp_lll and exp_aaaa and exp_exp_num:
        return f"{exp_lll}/{exp_aaaa}/{exp_exp_num}"

    return "UNKNOWN"


def sanitize_filename_component(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r'[<>:"|?*\x00-\x1F]', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(". ")
    return text or "UNKNOWN"


def call_with_supported_kwargs(fn, **kwargs):
    sig = inspect.signature(fn)
    accepts_var_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if accepts_var_kwargs:
        # Si el callable declara **kwargs, no filtrar claves.
        return fn(**kwargs)
    supported = {}
    for k, v in kwargs.items():
        if k not in sig.parameters:
            continue
        param = sig.parameters[k]
        # Si el parametro es obligatorio (sin default), no eliminar None:
        # dejamos que el controlador valide y emita error funcional claro.
        if v is None and param.default is not inspect._empty:
            continue
        supported[k] = v
    return fn(**supported)
