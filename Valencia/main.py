import json
import unicodedata
from pathlib import Path

from database import get_recurso_data
from tramits_valencia import (
    alegaciones_denuncia_transito,
    identificacion_conductor,
    recurso_reposicion,
)
from playwright.sync_api import sync_playwright


def _norm_text(value: str) -> str:
    txt = str(value or "").strip().lower()
    if not txt:
        return ""
    txt = "".join(
        ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn"
    )
    return " ".join(txt.split())


def _load_motivos() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "config_motivos.json"
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return {_norm_text(k): v for k, v in raw.items()}


def _build_sujeto_recurso(row) -> str:
    nombre = str(row.get("Nombre") or "").strip()
    apellido1 = str(row.get("Apellido1") or "").strip()
    apellido2 = str(row.get("Apellido2") or "").strip()
    parts = [p for p in [nombre, apellido1, apellido2] if p]
    return " ".join(parts).strip()


def _apply_motivos_by_fase(df, fase: str, motivos: dict):
    if df.empty:
        return df

    fase_key = _norm_text(fase)
    if fase_key not in motivos:
        disponibles = ", ".join(sorted(motivos.keys()))
        raise ValueError(f"Fase no configurada en config_motivos.json: '{fase}'. Disponibles: {disponibles}")

    row = df.iloc[0]
    expediente = str(row.get("Expedient") or "").strip()
    sujeto_recurso = _build_sujeto_recurso(row)
    motivo = motivos[fase_key]

    context = {
        "expediente": expediente,
        "sujeto_recurso": sujeto_recurso,
    }

    expone_tpl = str(motivo.get("expone") or "").strip()
    solicita_tpl = str(motivo.get("solicita") or "").strip()
    asunto_tpl = str(motivo.get("asunto") or "").strip()

    df = df.copy()
    df["fase_procedimiento"] = fase
    df["asunto"] = asunto_tpl.format(**context) if asunto_tpl else ""
    df["expone"] = expone_tpl.format(**context) if expone_tpl else ""
    df["solicita"] = solicita_tpl.format(**context) if solicita_tpl else ""
    return df


if __name__ == "__main__":
    id_recurso = 90508
    fase = "denuncia"
    motivos = _load_motivos()
    fase_key = _norm_text(fase)

    if fase_key == "identificacion":
        tipo_recurso = "identificacion_conductor"
    elif fase_key in {"denuncia", "propuesta de resolucion"}:
        tipo_recurso = "alegaciones_denuncia_transito"
    elif fase_key in {
        "sancion",
        "embargo",
        "apremio",
        "reclamaciones",
        "requerimiento embargo",
        "extraordinario de revision",
        "subsanacion",
    }:
        tipo_recurso = "recurso_reposicion"
    else:
        raise ValueError("Fase no valida")

    df = get_recurso_data(id_recurso)
    df = _apply_motivos_by_fase(df, fase, motivos)

    with sync_playwright() as playwright:
        if tipo_recurso == "identificacion_conductor":
            identificacion_conductor(playwright, df)
        elif tipo_recurso == "alegaciones_denuncia_transito":
            alegaciones_denuncia_transito(playwright, df)
        elif tipo_recurso == "recurso_reposicion":
            recurso_reposicion(playwright, df)
