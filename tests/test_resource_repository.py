from core.repositories.resource_repository import ResourceRepository


def test_parse_organisme_patterns_legacy_normalizes_like_tokens() -> None:
    repo = ResourceRepository(conn_str="")

    patterns, mode = repo._parse_organisme_patterns("%AYUNTAMIENTO DE PALMA DE MALLORCA%")

    assert mode == "and"
    assert patterns == ["%AYUNTAMIENTO%", "%DE%", "%PALMA%", "%DE%", "%MALLORCA%"]


def test_parse_organisme_patterns_or_mode_normalizes_each_branch() -> None:
    repo = ResourceRepository(conn_str="")

    patterns, mode = repo._parse_organisme_patterns("%MADRID%|base|XALOC")

    assert mode == "or"
    assert patterns == ["%MADRID%", "%base%", "%XALOC%"]

