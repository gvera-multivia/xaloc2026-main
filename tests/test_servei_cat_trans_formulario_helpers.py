from __future__ import annotations

from sites.servei_cat_trans.flows.formulario import (
    _KNOWN_MUNICIPIO_CODES,
    _known_municipio_code_label,
    _norm_text,
    _pais_emisor_candidates,
)


def test_pais_emisor_candidates_expands_iso_country_code() -> None:
    candidates = _pais_emisor_candidates("CO")

    assert "CO" in candidates
    assert "COL" in candidates
    assert "170" in candidates
    assert "Colombia" in candidates


def test_pais_emisor_candidates_keeps_country_name() -> None:
    candidates = _pais_emisor_candidates("Marruecos")

    assert candidates[0] == "Marruecos"
    assert "Marroc" in candidates


def test_known_municipio_codes_supports_hospitalet_aliases() -> None:
    assert _KNOWN_MUNICIPIO_CODES[_norm_text("L'Hospitalet de Llobregat")] == (
        "08101",
        "Hospitalet de Llobregat, l'",
    )
    assert _known_municipio_code_label("Hospitalet de Llobregat, l'") == (
        "08101",
        "Hospitalet de Llobregat, l'",
    )


def test_known_municipio_codes_supports_hospitalet_cp() -> None:
    assert _known_municipio_code_label("", "08902") == (
        "08101",
        "Hospitalet de Llobregat, l'",
    )
