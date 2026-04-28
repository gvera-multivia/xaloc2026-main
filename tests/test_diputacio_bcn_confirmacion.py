from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sites.diputacio_bcn.flows.confirmacion import (
    _ens_candidates,
    _extract_municipio_from_organismo,
    _format_matricula_for_diputacio,
    _municipio_candidates,
    _resolve_matricula_value,
)


def test_extract_municipio_from_organismo() -> None:
    value = _extract_municipio_from_organismo("Ajuntament de Sant Cugat del Valles")
    assert value == "SANT CUGAT DEL VALLES"


def test_municipio_candidates_prioritize_organismo() -> None:
    candidates = _municipio_candidates("08019", "Ajuntament de Badalona")
    assert candidates[0] == "BADALONA"
    assert "08019" in candidates


def test_ens_candidates_for_orgt_diba() -> None:
    candidates = _ens_candidates("ORGANISMO DE GESTION TRIBUTARIA DIPUTACION BARCELONA")
    assert "ORG.DE GESTIO TRIBUTARIA" in candidates
    assert "DIPUTACIO DE BARCELONA" in candidates


def test_extract_municipio_from_organismo_orgt_diba_returns_empty() -> None:
    value = _extract_municipio_from_organismo("ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA")
    assert value == ""


def test_municipio_candidates_orgt_diba_uses_payload_municipio() -> None:
    candidates = _municipio_candidates(
        municipio_raw="SABADELL",
        organismo_raw="ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
    )
    assert candidates == ["SABADELL"]


def test_format_matricula_for_diputacio_adds_hyphen_for_modern_plate() -> None:
    assert _format_matricula_for_diputacio("1234BCD") == "1234-BCD"


class _DummyTarget:
    def __init__(self, matricula: str = "", payload: dict | None = None) -> None:
        self.matricula = matricula
        self.payload = payload or {}


def test_resolve_matricula_value_prefers_target_then_payload_fallbacks() -> None:
    target = _DummyTarget(payload={"Matricula": "1234BCD"})
    value, sources = _resolve_matricula_value(target)
    assert value == "1234-BCD"
    assert sources["payload.Matricula"] == "1234BCD"


def test_resolve_matricula_value_returns_empty_when_all_sources_missing() -> None:
    target = _DummyTarget(payload={"matricula": ".", "Matricula": "", "rs_matricula": ""})
    value, sources = _resolve_matricula_value(target)
    assert value == ""
    assert sources["payload.matricula"] == "."
