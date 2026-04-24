from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sites.diputacio_bcn.flows.presentmul_pas2 import _is_retryable_signature_error_text


def test_is_retryable_signature_error_text_detects_known_warning() -> None:
    text = (
        "Se ha producido un error durante el proceso de firma. "
        "Intentar repetir la firma de aquí unos segundos y, si persiste el error, "
        "le recomendamos que cierre la sesión y vuelva a iniciar el trámite."
    )
    assert _is_retryable_signature_error_text(text) is True


def test_is_retryable_signature_error_text_ignores_unrelated_text() -> None:
    assert _is_retryable_signature_error_text("Resumen de datos indicados en el formulario web") is False
