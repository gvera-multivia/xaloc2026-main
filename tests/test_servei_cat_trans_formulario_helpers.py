from __future__ import annotations

from sites.servei_cat_trans.flows.formulario import _pais_emisor_candidates


def test_pais_emisor_candidates_expands_iso_country_code() -> None:
    candidates = _pais_emisor_candidates("CO")

    assert "CO" in candidates
    assert "Colombia" in candidates


def test_pais_emisor_candidates_keeps_country_name() -> None:
    candidates = _pais_emisor_candidates("Marruecos")

    assert candidates[0] == "Marruecos"
    assert "Marroc" in candidates
