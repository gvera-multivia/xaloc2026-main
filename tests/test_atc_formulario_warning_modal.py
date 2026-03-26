from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sites.atc.flows.formulario import _is_atencio_continue_modal_text, _is_csv_rejected_modal_text


def test_is_atencio_continue_modal_text_detects_deadline_warning() -> None:
    text = (
        "Atenció\n"
        "El termini per presentar la reclamació economicoadministrativa és d’un mes a comptar des de "
        "l’endemà de la notificació. Voleu continuar?"
    )
    assert _is_atencio_continue_modal_text(text) is True


def test_is_atencio_continue_modal_text_ignores_csv_error_modal() -> None:
    text = "No identifiquem el CSV que heu indicat. Reviseu el codi i torneu-ho a provar."
    assert _is_atencio_continue_modal_text(text) is False


def test_is_csv_rejected_modal_text_detects_csv_errors() -> None:
    text = "No identificamos el CSV que ha indicado. Compruebe el código."
    assert _is_csv_rejected_modal_text(text) is True
