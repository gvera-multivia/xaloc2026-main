from __future__ import annotations

from pathlib import Path

import pytest

from sites.atc.data_models import AtcTarget
from sites.atc.flows.confirmacion import _assert_registro_payload_preconditions
from sites.atc.flows.documentos import _assert_registro_minimum_upload_set, _short_desc


def test_atc_registro_short_desc_is_limited_to_15_chars() -> None:
    assert _short_desc("Autorizacion larguisima para cliente") == "Autorizacion la"


def test_atc_registro_requires_resource_and_authorization_docs() -> None:
    has_resource, has_authorization = _assert_registro_minimum_upload_set(
        [
            Path(r"C:\tmp\RECURSO exp - DIL20254019406.pdf"),
            Path(r"C:\tmp\Autoriza_Empresa_solo_20251223103243_43780.pdf"),
        ]
    )

    assert has_resource is True
    assert has_authorization is True


def test_atc_registro_raises_when_authorization_is_missing() -> None:
    with pytest.raises(RuntimeError, match="AUTORIZACION"):
        _assert_registro_minimum_upload_set(
            [
                Path(r"C:\tmp\RECURSO exp - DIL20254019406.pdf"),
                Path(r"C:\tmp\DNI_34762109R.pdf"),
            ]
        )


def test_atc_confirmacion_requires_complete_registro_payload_metadata() -> None:
    datos = AtcTarget(
        protocol="registro_sin_csv",
        payload={
            "atc_expected_registro_attachment_count": 2,
            "atc_has_recurso_doc": True,
            "atc_has_authorization_doc": True,
        },
    )

    assert _assert_registro_payload_preconditions(datos) == 2


def test_atc_confirmacion_rejects_missing_authorization_metadata() -> None:
    datos = AtcTarget(
        protocol="registro_sin_csv",
        payload={
            "atc_expected_registro_attachment_count": 1,
            "atc_has_recurso_doc": True,
            "atc_has_authorization_doc": False,
        },
    )

    with pytest.raises(RuntimeError, match="AUTORIZACION"):
        _assert_registro_payload_preconditions(datos)
