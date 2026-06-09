from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sites.atc.flows import formulario
from sites.atc.flows.formulario import _is_atencio_continue_modal_text, _is_csv_rejected_modal_text


def test_is_atencio_continue_modal_text_detects_deadline_warning() -> None:
    text = (
        "Atencio\n"
        "El termini per presentar la reclamacio economicoadministrativa es d'un mes a comptar des de "
        "l'endema de la notificacio. Voleu continuar?"
    )
    assert _is_atencio_continue_modal_text(text) is True


def test_is_atencio_continue_modal_text_ignores_csv_error_modal() -> None:
    text = "No identifiquem el CSV que heu indicat. Reviseu el codi i torneu-ho a provar."
    assert _is_atencio_continue_modal_text(text) is False


def test_is_csv_rejected_modal_text_detects_csv_errors() -> None:
    text = "No identificamos el CSV que ha indicado. Compruebe el codigo."
    assert _is_csv_rejected_modal_text(text) is True


@pytest.mark.asyncio
async def test_recover_csv_result_from_atencio_modal_retries_after_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    initial_state = {
        "loading": False,
        "hasCsvRejectedModal": False,
        "continuePresent": True,
        "continueEnabled": False,
        "visibleCheckboxCount": 0,
        "checkedCheckboxCount": 0,
        "singleSelectableCheckbox": False,
    }
    recovered_state = {**initial_state, "continueEnabled": True}

    async def _fake_dismiss(_page: object) -> bool:
        return True

    async def _fake_wait(_page: object, *, timeout_ms: int) -> dict:
        assert timeout_ms == formulario.ATC_FORM_MEDIUM_TIMEOUT_MS
        return recovered_state

    monkeypatch.setattr(formulario, "_dismiss_atencio_continue_modal_if_present", _fake_dismiss)
    monkeypatch.setattr(formulario, "_wait_csv_result_ready", _fake_wait)

    result = await formulario._recover_csv_result_from_atencio_modal_if_needed(object(), initial_state)

    assert result["continueEnabled"] is True
