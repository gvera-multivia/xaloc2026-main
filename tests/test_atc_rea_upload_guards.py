from __future__ import annotations

from pathlib import Path

import pytest

from sites.atc.data_models import AtcDocumento
from sites.atc.flows.documentos import _build_rea_repos_upload_plan, _row_matches_expected_upload


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
        "RECURSO Al·legacions",
        desc="RECURSO",
        tipus="Al-legacions",
    ) is True
    assert _row_matches_expected_upload(
        "AUTORIZACION Al·legacions",
        desc="RECURSO",
        tipus="Al-legacions",
    ) is False
    assert _row_matches_expected_upload(
        "RECURSO Documentacio acreditativa",
        desc="RECURSO",
        tipus="Al-legacions",
    ) is False
