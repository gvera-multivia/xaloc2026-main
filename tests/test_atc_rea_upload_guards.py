from __future__ import annotations

from pathlib import Path

import pytest

from sites.atc.data_models import AtcDocumento
from sites.atc.flows.documentos import (
    _build_rea_repos_upload_plan,
    _is_reposicio_fourth_option_target,
    _normalize_attachment_text,
    _reposicio_checkbox_state_matches_target,
    _reposicio_checkbox_text_matches,
    _row_matches_expected_upload,
)


def test_atc_rea_upload_plan_prioritizes_resource_and_authorization() -> None:
    plan = _build_rea_repos_upload_plan(
        [
            AtcDocumento(fitxer=Path(r"C:\tmp\Autoriza_Empresa_solo_20251223103243_43780.pdf")),
            AtcDocumento(fitxer=Path(r"C:\tmp\RECURSO exp - DIL20254019406.pdf")),
            AtcDocumento(fitxer=Path(r"C:\tmp\DNI_34762109R.pdf")),
        ],
        protocol="rea",
    )

    assert [str(item["kind"]) for item in plan] == ["resource", "authorization", "other"]
    assert [str(item["descripcio"]) for item in plan[:2]] == ["RECURSO", "AUTORIZACION"]
    assert [str(item["tipus"]) for item in plan] == [
        "Al-legacions",
        "Documentacio acreditativa",
        "Documentacio acreditativa",
    ]


def test_atc_rea_upload_plan_requires_resource_and_authorization() -> None:
    with pytest.raises(RuntimeError, match="AUTORIZACION"):
        _build_rea_repos_upload_plan(
            [
                AtcDocumento(fitxer=Path(r"C:\tmp\RECURSO exp - DIL20254019406.pdf")),
                AtcDocumento(fitxer=Path(r"C:\tmp\DNI_34762109R.pdf")),
            ],
            protocol="rea",
        )


def test_atc_rea_row_match_requires_expected_type_for_resource() -> None:
    assert _row_matches_expected_upload(
        "RECURSO Al-legacions",
        desc="RECURSO",
        tipus="Al-legacions",
    ) is True
    assert _row_matches_expected_upload(
        "AUTORIZACION Al-legacions",
        desc="RECURSO",
        tipus="Al-legacions",
    ) is False
    assert _row_matches_expected_upload(
        "RECURSO Documentacio acreditativa",
        desc="RECURSO",
        tipus="Al-legacions",
    ) is False


def test_atc_reposicio_checkbox_match_tolerates_partial_text() -> None:
    assert _reposicio_checkbox_text_matches(
        "no se m ha notificat la provisio de constrenyiment",
        "No se m'ha notificat la provisio de constrenyiment.",
    ) is True


def test_atc_reposicio_no_notification_target_uses_fourth_option() -> None:
    assert _is_reposicio_fourth_option_target(
        "No se m'ha notificat la provisio de constrenyiment."
    ) is True
    assert _is_reposicio_fourth_option_target(
        "No se me ha notificado la providencia de apremio."
    ) is True
    assert _is_reposicio_fourth_option_target(
        "No se me ha notificado"
    ) is True


def test_atc_reposicio_checkbox_normalization_strips_accents_and_apostrophes() -> None:
    assert _normalize_attachment_text("No se m'ha notificat la provisio de constrenyiment.") == (
        "no se m ha notificat la provisio de constrenyiment"
    )


def test_atc_reposicio_checkbox_state_accepts_fourth_checked_even_with_broken_label() -> None:
    state = {
        "checkedLabels": ["no se m ha notificat la provisia de constrenyiment"],
        "checkedIndexes": [4],
    }
    assert _reposicio_checkbox_state_matches_target(
        state,
        "No se m'ha notificat la provisio de constrenyiment.",
    ) is True
