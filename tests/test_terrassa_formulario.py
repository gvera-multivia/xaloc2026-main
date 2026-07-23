from __future__ import annotations

from sites.terrassa.flows.formulario import _field_value_matches


def test_field_value_matches_ignores_case_and_accents() -> None:
    assert _field_value_matches("RAUL", "Raul")
    assert _field_value_matches("MARIA TERESA", "Maria Teresa")
    assert _field_value_matches("JOSÉ LUIS", "Jose Luis")
    assert _field_value_matches("  ANA   ISABEL  ", "Ana Isabel")
    assert _field_value_matches("34765386N", "34765386N")
    assert not _field_value_matches("RAUL", "")
    assert not _field_value_matches("RAUL", "PAUL")
    assert not _field_value_matches("34765386N", "34765386M")
