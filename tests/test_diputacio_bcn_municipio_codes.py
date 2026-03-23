from __future__ import annotations

from sites.diputacio_bcn.municipio_codes import resolve_codmuni


def test_resolve_codmuni_by_name() -> None:
    assert resolve_codmuni("SABADELL") == "186"
    assert resolve_codmuni("Sant Cugat del Vallès") == "204"


def test_resolve_codmuni_accepts_common_aliases() -> None:
    assert resolve_codmuni("SANT BOI DEL LLOBREGAT") == "199"
    assert resolve_codmuni("L'HOSPITALET DE LLOBREGAT") == "100"


def test_resolve_codmuni_by_numeric_input() -> None:
    assert resolve_codmuni("186") == "186"
    assert resolve_codmuni("080186") == "186"
    assert resolve_codmuni("08186") == "186"
