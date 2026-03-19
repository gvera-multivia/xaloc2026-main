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
    assert normalize_province_alias("Guipuzcoa") == "gipuzkoa"
    assert normalize_province_alias("GIPUZCOA") == "gipuzkoa"


def test_select_heuristic_alias_for_balears_variants() -> None:
    assert normalize_province_alias("MALLORCA") == "illes balears"
    assert normalize_province_alias("Palma de Mallorca") == "illes balears"
    assert normalize_province_alias("ISLAS BALEARES") == "illes balears"


def test_select_heuristic_alias_for_san_andres_de_la_barca() -> None:
    assert normalize_city_alias("SAN ANDRES DE LA BARCA") == "sant andreu de la barca"


def test_select_heuristic_alias_for_puerto_de_sagunto() -> None:
    assert normalize_city_alias("PUERTO DE SAGUNTO") == "sagunto/sagunt"
