from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sites.diputacio_bcn.texts import build_fets_solicitud, resolve_phase_texts


def test_resolve_phase_texts_uses_config_motivos_templates() -> None:
    asunto, expone, solicita = resolve_phase_texts(
        fase_procedimiento="sancion",
        expediente="R000094073",
        sujeto_recurso="MARIA AZORIN RUBIO",
    )

    assert asunto == "Recurso de Reposición frente a Sanción"
    assert "RESOLUCION SANCIONADORA" in expone
    assert "R000094073" in solicita


def test_build_fets_solicitud_prioritizes_payload_values() -> None:
    text = build_fets_solicitud(
        fase_procedimiento="sancion",
        expediente="EXP-1",
        sujeto_recurso="TEST USER",
        asunto="Asunto custom",
        expone="Expone custom",
        solicita="Solicita custom",
    )

    assert text == "ASUNTO: Asunto custom\n\nEXPONE: Expone custom\n\nSOLICITA: Solicita custom"
