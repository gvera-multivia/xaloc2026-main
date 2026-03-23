from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sites.diputacio_bcn.flows.confirmacion import (
    _ens_candidates,
    _extract_municipio_from_organismo,
    _municipio_candidates,
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
