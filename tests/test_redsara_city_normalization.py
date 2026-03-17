from __future__ import annotations

from sites.redsara.controller import _normalize_city_for_redsara
from sites.redsara.flows.select_heuristic import normalize_city_alias, normalize_province_alias


def test_controller_normalizes_les_franqueses_to_valles_ascii() -> None:
    out = _normalize_city_for_redsara("LES FRANQUESES DEL VALLES")
    assert out == "FRANQUESES DEL VALLES, LES"


def test_controller_normalizes_nucleo_municipio_form() -> None:
    out = _normalize_city_for_redsara("BELLAVISTA - LES FRANQUESES DEL VALLES")
    assert out == "FRANQUESES DEL VALLES, LES"


def test_select_heuristic_alias_for_les_franqueses() -> None:
    out = normalize_city_alias("LES FRANQUESES DEL VALLES")
    assert out == "Franqueses del Valles, Les"


def test_select_heuristic_alias_for_guipuzcoa_variants() -> None:
    assert normalize_province_alias("GUIPUZCOA") == "gipuzkoa"
    assert normalize_province_alias("Guipúzcoa") == "gipuzkoa"
    assert normalize_province_alias("GIPUZCOA") == "gipuzkoa"
