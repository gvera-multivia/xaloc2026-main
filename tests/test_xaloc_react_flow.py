from pathlib import Path

import pytest

from sites.xaloc_girona.data_models import DatosMulta
from sites.xaloc_girona.flows.react_flow import (
    select_mandate_file,
    select_notification_files,
    split_motivos_for_react,
)


def _target(files: list[Path], *, required_docs: list[Path] | None = None) -> DatosMulta:
    return DatosMulta(
        email="info@xvia-serviciosjuridicos.com",
        num_denuncia="1",
        matricula="1234ABC",
        num_expediente="2026-1-1",
        motivos="motivos",
        archivos_adjuntos=files,
        required_client_doc_paths=required_docs,
    )


def test_select_mandate_prefers_required_client_authorization(tmp_path: Path) -> None:
    recurso = tmp_path / "RECURSO.pdf"
    recurso.write_text("x")
    aut = tmp_path / "AUTORIZACION cliente CF.pdf"
    aut.write_text("x")
    datos = _target([recurso, aut], required_docs=[aut])

    assert select_mandate_file(datos) == aut
    assert select_notification_files(datos, aut) == [recurso]


def test_select_mandate_falls_back_to_authorization_filename(tmp_path: Path) -> None:
    recurso = tmp_path / "RECURSO.pdf"
    recurso.write_text("x")
    aut = tmp_path / "mandat_representacio.pdf"
    aut.write_text("x")
    datos = _target([recurso, aut])

    assert select_mandate_file(datos) == aut


def test_select_mandate_raises_when_missing(tmp_path: Path) -> None:
    recurso = tmp_path / "RECURSO.pdf"
    recurso.write_text("x")
    datos = _target([recurso])

    with pytest.raises(RuntimeError, match="autorizacion/mandato"):
        select_mandate_file(datos)


def test_split_motivos_for_react_expone_solicita() -> None:
    expone, solicita = split_motivos_for_react(
        "ASUNTO: Recurso 123\n\nEXPONE: hechos del recurso\n\nSOLICITA: admision del recurso"
    )

    assert expone == "hechos del recurso"
    assert solicita == "admision del recurso"
