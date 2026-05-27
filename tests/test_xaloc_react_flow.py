from pathlib import Path

import pytest

from sites.xaloc_girona.data_models import DatosMandatario, DatosMulta
from sites.xaloc_girona.flows.react_flow import (
    _interesado_doc_and_name_parts,
    _interesado_legal_name,
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


def test_react_representation_prefers_physical_interested_party_over_company() -> None:
    datos = DatosMulta(
        email="info@xvia-serviciosjuridicos.com",
        num_denuncia="2026/45261-MUL",
        matricula="4694DWT",
        num_expediente="2026/45261-MUL",
        motivos="motivos",
        archivos_adjuntos=[Path("RECURSO.pdf")],
        mandatario=DatosMandatario(
            tipo_persona="JURIDICA",
            cif_documento="B0989925",
            cif_control="3",
            razon_social="CORP.PROJECTS HOLDING SOCIEDAD LIMITADA.",
        ),
        interesado_doc="40347979E",
        interesado_nombre="ALFONSO",
        interesado_apellido1="GALVEZ",
        interesado_apellido2="CAMARA",
    )

    assert _interesado_doc_and_name_parts(datos) == ("40347979E", "ALFONSO", "GALVEZ", "CAMARA")


def test_react_representation_keeps_company_when_no_physical_interested_party() -> None:
    datos = DatosMulta(
        email="info@xvia-serviciosjuridicos.com",
        num_denuncia="2026/1-MUL",
        matricula="4694DWT",
        num_expediente="2026/1-MUL",
        motivos="motivos",
        archivos_adjuntos=[Path("RECURSO.pdf")],
        mandatario=DatosMandatario(
            tipo_persona="JURIDICA",
            cif_documento="B0989925",
            cif_control="3",
            razon_social="CORP.PROJECTS HOLDING SOCIEDAD LIMITADA.",
        ),
    )

    assert _interesado_doc_and_name_parts(datos) == (
        "B09899253",
        "CORP.PROJECTS HOLDING SOCIEDAD LIMITADA.",
        "",
        "",
    )
    assert _interesado_legal_name(datos) == "CORP.PROJECTS HOLDING SOCIEDAD LIMITADA."
