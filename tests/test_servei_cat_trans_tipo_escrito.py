from __future__ import annotations

import os
import sys
from typing import Any

sys.path.append(os.getcwd())

from sites.servei_cat_trans.controller import ServeiCatTransController


def _base_payload() -> dict:
    return {
        "expediente": "08/1234567-1",
        "nombre": "NOMBRE",
        "apellido1": "APELLIDO1",
        "nif": "12345678Z",
    }


def test_tipo_escrito_alegaciones_group_by_fase() -> None:
    controller = ServeiCatTransController()
    payload = _base_payload()
    payload["FaseProcedimiento"] = "propuesta de resolución                           "

    mapped = controller.map_data(payload)

    assert mapped["tipo_escrito"] == "alegaciones"


def test_tipo_escrito_reposicion_group_by_fase() -> None:
    controller = ServeiCatTransController()
    payload = _base_payload()
    payload["FaseProcedimiento"] = "APREMIO Persona Física"

    mapped = controller.map_data(payload)

    assert mapped["tipo_escrito"] == "reposicion"


def test_tipo_escrito_revision_priority_by_procedim() -> None:
    controller = ServeiCatTransController()
    payload = _base_payload()
    payload["FaseProcedimiento"] = "sancion"
    payload["Procedim"] = "Trámite de Recurso Extraordinario por error material"

    mapped = controller.map_data(payload)

    assert mapped["tipo_escrito"] == "revision"


def test_nif_without_letter_gets_completed() -> None:
    controller = ServeiCatTransController()
    payload = _base_payload()
    payload["nif"] = "12345678"

    mapped = controller.map_data(payload)

    assert mapped["nif"] == "12345678Z"


def test_address_enrichment_uses_llm_and_cartociudad_only_for_comarca(monkeypatch: Any) -> None:
    controller = ServeiCatTransController()

    def _fake_llm(**kwargs: Any) -> dict[str, str]:
        del kwargs
        return {
            "tipo_via": "CALLE",
            "calle": "MALLORCA",
            "numero": "401",
            "escalera": "",
            "planta": "",
            "puerta": "",
        }

    monkeypatch.setattr(
        ServeiCatTransController,
        "_classify_address_with_groq",
        classmethod(lambda cls, **kwargs: _fake_llm(**kwargs)),
    )
    monkeypatch.setattr(
        ServeiCatTransController,
        "_query_comarca_cartociudad",
        classmethod(lambda cls, **kwargs: "BARCELONES"),
    )

    mapped = controller.map_data(
        {
            "expediente": "08/1234567-1",
            "nombre": "NOMBRE",
            "apellido1": "APELLIDO1",
            "nif": "12345678Z",
            "representado_calle_raw": "CL Mallorca",
            "representado_cp": "08013",
            "representado_municipio": "BARCELONA",
            "representado_provincia": "Barcelona",
        }
    )

    assert mapped["representado_tipo_via"] == "CALLE"
    assert mapped["representado_nombre_via"] == "MALLORCA"
    assert mapped["representado_numero"] == "401"
    assert mapped["representado_cp"] == "08013"
    assert mapped["representado_municipio"] == "BARCELONA"
    assert mapped["representado_comarca"] == "BARCELONES"


def test_general_mitre_forces_ronda(monkeypatch: Any) -> None:
    controller = ServeiCatTransController()

    monkeypatch.setattr(
        ServeiCatTransController,
        "_classify_address_with_groq",
        classmethod(
            lambda cls, **kwargs: {
                "tipo_via": "CALLE",
                "calle": "GENERAL MITRE",
                "numero": "169",
                "escalera": "",
                "planta": "",
                "puerta": "",
            }
        ),
    )
    mapped = controller.map_data(
        {
            "expediente": "08/1234567-1",
            "nombre": "NOMBRE",
            "apellido1": "APELLIDO1",
            "nif": "12345678Z",
            "representado_calle_raw": "Ronda General Mitre 169",
            "representado_provincia": "Barcelona",
            "representado_municipio": "BARCELONA",
        }
    )

    assert mapped["representado_tipo_via"] == "RONDA"


def test_representado_uses_cliente_fallbacks_when_raw_missing(monkeypatch: Any) -> None:
    controller = ServeiCatTransController()
    monkeypatch.setattr(
        ServeiCatTransController,
        "_classify_address_with_groq",
        classmethod(lambda cls, **kwargs: {"tipo_via": "AVENIDA", "calle": "DIAGONAL", "numero": "10", "escalera": "", "planta": "", "puerta": ""}),
    )
    mapped = controller.map_data(
        {
            "expediente": "08/1234567-1",
            "nombre": "NOMBRE",
            "apellido1": "APELLIDO1",
            "nif": "12345678Z",
            "cliente_domicilio": "Av Diagonal",
            "cliente_numero": "10",
            "cliente_cp": "08019",
            "cliente_municipio": "Barcelona",
            "cliente_provincia": "Barcelona",
        }
    )

    assert mapped["representado_nombre_via"] == "DIAGONAL"
    assert mapped["representado_cp"] == "08019"


def test_representado_cp_never_comes_from_cartociudad(monkeypatch: Any) -> None:
    controller = ServeiCatTransController()
    monkeypatch.setattr(
        ServeiCatTransController,
        "_classify_address_with_groq",
        classmethod(lambda cls, **kwargs: {"tipo_via": "CALLE", "calle": "MALLORCA", "numero": "401", "escalera": "", "planta": "", "puerta": ""}),
    )
    monkeypatch.setattr(
        ServeiCatTransController,
        "_query_comarca_cartociudad",
        classmethod(lambda cls, **kwargs: "BARCELONES"),
    )

    mapped = controller.map_data(
        {
            "expediente": "08/1234567-1",
            "nombre": "NOMBRE",
            "apellido1": "APELLIDO1",
            "nif": "12345678Z",
            "representado_calle_raw": "CL Mallorca",
            "cliente_cp": "08019",
            "cliente_municipio": "BARCELONA",
            "cliente_provincia": "Barcelona",
        }
    )

    assert mapped["representado_cp"] == "08019"
