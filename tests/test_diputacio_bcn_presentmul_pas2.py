from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sites.diputacio_bcn.flows.presentmul_pas2 import (
    _extract_municipio_from_organismo,
    _municipio_candidates,
)


def test_extract_municipio_from_organismo_ayuntamiento() -> None:
    value = _extract_municipio_from_organismo("Ajuntament de Sant Cugat del Valles")
    assert value == "SANT CUGAT DEL VALLES"


def test_extract_municipio_from_organismo_handles_suffix() -> None:
    value = _extract_municipio_from_organismo("AYUNTAMIENTO DE ABRERA - OFICINA DE MULTAS")
    assert value == "ABRERA"


def test_municipio_candidates_prioritizes_organismo_then_payload() -> None:
    candidates = _municipio_candidates(
        municipio_raw="08019",
        organismo_raw="Ajuntament de Badalona",
    )
    assert candidates[0] == "BADALONA"
    assert "08019" in candidates


def test_municipio_candidates_deduplicates_normalized_values() -> None:
    candidates = _municipio_candidates(
        municipio_raw="SANT CUGAT DEL VALLES",
        organismo_raw="Ajuntament de Sant Cugat del Valles",
    )
    assert candidates == ["SANT CUGAT DEL VALLES"]


def test_extract_municipio_from_organismo_orgt_diba_returns_empty() -> None:
    value = _extract_municipio_from_organismo("ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA")
    assert value == ""


def test_municipio_candidates_orgt_diba_uses_payload_municipio() -> None:
    candidates = _municipio_candidates(
        municipio_raw="SABADELL",
        organismo_raw="ORGANISMO DE GESTION TRIBUTARIA (ORGT) DE LA DIPUTACION DE BARCELONA",
    )
    assert candidates == ["SABADELL"]
